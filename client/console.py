"""控制台快照客户端（调试用）。

不开 pygame，只打印快照；适合在终端里验证服务端和协议。
正式的图形客户端是 client/main.py。

用法：
    .venv\\Scripts\\python.exe -X utf8 -m client.console Alice
    .venv\\Scripts\\python.exe -X utf8 -m client.console Bob 10
"""

import asyncio
import sys

from protocol.framing import ProtocolError, recv_frame_async
from protocol.messages import S_SNAPSHOT, S_WELCOME, WELCOME
from protocol.snapshot import unpack_snapshot

HOST = "127.0.0.1"
PORT = 9527
PRINT_EVERY = 5


async def main(label: str, limit: int) -> None:
    reader, writer = await asyncio.open_connection(HOST, PORT)
    print(f"[{label}] connected to {HOST}:{PORT}")

    try:
        welcome = await recv_frame_async(reader)
        if welcome is None or welcome.msg_type != S_WELCOME:
            print(f"[{label}] expected S_WELCOME, got {welcome}")
            return
        if len(welcome.payload) != WELCOME.size:
            print(f"[{label}] bad welcome payload: {welcome.payload!r}")
            return

        player_id, color = WELCOME.unpack(welcome.payload)
        print(f"[{label}] joined as player {player_id}, color {color}")

        shown = 0
        while True:
            frame = await recv_frame_async(reader)
            if frame is None:
                print(f"[{label}] server closed the connection")
                break
            if frame.msg_type != S_SNAPSHOT:
                continue

            snapshot = unpack_snapshot(frame.payload)
            shown += 1

            should_print = shown % PRINT_EVERY == 0 or (limit and shown >= limit)
            if should_print:
                players = " | ".join(
                    f"P{p.player_id}({p.x},{p.y})" for p in snapshot.players
                )
                print(f"[{label}] tick={snapshot.tick} {players}")

            if limit and shown >= limit:
                break
    except (ProtocolError, ConnectionError) as exc:
        print(f"[{label}] error: {exc}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "client"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    try:
        asyncio.run(main(label, limit))
    except KeyboardInterrupt:
        print()
