"""用户态 TCP 网络损伤代理 —— E4 的"软件版 netem"。

## 为什么不用 netem / WSL

原计划是在 Ubuntu VM 里用 `tc qdisc netem` 注入损伤。本机没有 WSL 发行版，
装一个要下载并可能重启；也不该为一个实验去改系统。

所以写这个**用户态**代理：机器人连代理，代理连真实服务端，中间按配置注入延迟。

## ⚠️ 关键方法论：TCP 上"丢包"的表现是**延迟**，不是丢帧

这是本实验最重要、也最容易被问倒的一点，写在这里免得后面忘：

| 注入方式 | 网络层发生什么 | 应用层看到什么 |
|---|---|---|
| **netem 丢包**（IP 层） | 数据段被丢 → TCP **重传** | **不会少收快照**，只是**来晚了**（RTO 量级的延迟尖峰） |
| **应用层丢帧**（`bot --sim-loss`） | 整帧被丢弃 | 真的**少收一帧** |

我们的传输层是 **TCP**，所以"丢包率 vs 插值误差"这条曲线，
**机制是"丢包 → 重传 → 等效额外延迟 → 误差变大"**，而不是"丢了帧所以画面缺点"。

本代理因此这样模拟"丢包"：**按概率给该数据块额外加一个 RTO 量级的延迟**
（默认 200 ms，Linux TCP 的最小 RTO 是 200 ms）。这是可论证的等价：
netem 丢一个段，TCP 至少要等一个 RTO 才重传，应用层看到的就是一次 200 ms 的停顿。

`bot --sim-loss` 保留，但**只用于验证测量逻辑**，不作为 E4 主实验 —— 它模拟的是
UDP 式丢帧，和本项目的 TCP 行为不是一回事。

## 延迟口径

`--delay-ms D` 给**每个方向**都加 D，所以一个请求-响应往返增加约 **2D**，
等同于"单程 D 毫秒的链路"。论文里写口径时要写清楚。

## 保序

延迟抖动如果让后面的块先到，字节流就乱了 —— TCP 流不允许乱序，解析器会直接崩。
所以每个方向维护一个"最早可放行时刻"，单调不减：
后到的块必须等前面的放完。这也是真实链路的行为（TCP 会重排，应用层看到的是顺序流）。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.netem_proxy \\
        --listen 9700 --upstream 9527 --delay-ms 100 --jitter-ms 20 --loss-pct 5
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time

CHUNK = 64 * 1024

# Linux TCP 的最小重传超时。netem 丢一个段，应用层至少等这么久才看到数据。
DEFAULT_RTO_MS = 200.0


class ProxyStats:
    """代理侧计数 —— 用来证明"损伤真的注入了"，而不是只有配置没有效果。"""

    def __init__(self) -> None:
        self.connections = 0
        self.up_bytes = 0      # 客户端 → 服务端
        self.down_bytes = 0    # 服务端 → 客户端
        self.simulated_retransmits = 0
        self.delay_events = 0

    def as_dict(self) -> dict:
        return {
            "connections": self.connections,
            "up_bytes": self.up_bytes,
            "down_bytes": self.down_bytes,
            "simulated_retransmits": self.simulated_retransmits,
            "delay_events": self.delay_events,
        }


class LinkConfig:
    def __init__(self, delay_ms: float = 0.0, jitter_ms: float = 0.0,
                 loss_pct: float = 0.0, rto_ms: float = DEFAULT_RTO_MS) -> None:
        self.delay_ms = max(0.0, delay_ms)
        self.jitter_ms = max(0.0, jitter_ms)
        self.loss_pct = min(100.0, max(0.0, loss_pct))
        self.rto_ms = max(0.0, rto_ms)

    def next_delay_s(self, rng: random.Random) -> tuple[float, bool]:
        """这一块要延迟多久（秒），以及是否模拟了一次"丢包重传"。"""
        delay = self.delay_ms
        if self.jitter_ms > 0:
            delay += rng.uniform(0.0, self.jitter_ms)
        retransmit = False
        if self.loss_pct > 0 and rng.random() * 100.0 < self.loss_pct:
            delay += self.rto_ms
            retransmit = True
        return delay / 1000.0, retransmit


async def _pump(
    src: asyncio.StreamReader,
    dst: asyncio.StreamWriter,
    link: LinkConfig,
    rng: random.Random,
    stats: ProxyStats,
    direction: str,
) -> None:
    """把一个方向的字节流按延迟规则搬到对端。**保序 + 绝对截止时刻**。

    ⚠️ 这里踩过两个坑，都写下来免得改回去（2026-11-04）：

    **坑① 用相对 sleep 会累积漂移。**
    第一版按 `release_at = max(prev, now + d)` 循环 `sleep(remaining)`。
    单包测试正确（100 ms → 往返 220 ms），但**持续流量下积压无界增长**：
    Windows 定时器精度 ~15 ms，每次 sleep 都晚一点，20 Hz 的数据每 50 ms 来一块，
    释放点永远追不上到达点。实测 100 ms 配置跑出 433 ms 的往返。

    **坑② 串行"读-等-写"会制造突发。**
    改成"读一块 → 等 D → 写一块"后不再漂移，但读的间隔被 D 拖长，
    期间多帧堆在 socket 缓冲里，下一次 read 会**一次拿到好几帧**、
    一次性写出去 → 到达间隔 p50 塌成 0.35 ms，等效延迟变成 `D + 最多 D`。

    **最终做法：读写分离 + 绝对截止时刻。**
    - 读协程只管尽快读，把 `(到达时刻 + D, data)` 压进队列
    - 写协程按队列顺序等**绝对时刻**再写
    某次 sleep 超时只影响那一块；下一块的截止点是绝对的，自动把误差吸收掉，不累积。
    队列 FIFO 天然保序（抖动导致的乱序会被推迟到前一块之后，牺牲一点抖动精度换正确性）。
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=4096)
    loop = asyncio.get_running_loop()

    async def reader() -> None:
        while True:
            data = await src.read(CHUNK)
            if not data:
                break
            delay_s, retransmit = link.next_delay_s(rng)
            if retransmit:
                stats.simulated_retransmits += 1
            if delay_s > 0:
                stats.delay_events += 1
            await queue.put((loop.time() + delay_s, data))
        await queue.put(None)  # 结束标记

    async def writer() -> None:
        while True:
            item = await queue.get()
            if item is None:
                break
            release_at, data = item
            remaining = release_at - loop.time()
            if remaining > 0:
                await asyncio.sleep(remaining)
            try:
                dst.write(data)
                await dst.drain()
            except (ConnectionError, RuntimeError):
                break
            if direction == "up":
                stats.up_bytes += len(data)
            else:
                stats.down_bytes += len(data)

    try:
        await asyncio.gather(reader(), writer())
    finally:
        try:
            dst.close()
        except (ConnectionError, RuntimeError):
            pass


async def _handle(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream: tuple[str, int],
    link: LinkConfig,
    stats: ProxyStats,
    rng: random.Random,
) -> None:
    stats.connections += 1
    try:
        server_reader, server_writer = await asyncio.open_connection(*upstream)
    except OSError:
        client_writer.close()
        return

    try:
        await asyncio.gather(
            _pump(client_reader, server_writer, link, rng, stats, "up"),
            _pump(server_reader, client_writer, link, rng, stats, "down"),
        )
    except (ConnectionError, RuntimeError):
        pass
    finally:
        for writer in (client_writer, server_writer):
            try:
                writer.close()
            except (ConnectionError, RuntimeError):
                pass


async def serve(args: argparse.Namespace) -> None:
    link = LinkConfig(args.delay_ms, args.jitter_ms, args.loss_pct, args.rto_ms)
    stats = ProxyStats()
    rng = random.Random(args.seed)

    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, (args.upstream_host, args.upstream), link, stats, rng),
        args.listen_host,
        args.listen,
    )
    print(
        f"[proxy] {args.listen_host}:{args.listen} -> "
        f"{args.upstream_host}:{args.upstream}  "
        f"delay={link.delay_ms:g}ms(+jitter {link.jitter_ms:g}) "
        f"loss={link.loss_pct:g}%(+RTO {link.rto_ms:g}ms)",
        flush=True,
    )

    async with server:
        try:
            await asyncio.sleep(args.duration if args.duration > 0 else 1e9)
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass
    print(f"[proxy] stats: {stats.as_dict()}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用户态 TCP 网络损伤代理（E4 用）")
    parser.add_argument("--listen", type=int, default=9700, help="代理监听端口")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--upstream", type=int, default=9527, help="真实服务端端口")
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--delay-ms", type=float, default=0.0,
                        help="**每个方向**的固定延迟；RTT 约增加 2×该值")
    parser.add_argument("--jitter-ms", type=float, default=0.0, help="随机抖动上限")
    parser.add_argument("--loss-pct", type=float, default=0.0,
                        help="模拟丢包率：按概率给数据块加一个 RTO 量级的延迟"
                             "（TCP 会重传，应用层看到的是「来晚了」而不是「丢了」）")
    parser.add_argument("--rto-ms", type=float, default=DEFAULT_RTO_MS,
                        help="模拟重传的额外延迟（默认 200 ms = Linux TCP 最小 RTO）")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--duration", type=float, default=0.0,
                        help="跑多少秒后退出（0 = 一直跑，用 Ctrl+C 停）")
    return parser.parse_args()


def main() -> None:
    asyncio.run(serve(parse_args()))


if __name__ == "__main__":
    main()