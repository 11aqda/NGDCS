"""protocol.framing 的帧边界测试。

为什么不启动真实服务器？
    帧逻辑的输入是“recv() 每次返回多少字节”。用 FakeSocket 可以精确编排，
    稳定复现半包 / 粘包 / 截断；真实 TCP 的到达方式由内核决定，很难重复。
    真实端到端联调放在第 5~6 步；这里保留一个 socketpair 用例兜底。

运行：
    .venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_framing -v
"""

import socket
import struct
import unittest

from protocol.framing import (
    HEADER,
    MAX_PAYLOAD,
    ProtocolError,
    pack_frame,
    recv_exact,
    recv_frame,
    send_frame,
)


class FakeSocket:
    """只实现 recv(n) 的假 socket，按预设字节块返回数据。

    chunks 相当于内核接收缓冲区：recv(n) 最多返回 n 字节，
    多出来的部分留到下一次，与 TCP 字节流的行为一致。
    """

    def __init__(self, chunks):
        self.chunks = [bytes(chunk) for chunk in chunks]
        self.requests = []

    def recv(self, n):
        self.requests.append(n)
        if n <= 0:
            return b""
        while self.chunks:
            chunk = self.chunks.pop(0)
            if not chunk:
                continue
            if len(chunk) > n:
                self.chunks.insert(0, chunk[n:])
                return chunk[:n]
            return chunk
        return b""  # 缓冲区空 = 对端关闭


class FramingTest(unittest.TestCase):
    def test_pack_frame_layout(self):
        """帧头就是 4 字节大端长度，后面紧跟载荷。"""
        frame = pack_frame(b"abc")
        self.assertEqual(frame, b"\x00\x00\x00\x03abc")
        self.assertEqual(HEADER.unpack(frame[: HEADER.size]), (3,))

    def test_round_trip_binary_safe(self):
        """载荷里放 \\n 和 \\x00，证明长度前缀不依赖分隔符。"""
        payload = b"line1\nline2\x00\xff"
        sock = FakeSocket([pack_frame(payload)])
        self.assertEqual(recv_frame(sock), payload)

    def test_empty_payload(self):
        """length=0 是合法帧；不应该再去读载荷。"""
        sock = FakeSocket([pack_frame(b"")])
        self.assertEqual(recv_frame(sock), b"")
        self.assertEqual(sock.requests, [HEADER.size])

    def test_sticky_two_frames(self):
        """两条帧粘在一起：第一次 recv_frame 只消费第一条。"""
        sock = FakeSocket([pack_frame(b"one") + pack_frame(b"two")])
        self.assertEqual(recv_frame(sock), b"one")
        self.assertEqual(recv_frame(sock), b"two")
        self.assertIsNone(recv_frame(sock))

    def test_five_frames_in_one_chunk(self):
        """一次收到 N 个完整报文，循环读取。"""
        payloads = [f"msg-{i}".encode() for i in range(5)]
        sock = FakeSocket([b"".join(pack_frame(p) for p in payloads)])
        for expected in payloads:
            self.assertEqual(recv_frame(sock), expected)

    def test_split_at_every_byte(self):
        """在帧的每一个字节位置切开，都必须能还原。"""
        payload = b"0123456789"
        frame = pack_frame(payload)
        for split in range(len(frame) + 1):
            with self.subTest(split=split):
                sock = FakeSocket([frame[:split], frame[split:]])
                self.assertEqual(recv_frame(sock), payload)

    def test_one_byte_at_a_time(self):
        """最极端的半包：每次 recv 只返回 1 字节。"""
        payload = b"hello"
        frame = pack_frame(payload)
        sock = FakeSocket([bytes([byte]) for byte in frame])
        self.assertEqual(recv_frame(sock), payload)

    def test_max_payload_accepted(self):
        """长度恰好等于上限，必须接受。"""
        payload = b"x" * MAX_PAYLOAD
        sock = FakeSocket([pack_frame(payload)])
        self.assertEqual(recv_frame(sock), payload)

    def test_oversized_length_rejected_before_payload(self):
        """声明长度超限时，读完 4 B 帧头就报错，不能按恶意长度分配内存。"""
        sock = FakeSocket([struct.pack("!I", MAX_PAYLOAD + 1)])
        with self.assertRaises(ProtocolError):
            recv_frame(sock)
        self.assertEqual(sock.requests, [HEADER.size])

    def test_pack_too_large_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_frame(b"x" * (MAX_PAYLOAD + 1))

    def test_clean_eof_returns_none(self):
        """对端在帧边界正常关闭：返回 None，不是异常。"""
        self.assertIsNone(recv_frame(FakeSocket([])))

    def test_truncated_header_raises(self):
        """帧头只收到一半就断开。"""
        with self.assertRaises(ProtocolError):
            recv_frame(FakeSocket([b"\x00\x00"]))

    def test_truncated_payload_raises(self):
        """帧头说 10 B，实际只给 3 B 就断开。"""
        sock = FakeSocket([struct.pack("!I", 10) + b"abc"])
        with self.assertRaises(ProtocolError):
            recv_frame(sock)

    def test_zero_length_read_needs_no_socket(self):
        """recv_exact(n=0) 直接返回 b''，不应触发 recv。"""
        sock = FakeSocket([])
        self.assertEqual(recv_exact(sock, 0), b"")
        self.assertEqual(sock.requests, [])

    def test_send_frame_over_real_socketpair(self):
        """用真实 socketpair 验证 send_frame 与 recv_frame 能对接。"""
        left, right = socket.socketpair()
        try:
            send_frame(left, b"real-socket")
            self.assertEqual(recv_frame(right), b"real-socket")
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
