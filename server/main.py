"""阶段 1 · 第 8 步（8a）：服务端 + 占位实体 + 指标落盘。

在 7b（输入 + 心跳 + 超时）之上补两件事：

    1. **占位实体**：`--enemies N --bullets M` 开出一批「匀速直线飞」的敌机与子弹，
       让 E9 的自变量（同屏实体数）存在。实体结构与协议条目与最终版本一致（D-010）
    2. **指标落盘**：每秒把 tick 耗时 / 快照体积 / 收发流量 / CPU / 内存
       追加写进 CSV，供 tools/plot.py 出图

本步不做：
    - 敌机 AI、碰撞、伤害、掉落、波次、BOSS（全在第 11 步）
    - 房间、认证（第 10 步）
    - S_PLAYER_LEAVE (0x86)：D-012 已确立「快照是全量真相」，事件同步留给游戏内容阶段
    - 慢客户端的独立发送队列（D-020 记的账，压测阶段再还）

用法：
    .venv\\Scripts\\python.exe -X utf8 -m server.main
    .venv\\Scripts\\python.exe -X utf8 -m server.main --enemies 30 --bullets 200 --scenario E9-e30-b200-01
    .venv\\Scripts\\python.exe -X utf8 -m server.main --timeout 0 --no-stats --no-metrics
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from protocol.framing import (
    HEADER,
    Frame,
    ProtocolError,
    recv_frame_async,
    send_frame_async,
)
from protocol.messages import (
    C_HEARTBEAT,
    C_INPUT,
    S_HEARTBEAT_ACK,
    S_SNAPSHOT,
    S_WELCOME,
    WELCOME,
    now_ms,
    pack_heartbeat_ack,
    unpack_heartbeat,
    unpack_keys,
)
from protocol.snapshot import PlayerSnapshot
from protocol.encoders import ENCODER_NAMES, SnapshotEncoder, get_encoder
from server.entities import World, detect_collisions
from server.metrics import MetricsRecorder, write_scenario
from server.movement import apply_input
from server.stats import TickStats

HOST = "0.0.0.0"
PORT = 9527
TICK_HZ = 20
TICK_INTERVAL = 1 / TICK_HZ

# 02 §7：超时 = 3 × 心跳间隔，单次心跳丢失不应导致误判断线
HEARTBEAT_TIMEOUT = 15.0

# 输入的保质期：超过这么久没收到新输入就当作「松手」。
# 没有它的话，客户端卡死 / 拔网线前的最后一帧如果是「按住左」，
# 玩家会一直往左走到 15 s 超时被踢 —— 观感上是「幽灵移动」。
INPUT_TTL = 0.5

# 每秒一个统计窗口（20 个 tick），也是指标 CSV 的行频
STATS_EVERY_TICKS = TICK_HZ

DEFAULT_METRICS_PATH = "data/server_metrics.csv"


@dataclass
class Client:
    player_id: int
    color: int
    x: int
    y: int
    writer: asyncio.StreamWriter
    keys: int = 0
    last_input_at: float = field(default_factory=time.perf_counter)
    last_recv_at: float = field(default_factory=time.perf_counter)


class GameServer:
    def __init__(
        self,
        timeout: float = HEARTBEAT_TIMEOUT,
        input_ttl: float = INPUT_TTL,
        stats: TickStats | None = None,
        world: World | None = None,
        metrics: MetricsRecorder | None = None,
        print_stats: bool = True,
        encoder: SnapshotEncoder | None = None,
    ) -> None:
        self.clients: dict[int, Client] = {}
        self.next_id = 1
        self.tick = 0
        self.timeout = timeout
        self.input_ttl = input_ttl
        self.stats = stats if stats is not None else TickStats()
        self.world = world if world is not None else World()
        self.metrics = metrics
        self.print_stats_enabled = print_stats
        # 默认标准二进制编码；E1 实验会换成 binary_fast / json（见 protocol/encoders.py）
        self.encoder = encoder if encoder is not None else get_encoder("binary")

    # ---------------------------------------------------------------- 连接

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        player_id = self.next_id
        self.next_id += 1
        color = player_id % 8

        client = Client(
            player_id=player_id,
            color=color,
            # 竖版飞机大战：从底部附近出发，横向居中
            x=360,
            y=760 - ((player_id - 1) % 4) * 60,
            writer=writer,
        )
        self.clients[player_id] = client
        print(f"[server] player {player_id} joined from {peer} (color={color})")

        try:
            # 先告诉客户端“你是谁”，再开始收输入 / 心跳
            await send_frame_async(writer, S_WELCOME, 0, WELCOME.pack(player_id, color))

            while True:
                frame = await recv_frame_async(reader)
                if frame is None:
                    break
                # 收到任何消息都算「这个连接还活着」，不只是心跳
                client.last_recv_at = time.perf_counter()
                self.stats.record_in_frame(HEADER.size + len(frame.payload))
                await self.dispatch(client, frame)
        except ProtocolError as exc:
            # magic / version / length / 载荷长度错误。
            # 此时字节流已经不可信，必须断开。
            print(f"[server] protocol error: {exc}")
        except (ConnectionError, RuntimeError):
            # 客户端正常/强制断开；这是常态，不当作服务器错误
            pass
        finally:
            # **唯一的清理点**：超时判定只关 writer，实际清理只在这里做，
            # 避免两处都改 clients 字典（删两次 / 删错人）
            self.clients.pop(player_id, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass
            print(f"[server] player {player_id} left")

    async def dispatch(self, client: Client, frame: Frame) -> None:
        """处理一条客户端消息。

        不认识的类型**静默忽略**（前向兼容：将来加消息时旧服务端不会崩），
        但要先过帧层的 magic / version 校验 —— 那关已经由 recv_frame_async 把过了。
        """
        if frame.msg_type == C_INPUT:
            # 只记「按了什么」，不记坐标 —— 服务端权威（D-006）
            client.keys = unpack_keys(frame.payload)
            client.last_input_at = time.perf_counter()

        elif frame.msg_type == C_HEARTBEAT:
            client_time = unpack_heartbeat(frame.payload)
            # 帧头 seq 回带请求的 seq（02 §4.2 请求-响应关联），
            # 载荷再把 client_time 原样回显 —— 双重保险，且 RTT 不依赖两端时钟同步
            payload = pack_heartbeat_ack(client_time, now_ms())
            await send_frame_async(client.writer, S_HEARTBEAT_ACK, frame.seq, payload)
            self.stats.record_out_frame(HEADER.size + len(payload))

    # ---------------------------------------------------------------- 逻辑帧

    def active_keys(self, client: Client, now: float) -> int:
        """这个 tick 该用哪套按键。

        输入有保质期（INPUT_TTL）：太久没收到新输入就等于松手，
        免得客户端失联后玩家还在「幽灵移动」。
        """
        if now - client.last_input_at > self.input_ttl:
            return 0
        return client.keys

    def update_players(self, now: float) -> None:
        """服务端权威（D-006）：按每个客户端最近上报的输入移动。"""
        for client in self.clients.values():
            keys = self.active_keys(client, now)
            client.x = apply_input(client.x, keys)

    def check_timeouts(self, now: float) -> list[Client]:
        """返回已经超时的客户端。

        **只判定，不关闭** —— 关闭由 tick_loop 做。拆开是为了可测：
        测试塞一个假的 now 进来，不用真的等 15 秒。
        timeout <= 0 表示关闭超时判定（做「纯广播」基线实验用）。
        """
        if self.timeout <= 0:
            return []
        return [c for c in self.clients.values() if now - c.last_recv_at > self.timeout]

    def build_entities(self):
        """把世界状态取成快照用的实体列表（**与编码方式无关**）。

        单独拆出来是为了 E1：这一步要造 100 敌机 + 800 子弹 = 900 个 dataclass 实例，
        而**三种编码器都要付这笔钱**。如果它和 `encoder.encode()` 混在一个计时窗口里，
        编码方式的差异会被共享开销淹没 —— 图 6-2 会变成三根一样高的柱子。
        """
        players = [
            PlayerSnapshot(
                player_id=client.player_id,
                x=max(0, min(0xFFFF, client.x)),
                y=max(0, min(0xFFFF, client.y)),
                power=1,
                color=client.color,
                flags=1,
                score=0,
            )
            for client in sorted(self.clients.values(), key=lambda c: c.player_id)
        ]
        return players, self.world.snapshot_enemies(), self.world.snapshot_bullets()

    def build_snapshot(self) -> bytes:
        players, enemies, bullets = self.build_entities()

        # 只把 `encoder.encode()` 这一步单独计时（嵌套在 ser 内，见 stats.NESTED_TIMERS）
        encode_started = time.perf_counter()
        payload = self.encoder.encode(self.tick, players, enemies, bullets)
        self.stats.record_nested("encode", time.perf_counter() - encode_started)

        self.stats.record_snapshot(len(payload))
        return payload

    async def broadcast(self, payload: bytes) -> None:
        """把**已经序列化好的**载荷发给所有客户端。

        和 `build_snapshot()` 拆开，是为了让「序列化」和「发送」各自计时 ——
        合成一个方法就没法量出通信耗时的两部分了。
        """
        if not self.clients:
            return

        size = HEADER.size + len(payload)
        for client in list(self.clients.values()):
            try:
                await send_frame_async(client.writer, S_SNAPSHOT, self.tick, payload)
            except (ConnectionError, RuntimeError):
                # 对端已经断开：移除即可，不刷屏
                self.clients.pop(client.player_id, None)
            else:
                # 每个收件人各记一次 —— 那才是真实下行带宽
                self.stats.record_out_frame(size)

    async def reap_timeouts(self) -> None:
        """每秒检查一次超时（不是每 tick —— 20 次/秒 × N 客户端全是无用功）。"""
        for client in self.check_timeouts(time.perf_counter()):
            print(
                f"[server] player {client.player_id} timed out "
                f"(no message for > {self.timeout:g}s)"
            )
            # 只关 writer：真正的清理在 handle_client 的 finally
            client.writer.close()

    def report_stats(self, stats: dict) -> None:
        if not self.print_stats_enabled:
            return
        enemies, bullets = self.world.counts()
        logic = stats["sim_ms"] + stats["collision_ms"]
        comms = stats["ser_ms"] + stats["net_ms"]
        print(
            f"[server] tick {TICK_HZ} Hz | total {stats['avg_ms']:.3f} ms "
            f"(p50 {stats['p50_ms']:.3f} p95 {stats['p95_ms']:.3f} "
            f"max {stats['max_ms']:.3f}) | "
            f"logic {logic:.3f} (sim {stats['sim_ms']:.3f} + "
            f"col {stats['collision_ms']:.3f}) | "
            f"comms {comms:.3f} (ser {stats['ser_ms']:.3f} + "
            f"net {stats['net_ms']:.3f}) | "
            f"players {len(self.clients)} | e/b {enemies}/{bullets} | "
            f"snap {stats['snapshot_bytes']} B | hits {stats['hits']} | "
            f"in {stats['packets_in']}/s"
        )

    def write_metrics(self, stats: dict) -> None:
        if self.metrics is None:
            return
        enemies, bullets = self.world.counts()
        self.metrics.write(
            client_count=len(self.clients),
            enemies=enemies,
            bullets=bullets,
            stats=stats,
        )

    async def tick_loop(self) -> None:
        """固定 20 Hz：用 deadline 累加，避免 sleep 漂移。"""
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        print(f"[server] tick loop started at {TICK_HZ} Hz")

        while True:
            next_tick += TICK_INTERVAL
            await asyncio.sleep(max(0.0, next_tick - loop.time()))

            started = time.perf_counter()
            self.tick += 1

            # ① 模拟：玩家按输入移动 + 实体移动 / 出屏剔除 / 补足数量
            self.update_players(started)
            self.world.step([(c.player_id, c.x) for c in self.clients.values()])
            sim_done = time.perf_counter()

            # ② 碰撞判定：朴素 O(子弹×敌机)，**只判定不生效**（见 entities.py）
            hits = detect_collisions(self.world.bullets, self.world.enemies)
            collision_done = time.perf_counter()

            # ③ 序列化：把几百个实体逐个 struct.pack（没人连就不做）
            payload = self.build_snapshot() if self.clients else None
            ser_done = time.perf_counter()

            # ④ 广播：逐客户端 write + drain
            if payload is not None:
                await self.broadcast(payload)
            net_done = time.perf_counter()

            self.stats.record_tick(net_done - started)
            self.stats.record_phase("sim", sim_done - started)
            self.stats.record_phase("collision", collision_done - sim_done)
            self.stats.record_phase("ser", ser_done - collision_done)
            self.stats.record_phase("net", net_done - ser_done)
            self.stats.record_hits(hits)

            if self.tick % STATS_EVERY_TICKS == 0:
                await self.reap_timeouts()
                window = self.stats.flush()
                self.report_stats(window)
                self.write_metrics(window)


def report_tick_crash(task: asyncio.Task, file=None) -> BaseException | None:
    """tick_loop 的 done 回调：死了必须**大声报**，返回异常（没死返回 None）。

    为什么单独写这个：2026-10-25 真的踩到了。`tick_loop` 里一个没导入的名字
    让它在第一个 tick 就抛 `NameError`，然后**整个协程静静死掉** ——
    服务端照常监听、照常打印 "player 1 joined"，客户端却再也收不到一帧快照。

    症状极具迷惑性：机器人报告 `clients_connected: 4` 但 `snapshots: 0`、
    `errors: 0`（连接是好的，只是没人广播）。要是没发现，
    一次 3 分钟的实验会老老实实跑完，然后留下一整份空数据。

    asyncio 只在**任务对象被回收**时才打印未取回的异常，而 `main()` 一直持有引用，
    所以进程活着的时候什么都不显示 —— 必须自己接个 done 回调。
    """
    if task.cancelled():
        return None

    exc = task.exception()
    if exc is None:
        return None

    stream = file if file is not None else sys.stdout
    print(
        f"[server] !! tick loop 已崩溃，不再广播快照："
        f"{type(exc).__name__}: {exc}",
        file=stream,
    )
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=stream)
    return exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="阶段 1 TCP 服务端（占位实体 + 指标）")
    parser.add_argument("port", nargs="?", type=int, default=PORT, help="监听端口")
    parser.add_argument(
        "--timeout",
        type=float,
        default=HEARTBEAT_TIMEOUT,
        help="心跳超时秒数；0 = 关闭超时判定（做“纯广播”基线实验用）",
    )
    parser.add_argument(
        "--enemies", type=int, default=0, help="占位敌机数量；0 = 不加（7b 行为）"
    )
    parser.add_argument("--bullets", type=int, default=0, help="占位子弹数量")
    parser.add_argument(
        "--seed", type=int, default=1, help="占位实体生成的随机种子（固定 = 可复现）"
    )
    parser.add_argument(
        "--scenario", default="", help="场景 ID，写进指标每一行；默认 adhoc"
    )
    parser.add_argument("--metrics", default=DEFAULT_METRICS_PATH, help="指标 CSV 路径")
    parser.add_argument(
        "--encoder",
        default="binary",
        choices=ENCODER_NAMES,
        help="快照编码器（E1 实验用）：binary = 标准逐条目 pack；"
        "binary_fast = 同协议的整帧单次 pack（产物逐字节相同，只差实现）（产物逐字节相同，只差实现）；"
        "json = 短键名 JSON 对照组",
    )
    parser.add_argument("--no-metrics", action="store_true", help="不写指标 CSV")
    parser.add_argument(
        "--no-stats", action="store_true", help="不打印每秒统计（照旧写 CSV）"
    )
    return parser.parse_args()


async def main(args: argparse.Namespace) -> None:
    try:
        world = World(
            enemy_target=args.enemies, bullet_target=args.bullets, seed=args.seed
        )
    except ValueError as exc:
        print(f"[server] 参数错误：{exc}")
        raise SystemExit(2) from exc

    metrics = None
    if not args.no_metrics:
        metrics = MetricsRecorder(args.metrics, scenario_id=args.scenario)
        if args.scenario:
            write_scenario(
                Path(args.metrics).with_name("server_scenario.csv"),
                args.scenario,
                enemies=args.enemies,
                bullets=args.bullets,
                tick_rate=TICK_HZ,
                seed=args.seed,
                encoder=args.encoder,
            )
        print(f"[server] metrics -> {args.metrics} (scenario={metrics.scenario_id})")

    game = GameServer(
        timeout=args.timeout,
        world=world,
        metrics=metrics,
        print_stats=not args.no_stats,
        encoder=get_encoder(args.encoder),
    )

    server = await asyncio.start_server(game.handle_client, HOST, args.port)
    timeout_text = f"{args.timeout:g}s" if args.timeout > 0 else "off"
    print(
        f"[server] listening on {HOST}:{args.port} (timeout {timeout_text}, "
        f"enemies {args.enemies}, bullets {args.bullets}, seed {args.seed}, "
        f"encoder {args.encoder})"
    )

    tick_task = asyncio.create_task(game.tick_loop())
    # 静默死掉的 tick loop 会让整场实验录到空数据，所以必须挂个回调盯着
    tick_task.add_done_callback(report_tick_crash)
    try:
        async with server:
            await server.serve_forever()
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 已经在 report_tick_crash 里报过一次，不重复刷屏
        if metrics is not None:
            metrics.close()


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\n[server] stopped")