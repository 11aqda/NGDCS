"""隔离测试：TCP 代理的单次往返延迟到底是多少。

用最简单的回声服务器，排除游戏协议/机器人/服务端的干扰 ——
如果"发一个包、收回同一个包"的耗时都不对，那问题一定在代理本身。
"""

import asyncio
import sys
import time

PROXY_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9710
ROUNDS = 10


async def echo_handler(reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> None:
    while True:
        data = await reader.read(4096)
        if not data:
            break
        writer.write(data)
        await writer.drain()
    writer.close()


async def main() -> None:
    server = await asyncio.start_server(echo_handler, "127.0.0.1", 9711)
    async with server:
        await asyncio.sleep(0.2)
        reader, writer = await asyncio.open_connection("127.0.0.1", PROXY_PORT)
        # 预热一次
        writer.write(b"warm")
        await writer.drain()
        await reader.read(64)

        times = []
        for _ in range(ROUNDS):
            started = time.perf_counter()
            writer.write(b"ping-pong-payload-16")
            await writer.drain()
            data = await reader.read(64)
            times.append((time.perf_counter() - started) * 1000)
            assert data, "回声没回来"
            await asyncio.sleep(0.05)

        avg = sum(times) / len(times)
        print(f"  单次往返: 均值 {avg:.1f} ms  最小 {min(times):.1f}  "
              f"最大 {max(times):.1f}")
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


asyncio.run(main())