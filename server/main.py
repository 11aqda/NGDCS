"""阶段 1 · 第 5 步：asyncio 服务端 + 20 Hz tick + 广播。

最小闭环：
    客户端连上来 → 服务端分配 player_id / color
    → 每 50 ms 更新一次占位坐标
    → 向所有客户端广播 S_SNAPSHOT。

本步不做：
    - 房间（后面）
    - 客户端输入（第 6 步）
    - 敌机 / 子弹 / 道具（后面）
    - 慢客户端的独立发送队列（现在客户端少，直接 drain；后面再优化）

用法：
    .venv\\Scripts\\python.exe -X utf8 -m server.main
    .venv\\Scripts\\python.exe -X utf8 -m server.main 9527
"""

import asyncio
import math
import sys
from dataclasses import dataclass

from protocol.framing import ProtocolError, recv_frame_async, send_frame_async
from protocol.messages import S_SNAPSHOT, S_WELCOME, WELCOME
from protocol.snapshot import PlayerSnapshot, pack_snapshot

HOST = "0.0.0.0"
PORT = 9527
TICK_HZ = 20
TICK_INTERVAL = 1 / TICK_HZ


@dataclass
class Client:
    player_id: int
    color: int
    x: int
    y: int
    writer: asyncio.StreamWriter


class GameServer:
    def __init__(self) -> None:
        self.clients: dict[int, Client] = {}
        self.next_id = 1
        self.tick = 0

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
            x=360,
            y=200 + ((player_id - 1) % 4) * 160,
            writer=writer,
        )
        self.clients[player_id] = client
        print(f"[server] player {player_id} joined from {peer} (color={color})")

        try:
            # 先告诉客户端“你是谁”，再开始收快照
            await send_frame_async(writer, S_WELCOME, 0, WELCOME.pack(player_id, color))

            # 阶段 5 不处理客户端消息；这里只负责检测断开。
            # 第 6 步会把 C_INPUT 接进来。
            while True:
                frame = await recv_frame_async(reader)
                if frame is None:
                    break
        except ProtocolError as exc:
            # magic / version / length 错误或帧被截断。
            # 此时字节流已经不可信，必须断开。
            print(f"[server] protocol error: {exc}")
        except (ConnectionError, RuntimeError):
            # 客户端正常/强制断开；这是常态，不当作服务器错误
            pass
        finally:
            self.clients.pop(player_id, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass
            print(f"[server] player {player_id} left")

    def update_players(self) -> None:
        """占位运动：每个人在自己的 y 附近左右摆动。"""
        for client in self.clients.values():
            phase = self.tick * 0.05 + client.player_id
            client.x = 360 + int(120 * math.sin(phase))

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

    async def tick_loop(self) -> None:
        """固定 20 Hz：用 deadline 累加，避免 sleep 漂移。"""
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        print(f"[server] tick loop started at {TICK_HZ} Hz")

        while True:
            next_tick += TICK_INTERVAL
            await asyncio.sleep(max(0.0, next_tick - loop.time()))

            self.tick += 1
            self.update_players()
            await self.broadcast_snapshot()


async def main(port: int) -> None:
    game = GameServer()
    server = await asyncio.start_server(game.handle_client, HOST, port)
    print(f"[server] listening on {HOST}:{port}")

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
        asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else PORT))
    except KeyboardInterrupt:
        print("\n[server] stopped")
