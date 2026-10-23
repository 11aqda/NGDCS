"""控制台快照客户端（调试用）。

不开 pygame，只打印快照；适合在终端里验证服务端和协议。
正式的图形客户端是 client/main.py。

7b 起服务端有 **15 秒心跳超时**（02 §7）：任何客户端超过 15 s 不发消息
就会被判定断线并清理。所以这个调试客户端也必须发心跳，否则跑十几秒就掉。

用法：
    .venv\\Scripts\\python.exe -X utf8 -m client.console Alice
    .venv\\Scripts\\python.exe -X utf8 -m client.console Bob 10
"""

import asyncio
import contextlib
import sys

from protocol.framing import ProtocolError, recv_frame_async, send_frame_async
from protocol.messages import (
    C_HEARTBEAT,
    S_HEARTBEAT_ACK,
    S_SNAPSHOT,
    S_WELCOME,
    WELCOME,
    now_ms,
    pack_heartbeat,
    rtt_ms,
    unpack_heartbeat_ack,
)
from protocol.snapshot import unpack_snapshot

HOST = "127.0.0.1"
PORT = 9527
PRINT_EVERY = 5
HEARTBEAT_INTERVAL = 5.0


async def heartbeat_loop(writer: asyncio.StreamWriter) -> None:
    """每 5 秒发一次心跳，让服务端知道我们还活着。"""
    seq = 1
    while True:
        await send_frame_async(
            writer, C_HEARTBEAT, seq, pack_heartbeat(now_ms())
        )
        seq += 1
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def main(label: str, limit: int) -> None:
    reader, writer = await asyncio.open_connection(HOST, PORT)
    print(f"[{label}] connected to {HOST}:{PORT}")

    heartbeat = asyncio.create_task(heartbeat_loop(writer))

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
        rtt_ms_value = 0.0
        while True:
            frame = await recv_frame_async(reader)
            if frame is None:
                print(f"[{label}] server closed the connection")
                break
            if frame.msg_type == S_HEARTBEAT_ACK:
                client_time, _server_time = unpack_heartbeat_ack(frame.payload)
                rtt_ms_value = rtt_ms(client_time)
                continue
            if frame.msg_type != S_SNAPSHOT:
                continue

            snapshot = unpack_snapshot(frame.payload)
            shown += 1

            should_print = shown % PRINT_EVERY == 0 or (limit and shown >= limit)
            if should_print:
                players = " | ".join(
                    f"P{p.player_id}({p.x},{p.y})" for p in snapshot.players
                )
                print(
                    f"[{label}] tick={snapshot.tick} rtt={rtt_ms_value}ms {players}"
                )
                rtt_ms_value = 0.0  # 只打印最近一次心跳的 RTT

            if limit and shown >= limit:
                break
    except (ProtocolError, ConnectionError) as exc:
        print(f"[{label}] error: {exc}")
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
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