"""阶段 1 · 第 7 步（7b）：asyncio 服务端 + 输入 + 心跳。

最小闭环（在 7a 的「连接 → 广播快照」之上补上客户端→服务端这条路）：

    客户端连上来 → 服务端分配 player_id / color
    → 客户端每 50 ms 发 C_INPUT(keys)、每 5 s 发 C_HEARTBEAT
    → 服务端按 keys 移动该玩家（**服务端权威**，坐标不由客户端给，D-006）
    → 每 50 ms 向所有客户端广播 S_SNAPSHOT
    → 15 s 收不到任何消息就判定断线

本步不做：
    - 房间、认证（第 10 步）
    - 防洪 ERR_RATE_LIMITED（等有认证和真实玩家再说）
    - S_PLAYER_LEAVE (0x86)：D-012 已确立「快照是全量真相」，
      玩家断开后不再出现在下一帧快照里，客户端自然就删掉他了，
      事件同步留给游戏内容阶段（02 §5.3）
    - 慢客户端的独立发送队列（D-020 记的账，压测阶段再还）

用法：
    .venv\\Scripts\\python.exe -X utf8 -m server.main
    .venv\\Scripts\\python.exe -X utf8 -m server.main 9527 --timeout 5
    .venv\\Scripts\\python.exe -X utf8 -m server.main --timeout 0 --no-stats
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass, field

from protocol.framing import (
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
from protocol.snapshot import PlayerSnapshot, pack_snapshot
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

# 每秒打印一行 tick 耗时（20 个 tick 一个窗口）
STATS_EVERY_TICKS = TICK_HZ


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
    ) -> None:
        self.clients: dict[int, Client] = {}
        self.next_id = 1
        self.tick = 0
        self.timeout = timeout
        self.input_ttl = input_ttl
        self.stats = stats

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
                if frame is None:#断开就结束
                    break
                # 收到任何消息都算「这个连接还活着」，不只是心跳
                client.last_recv_at = time.perf_counter()
                await self.dispatch(client, frame)
        except ProtocolError as exc:
            # magic / version / length / 载荷长度错误。
            # 此时字节流已经不可信，必须断开。
            print(f"[server] protocol error: {exc}")
        except (ConnectionError, RuntimeError):
            # 客户端正常/强制断开；这是常态，不当作服务器错误
            pass
        finally:
            # 唯一的清理点：超时判定只关 writer，实际清理只在这里做，
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
            if self.stats is not None:
                self.stats.record_input()

        elif frame.msg_type == C_HEARTBEAT:
            client_time = unpack_heartbeat(frame.payload)
            # 帧头 seq 回带请求的 seq（02 §4.2 请求-响应关联），
            # 载荷再把 client_time 原样回显 —— 双重保险，且 RTT 不依赖两端时钟同步
            payload = pack_heartbeat_ack(client_time, now_ms())
            await send_frame_async(client.writer, S_HEARTBEAT_ACK, frame.seq, payload)

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
        """服务端权威（D-006）：按每个客户端最近上报的输入移动。

        7a 的 sin 占位摆动在这里退役 —— 现在「有没有输入」是可观测的，
        E9 实验要的正是「输入 → 位置变化」这条因果链。
        """
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
        return [
            c for c in self.clients.values() if now - c.last_recv_at > self.timeout
        ]

    def build_snapshot(self) -> bytes:
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
        return pack_snapshot(self.tick, players)

    async def broadcast_snapshot(self) -> None:
        if not self.clients:
            return

        payload = self.build_snapshot()
        for client in list(self.clients.values()):
            try:
                await send_frame_async(client.writer, S_SNAPSHOT, self.tick, payload)
            except (ConnectionError, RuntimeError):
                # 对端已经断开：移除即可，不刷屏
                self.clients.pop(client.player_id, None)

    async def reap_timeouts(self) -> None:
        """每秒检查一次超时（不是每 tick —— 20 次/秒 × N 客户端全是无用功）。"""
        for client in self.check_timeouts(time.perf_counter()):
            print(
                f"[server] player {client.player_id} timed out "
                f"(no message for > {self.timeout:g}s)"
            )
            # 只关 writer：真正的清理在 handle_client 的 finally
            client.writer.close()

    def print_stats(self) -> None:
        if self.stats is None:
            return
        stats = self.stats.flush()
        print(
            f"[server] tick {TICK_HZ} Hz | avg {stats['avg_ms']:.3f} ms | "
            f"p50 {stats['p50_ms']:.3f} ms | p95 {stats['p95_ms']:.3f} ms | "
            f"max {stats['max_ms']:.3f} ms | players {len(self.clients)} | "
            f"in {stats['inputs']}/s"
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
            self.update_players(started)
            await self.broadcast_snapshot()
            if self.stats is not None:
                self.stats.record_tick(time.perf_counter() - started)

            if self.tick % STATS_EVERY_TICKS == 0:
                await self.reap_timeouts()
                self.print_stats()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="阶段 1 TCP 服务端（输入 + 心跳）")
    parser.add_argument("port", nargs="?", type=int, default=PORT, help="监听端口")
    parser.add_argument(
        "--timeout",
        type=float,
        default=HEARTBEAT_TIMEOUT,
        help="心跳超时秒数；0 = 关闭超时判定（做“纯广播”基线实验用）",
    )
    parser.add_argument(
        "--no-stats", action="store_true", help="不打印每秒 tick 耗时"
    )
    return parser.parse_args()


async def main(args: argparse.Namespace) -> None:
    stats = None if args.no_stats else TickStats()
    game = GameServer(timeout=args.timeout, stats=stats)

    server = await asyncio.start_server(game.handle_client, HOST, args.port)
    timeout_text = f"{args.timeout:g}s" if args.timeout > 0 else "off"
    print(f"[server] listening on {HOST}:{args.port} (timeout {timeout_text})")

    tick_task = asyncio.create_task(game.tick_loop())
    try:
        async with server:
            await server.serve_forever()
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\n[server] stopped")