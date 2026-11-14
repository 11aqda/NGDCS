"""`--live-metrics`：把每秒指标写进 Redis Hash，供 Django 看板实时读取。

## 为什么单独一个模块

CSV 是**给实验/论文**的（追加写、按秒一行、可复算），Redis 是**给看板**的
（只关心"现在怎么样"，10 秒不写就该消失）。两者生命周期完全不同，
所以 CSV 链路一行不改，只在旁边挂一个发布器。

## 口径（2026-11-14 定）

| 项 | 值 |
|---|---|
| key | `ngdcs:metrics:live` |
| 写入 | 每秒一次 `HSET`，字段与 CSVMetrics 的列同名 |
| 过期 | 每次写完 `EXPIRE 10`（TTL 10 秒）→ 服务端停了，key 自动消失 |
| 开关 | `--live-metrics`，**默认关**：实验基线不碰 Redis（同 `--persist-scores` 的理由） |
| 线程 | 真正写 Redis 在 `asyncio.to_thread` 里，**绝不阻塞 tick** |
| 失败 | 只记日志（首次 + 每 60 秒一次），不影响对局 |

## 为什么用队列 + 后台任务，而不是在 tick 里 await

如果 tick_loop 里 `await to_thread(写 Redis)`，Redis 卡 0.5 秒，tick 就跟着停 0.5 秒 ——
"不阻塞"就只是嘴上说说。所以这里：`publish()` 只做 `put_nowait`（微秒级），
由独立协程消费队列。队列只有 2 格，Redis 慢了就丢掉旧采样，**要最新值不要全量**。
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

LIVE_METRICS_KEY = "ngdcs:metrics:live"
LIVE_METRICS_TTL = 10

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0

# 连接/读写超时：Redis 没起时也不能让线程池里的调用挂太久
REDIS_TIMEOUT = 0.5

# 失败日志节流：一秒一条 warning 会把日志刷爆
FAILURE_LOG_INTERVAL = 60.0


def make_client(
    host: str = REDIS_HOST, port: int = REDIS_PORT, db: int = REDIS_DB
):
    """懒加载 redis 客户端（`redis` 包已在 venv 里，见 requirements/F-01）。

    **必须 `protocol=2`**：本机 Redis 是 5.0.14，不支持 RESP3 的 `HELLO` 命令；
    redis-py 8.x 默认会先发 `HELLO 3`，于是直接报
    `unknown command 'HELLO'` —— 看起来像"Redis 连不上"，其实是协议版本不对。
    """
    import redis  # 局部导入：没装 redis 时只有开这个开关才会报错

    return redis.Redis(
        host=host,
        port=port,
        db=db,
        socket_connect_timeout=REDIS_TIMEOUT,
        socket_timeout=REDIS_TIMEOUT,
        decode_responses=True,
        protocol=2,
    )


class LiveMetricsPublisher:
    """每秒一行的指标 → Redis Hash。

    `client` 参数留给测试注入假客户端；正常路径不传，第一次写入时才建连接。
    """

    def __init__(
        self,
        *,
        key: str = LIVE_METRICS_KEY,
        ttl: int = LIVE_METRICS_TTL,
        client=None,
        queue_size: int = 2,
    ) -> None:
        self.key = key
        self.ttl = ttl
        self._client = client
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task | None = None
        self._last_error_at = 0.0
        self._failing = False
        self.written = 0
        self.failed = 0

    # ---- 对外 ----
    def publish(self, payload: dict) -> None:
        """投递一行指标（同步、非阻塞）。队列满了就丢最旧的一行。"""
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - 理论竞态
                pass
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover
                pass

    def start(self) -> asyncio.Task:
        """启动消费协程（必须在事件循环里调用）。返回任务便于测试/停机。"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # ---- 内部 ----
    def _write_now(self, payload: dict) -> None:
        """真正写 Redis（同步，跑在线程池里）。"""
        client = self._client if self._client is not None else make_client()
        if self._client is None:
            self._client = client
        pipe = client.pipeline()
        pipe.hset(self.key, mapping=dict(payload))
        pipe.expire(self.key, self.ttl)
        pipe.execute()

    async def consume_once(self) -> None:
        """取一行、写一次。异常在这里吞掉（失败不影响 tick）。"""
        payload = await self._queue.get()
        try:
            await asyncio.to_thread(self._write_now, payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Redis 挂了也不能影响对局
            self.failed += 1
            self._note_failure(exc)
        else:
            self.written += 1
            if self._failing:
                self._failing = False
                logger.info("Redis 实时指标已恢复写入（%s）", self.key)

    def _note_failure(self, exc: Exception) -> None:
        now = time.monotonic()
        if not self._failing or now - self._last_error_at >= FAILURE_LOG_INTERVAL:
            logger.warning("写 Redis 实时指标失败（不影响对局）：%s", exc)
            self._last_error_at = now
        self._failing = True

    async def _run(self) -> None:
        while True:
            await self.consume_once()
