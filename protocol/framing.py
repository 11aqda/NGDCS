"""长度前缀帧：4 字节大端长度 + 载荷。

为什么用长度前缀，而不是分隔符？
    TCP 是字节流。要把“一条消息”从流里切出来，最可靠的办法是先知道它有多长。
    分隔符（比如 \\n）遇到二进制载荷必须转义，既增加体积又容易出错；
    长度前缀对任意字节都安全。详见 docs/02-协议设计.md §3。

本步只做 4 字节长度；第 4 步会扩展成 12 字节帧头
（magic + version + type + seq + length），但“先读长度、再读载荷”的核心不变。

    +--------+---------------------------+
    | length |          payload          |
    | uint32 |       length bytes        |
    +--------+---------------------------+
      length 只算载荷，不含自己这 4 字节

注意：
    recv_exact() 假设 socket 是**阻塞**的。第 6 步客户端改成非阻塞后，
    会换成“缓冲区 + 状态机”的 FrameParser；帧格式本身不变。
"""

from __future__ import annotations

import socket
import struct

# ! = 网络字节序（大端）；I = 4 字节无符号整数
HEADER = struct.Struct("!I")

# 单个载荷上限：防止对端报一个 4 GB 的长度，把内存吃光
MAX_PAYLOAD = 64 * 1024


class ProtocolError(Exception):
    """帧格式错误、连接提前关闭、载荷超限。"""


def pack_frame(payload: bytes) -> bytes:
    """把一段载荷封装成“4 字节长度 + 载荷”。"""
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"载荷超限：{len(payload)} B > {MAX_PAYLOAD} B")
    return HEADER.pack(len(payload)) + payload


def send_frame(sock: socket.socket, payload: bytes) -> None:
    """封装并发送一帧。sendall 负责把数据全部写进内核缓冲区。"""
    sock.sendall(pack_frame(payload))


def recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """从 socket 精确读满 n 字节。

    返回：
        bytes —— 读满 n 字节（n=0 时返回 b""）
        None  —— 还没读到任何字节，对端就正常关闭了（干净的 EOF）

    如果读了一半对端才关闭，说明帧被截断，抛 ProtocolError。
    """
    if n == 0:
        return b""

    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)  # 阻塞；最多读 remaining 字节
        if not chunk:  # 对端关闭
            if remaining == n:
                # 一个字节都没读到，说明正好在帧边界上，属于正常断开
                return None
            raise ProtocolError(f"连接提前关闭：还差 {remaining} B 才读完")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(sock: socket.socket) -> bytes | None:
    """读一个完整帧，返回载荷；对端在帧边界关闭时返回 None。"""
    header = recv_exact(sock, HEADER.size)
    if header is None:
        return None

    (length,) = HEADER.unpack(header)
    if length > MAX_PAYLOAD:
        raise ProtocolError(f"载荷超限：{length} B > {MAX_PAYLOAD} B")

    payload = recv_exact(sock, length)
    if payload is None:
        raise ProtocolError("帧头之后连接关闭，帧不完整")
    return payload
