"""阶段 1 · 回声服务器：客户端发什么，就原样回什么。

这是整个通信系统的起点，只演示 socket 的三件事：
  1. bind / listen / accept —— 服务器怎么“等连接”
  2. recv / sendall        —— 连接建立后怎么收发
  3. 为什么 recv 拿到的是“字节”，而不是“一条消息”

限制（有意保留，后面几步解决）：
  - 一次只服务一个客户端：阻塞在 accept 和 recv 上
  - 没有消息边界：第 2 步加长度前缀
  - 没有并发：第 5 步换成 asyncio

用法：
    .venv\\Scripts\\python.exe server\\echo_server.py
    .venv\\Scripts\\python.exe server\\echo_server.py 9000
"""

import socket
import sys

HOST = "0.0.0.0"  # 监听本机所有网卡；客户端可连 127.0.0.1 或本机局域网 IP
PORT = 9000
BUFSIZE = 1024  # 一次 recv 最多读多少字节，不是“一条消息的长度”


def serve(port: int) -> None:
    # AF_INET = IPv4，SOCK_STREAM = TCP（可靠、有序、字节流）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # 允许端口在进程退出后立刻复用，免得调试时反复等 TIME_WAIT
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
                        data = conn.recv(BUFSIZE)  # 阻塞，直到有数据或对端关闭
                        if not data:  # 对端正常关闭时 recv 返回 b""
                            break
                        print(f"[server] recv {len(data)} B: {data!r}")
                        conn.sendall(data)  # sendall：内部循环，保证全部发出
                except ConnectionError as exc:
                    # 客户端被强杀、或先关闭后服务端还在写，都会走到这里；
                    # 单个连接出错不应该让整个服务器退出
                    print(f"[server] connection error: {exc!r}")
            print(f"[server] disconnected: {addr}")


if __name__ == "__main__":
    try:
        serve(int(sys.argv[1]) if len(sys.argv) > 1 else PORT)
    except KeyboardInterrupt:
        print("\n[server] stopped")
