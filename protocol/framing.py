"""12 字节帧头 + 载荷。

帧格式（所有多字节字段为大端 / 网络字节序）：

    偏移  长度  字段      类型      说明
    0     2     magic     uint16    固定 0x4A59
    2     1     version   uint8     当前 1
    3     1     type      uint8     消息类型（见 protocol/messages.py）
    4     4     seq       uint32    发送方递增序列号
    8     4     length    uint32    载荷字节数（不含帧头）
    12    N     payload   bytes     载荷

    +--------+---------+------+--------+--------+------------------+
    | magic  | version | type | seq    | length | payload          |
    | uint16 | uint8   | uint8| uint32 | uint32 | length bytes     |
    +--------+---------+------+--------+--------+------------------+
    帧头固定 12 B

为什么有 magic / version / type / seq？
    magic   —— 快速判断“这是不是我们的协议”，也能发现字节流错位
    version —— 协议升级时拒绝不兼容的对端，而不是解析出乱码
    type    —— 同一条 TCP 连接上跑多种消息，接收方要知道交给谁处理
    seq     —— 请求-响应关联（算 RTT）、丢包检测、防重放
    length  —— 划出消息边界（第 2 步的核心，位置从 0 变成 8）

同步 / 异步 / 非阻塞三套 API：
    - recv_frame(sock) / send_frame(sock, ...)       阻塞 socket 用
    - recv_frame_async(reader) / send_frame_async(...)  asyncio 用
    - FrameParser.feed() / next_frame()              非阻塞 socket（pygame 主循环）用
    三者共用 parse_header()，所以校验规则只写一遍。
"""

from __future__ import annotations

import asyncio
import socket
import struct
from dataclasses import dataclass

MAGIC = 0x4A59
VERSION = 1

# ! = 网络字节序（大端）；HBBII = 2 + 1 + 1 + 4 + 4 = 12 字节
HEADER = struct.Struct("!HBBII")

# 单个载荷上限：防止对端报一个 4 GB 的长度，把内存吃光
MAX_PAYLOAD = 64 * 1024


class ProtocolError(Exception):
    """帧格式错误、连接提前关闭、载荷超限。"""


@dataclass(frozen=True, slots=True)
class Frame:
    """一帧的语义字段（magic / version 已校验，不再返回）。"""

    msg_type: int
    seq: int
    payload: bytes


def parse_header(header: bytes) -> tuple[int, int, int]:
    """校验 12 B 帧头，返回 (msg_type, seq, length)。

    同步和异步接收共用这一份校验逻辑。
    """
    if len(header) != HEADER.size:
        raise ProtocolError(f"帧头长度错误：{len(header)} != {HEADER.size}")

    magic, version, msg_type, seq, length = HEADER.unpack(header)
    if magic != MAGIC:
        raise ProtocolError(f"magic 不匹配：0x{magic:04X} != 0x{MAGIC:04X}")
    if version != VERSION:
        raise ProtocolError(f"version 不支持：{version} != {VERSION}")
    if length > MAX_PAYLOAD:
        raise ProtocolError(f"载荷超限：{length} B > {MAX_PAYLOAD} B")
    return msg_type, seq, length


def pack_frame(msg_type: int, seq: int, payload: bytes) -> bytes:
    """把 type / seq / payload 封装成“12 B 帧头 + 载荷”。"""
    if not 0 <= msg_type <= 0xFF:
        raise ProtocolError(f"type 超出 uint8：{msg_type}")
    if not 0 <= seq <= 0xFFFFFFFF:
        raise ProtocolError(f"seq 超出 uint32：{seq}")
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"载荷超限：{len(payload)} B > {MAX_PAYLOAD} B")
    return HEADER.pack(MAGIC, VERSION, msg_type, seq, len(payload)) + payload


def send_frame(sock: socket.socket, msg_type: int, seq: int, payload: bytes) -> None:
    """封装并发送一帧。sendall 负责把数据全部写进内核缓冲区。"""
    sock.sendall(pack_frame(msg_type, seq, payload))


async def send_frame_async(
    writer: asyncio.StreamWriter, msg_type: int, seq: int, payload: bytes
) -> None:
    """asyncio 版发送：write + drain，确保数据交给内核。"""
    writer.write(pack_frame(msg_type, seq, payload))
    await writer.drain()


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


def recv_frame(sock: socket.socket) -> Frame | None:
    """读一个完整帧；对端在帧边界关闭时返回 None。"""
    header = recv_exact(sock, HEADER.size)
    if header is None:
        return None

    msg_type, seq, length = parse_header(header)
    payload = recv_exact(sock, length)
    if payload is None:
        raise ProtocolError("帧头之后连接关闭，帧不完整")
    return Frame(msg_type=msg_type, seq=seq, payload=payload)


async def recv_frame_async(reader: asyncio.StreamReader) -> Frame | None:
    """asyncio 版接收：先读满 12 B 帧头，再按 length 读满载荷。"""
    try:
        header = await reader.readexactly(HEADER.size)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None  # 帧边界上的正常关闭
        raise ProtocolError(
            f"连接提前关闭：帧头只收到 {len(exc.partial)} B"
        ) from exc

    msg_type, seq, length = parse_header(header)

    try:
        payload = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        missing = exc.expected - len(exc.partial)
        raise ProtocolError(f"连接提前关闭：载荷还差 {missing} B") from exc
    return Frame(msg_type=msg_type, seq=seq, payload=payload)


class FrameParser:
    """非阻塞接收用的帧解析器：喂任意分片，吐出完整 Frame。

    用法：
        parser = FrameParser()
        parser.feed(data)                 # 每次 recv 到多少就喂多少
        while True:
            frame = parser.next_frame()
            if frame is None:             # 还没有完整帧
                break
            handle(frame)

    注意：解析失败（magic / version / length 错）会抛 ProtocolError，
    调用方应关闭连接，不要继续喂数据。
    """

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> None:
        """把一次 recv 到的字节追加到缓冲区。"""
        self.buffer.extend(data)

    def next_frame(self) -> Frame | None:
        """取出一个完整帧；数据不够时返回 None，不阻塞。"""
        if len(self.buffer) < HEADER.size:
            return None

        header = bytes(self.buffer[: HEADER.size])
        msg_type, seq, length = parse_header(header)

        total = HEADER.size + length
        if len(self.buffer) < total:
            return None  # 半包：等下一次 feed

        payload = bytes(self.buffer[HEADER.size : total])
        del self.buffer[:total]
        return Frame(msg_type=msg_type, seq=seq, payload=payload)
