"""阶段 1 · 第 2 步：带长度前缀的回声服务器。

相比第 1 步，只改了收发方式：
    所有消息都走 protocol/framing.py 的“4 字节长度 + 载荷”。
    无论一次 recv 收到的是半包、整包，还是两个粘在一起的包，
    recv_frame() 都会还原成一条完整消息。

仍然保留的限制（后面几步解决）：
    - 一次只服务一个客户端（第 5 步换成 asyncio）
    - 帧头里只有长度，没有 type / seq（第 4 步扩展成 12 字节）

用法：
    .venv\\Scripts\\python.exe -m server.echo_server
    .venv\\Scripts\\python.exe -m server.echo_server 9000
"""

import socket
import sys

from protocol.framing import ProtocolError, recv_frame, send_frame

HOST = "0.0.0.0"  # 监听本机所有网卡；客户端可连 127.0.0.1 或本机局域网 IP
PORT = 9000


def serve(port: int) -> None:
    # AF_INET = IPv4，SOCK_STREAM = TCP（可靠、有序、字节流）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, port))
        listener.listen(1)  # backlog=1：只排一个等待连接，强调“单客户端”
        print(f"[server] listening on {HOST}:{port}")

        while True:  # 外层：一个客户端断开后，继续等下一个
            conn, addr = listener.accept()  # 阻塞，直到有人连进来
            print(f"[server] connected: {addr}")
            with conn:  # 离开 with 时自动 close，避免文件描述符泄漏
                try:
                    while True:
                        payload = recv_frame(conn)  # 阻塞，直到读到一个完整帧
                        if payload is None:  # 对端在帧边界正常关闭
                            break
                        print(f"[server] recv frame {len(payload)} B: {payload!r}")
                        send_frame(conn, payload)
                except ProtocolError as exc:
                    # 长度超限或帧被截断。此时字节流已经不可信，必须断开。
                    print(f"[server] protocol error: {exc}")
                except ConnectionError as exc:
                    # 客户端被强杀、或先关闭后服务端还在写
                    print(f"[server] connection error: {exc!r}")
            print(f"[server] disconnected: {addr}")


if __name__ == "__main__":
    try:
        serve(int(sys.argv[1]) if len(sys.argv) > 1 else PORT)
    except KeyboardInterrupt:
        print("\n[server] stopped")
