"""阶段 1 · 第 2 步：带长度前缀的回声客户端。

和第 1 步的区别：
    - 发送时先写 4 字节长度，再写载荷（send_frame）
    - 接收时先读长度，再读满载荷（recv_frame）
    所以一次 recv 只拿到半条消息也不会出错，客户端不会再“少收几个字节”。

用法：
    .venv\\Scripts\\python.exe -m client.echo_client
    .venv\\Scripts\\python.exe -m client.echo_client 127.0.0.1 9000
    .venv\\Scripts\\python.exe -m client.echo_client 10.140.71.127 9000
"""

import socket
import sys
import time

from protocol.framing import ProtocolError, recv_frame, send_frame

HOST = "127.0.0.1"
PORT = 9000


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    # create_connection：DNS/连接/超时一次搞定，超时避免连不上时永久卡住
    with socket.create_connection((host, port), timeout=5) as sock:
        print(f"[client] connected to {host}:{port}（输入一行回车发送，空行退出）")
        while True:
            try:
                line = input("> ")
            except EOFError:  # 管道输入结束时也会走到这里
                break
            line = line.strip()
            if not line:
                break

            payload = line.encode("utf-8")  # 网络上只能传字节，不能传 str
            t0 = time.perf_counter()
            try:
                send_frame(sock, payload)
                echoed = recv_frame(sock)  # 阻塞，直到读到一个完整帧
            except (ProtocolError, OSError) as exc:
                print(f"[client] error: {exc}")
                break
            rtt_ms = (time.perf_counter() - t0) * 1000

            if echoed is None:
                print("[client] server closed the connection")
                break

            text = echoed.decode("utf-8", errors="replace")
            shown = text if len(text) <= 60 else text[:60] + "…"
            print(f"[client] echo {len(echoed)} B: {shown!r}  RTT {rtt_ms:.3f} ms")


if __name__ == "__main__":
    main()
