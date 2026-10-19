"""阶段 1 · 回声客户端：从标准输入读一行，发给服务器，再把回声打印出来。

用法：
    .venv\\Scripts\\python.exe client\\echo_client.py
    .venv\\Scripts\\python.exe client\\echo_client.py 127.0.0.1 9000
    .venv\\Scripts\\python.exe client\\echo_client.py 10.140.71.127 9000
"""

import socket
import sys
import time

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
            sock.sendall(payload)  # 不保证一次发完，sendall 负责发完
            echoed = sock.recv(1024)  # ⚠️ 只调用一次：不保证把 payload 收全
            rtt_ms = (time.perf_counter() - t0) * 1000

            text = echoed.decode("utf-8", errors="replace")
            shown = text if len(text) <= 60 else text[:60] + "…"
            print(f"[client] echo {len(echoed)} B: {shown!r}  RTT {rtt_ms:.3f} ms")
            if len(echoed) != len(payload):
                print(f"[client] ⚠️ 只收到 {len(echoed)}/{len(payload)} B —— recv 不保证一次收全")


if __name__ == "__main__":
    main()
