"""protocol.framing 的 12 字节帧头与边界测试。

为什么不启动真实服务器？
    帧逻辑的输入是“recv() 每次返回多少字节”。用 FakeSocket 可以精确编排，
    稳定复现半包 / 粘包 / 截断；真实 TCP 的到达方式由内核决定，很难重复。
    真实端到端联调放在第 5~6 步；这里保留一个 socketpair 用例兜底。

运行：
    .venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_framing -v
"""

import socket
import unittest

from protocol.framing import (
    HEADER,
    MAGIC,
    MAX_PAYLOAD,
    VERSION,
    Frame,
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
    def test_header_layout(self):
        """12 B 帧头：magic(2) + version(1) + type(1) + seq(4) + length(4)。"""
        raw = pack_frame(0x06, 1, b"abc")
        self.assertEqual(HEADER.size, 12)
        self.assertEqual(
            raw[:12],
            b"\x4a\x59\x01\x06\x00\x00\x00\x01\x00\x00\x00\x03",
        )
        self.assertEqual(HEADER.unpack(raw[:12]), (MAGIC, VERSION, 0x06, 1, 3))
        self.assertEqual(raw[12:], b"abc")

    def test_round_trip_fields(self):
        """type / seq / payload 原样往返。"""
        payload = b"line1\nline2\x00\xff"
        sock = FakeSocket([pack_frame(0x84, 42, payload)])
        frame = recv_frame(sock)
        self.assertIsInstance(frame, Frame)
        self.assertEqual((frame.msg_type, frame.seq, frame.payload), (0x84, 42, payload))

    def test_unknown_type_is_not_a_framing_error(self):
        """帧层不判断 type 的业务含义，未知 type 也要能读出来。"""
        frame = recv_frame(FakeSocket([pack_frame(0xAA, 7, b"x")]))
        self.assertEqual(frame.msg_type, 0xAA)

    def test_empty_payload(self):
        """length=0 是合法帧；不应该再去读载荷。"""
        sock = FakeSocket([pack_frame(0x06, 7, b"")])
        frame = recv_frame(sock)
        self.assertEqual(frame.payload, b"")
        self.assertEqual(sock.requests, [HEADER.size])

    def test_sticky_two_frames(self):
        """两条帧粘在一起：第一次 recv_frame 只消费第一条。"""
        sock = FakeSocket([pack_frame(0x7F, 1, b"one") + pack_frame(0x7F, 2, b"two")])
        first = recv_frame(sock)
        second = recv_frame(sock)
        self.assertEqual((first.seq, first.payload), (1, b"one"))
        self.assertEqual((second.seq, second.payload), (2, b"two"))
        self.assertIsNone(recv_frame(sock))

    def test_five_frames_in_one_chunk(self):
        """一次收到 N 个完整报文，循环读取。"""
        expected = [(0x10 + i, i + 1, f"msg-{i}".encode()) for i in range(5)]
        sock = FakeSocket([b"".join(pack_frame(*item) for item in expected)])
        for msg_type, seq, payload in expected:
            frame = recv_frame(sock)
            self.assertEqual((frame.msg_type, frame.seq, frame.payload), (msg_type, seq, payload))

    def test_split_at_every_byte(self):
        """在帧的每一个字节位置切开，都必须能还原。"""
        raw = pack_frame(0x06, 1, b"0123456789")
        for split in range(len(raw) + 1):
            with self.subTest(split=split):
                frame = recv_frame(FakeSocket([raw[:split], raw[split:]]))
                self.assertEqual(frame.payload, b"0123456789")

    def test_one_byte_at_a_time(self):
        """最极端的半包：每次 recv 只返回 1 字节。"""
        raw = pack_frame(0x06, 1, b"hello")
        sock = FakeSocket([bytes([byte]) for byte in raw])
        self.assertEqual(recv_frame(sock).payload, b"hello")

    def test_max_payload_accepted(self):
        """长度恰好等于上限，必须接受。"""
        payload = b"x" * MAX_PAYLOAD
        frame = recv_frame(FakeSocket([pack_frame(0x84, 1, payload)]))
        self.assertEqual(frame.payload, payload)

    def test_oversized_length_rejected_before_payload(self):
        """声明长度超限时，读完 12 B 帧头就报错，不能按恶意长度分配内存。"""
        header = HEADER.pack(MAGIC, VERSION, 0x06, 1, MAX_PAYLOAD + 1)
        sock = FakeSocket([header])
        with self.assertRaises(ProtocolError):
            recv_frame(sock)
        self.assertEqual(sock.requests, [HEADER.size])

    def test_pack_too_large_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_frame(0x06, 1, b"x" * (MAX_PAYLOAD + 1))

    def test_magic_mismatch_rejected(self):
        """magic 不对：可能连错了端口，或字节流错位。"""
        header = HEADER.pack(MAGIC ^ 0xFFFF, VERSION, 0x06, 1, 0)
        with self.assertRaises(ProtocolError):
            recv_frame(FakeSocket([header]))

    def test_version_mismatch_rejected(self):
        """version 不对：拒绝不兼容的对端，而不是解析出乱码。"""
        header = HEADER.pack(MAGIC, VERSION + 1, 0x06, 1, 0)
        with self.assertRaises(ProtocolError):
            recv_frame(FakeSocket([header]))

    def test_type_and_seq_range_checked(self):
        for bad_type in (-1, 256):
            with self.subTest(bad_type=bad_type), self.assertRaises(ProtocolError):
                pack_frame(bad_type, 1, b"")
        for bad_seq in (-1, 2**32):
            with self.subTest(bad_seq=bad_seq), self.assertRaises(ProtocolError):
                pack_frame(0x06, bad_seq, b"")

    def test_clean_eof_returns_none(self):
        """对端在帧边界正常关闭：返回 None，不是异常。"""
        self.assertIsNone(recv_frame(FakeSocket([])))

    def test_truncated_header_raises(self):
        """帧头只收到 11 B 就断开。"""
        with self.assertRaises(ProtocolError):
            recv_frame(FakeSocket([b"\x00" * (HEADER.size - 1)]))

    def test_truncated_payload_raises(self):
        """帧头说 10 B，实际只给 3 B 就断开。"""
        raw = HEADER.pack(MAGIC, VERSION, 0x06, 1, 10) + b"abc"
        with self.assertRaises(ProtocolError):
            recv_frame(FakeSocket([raw]))

    def test_zero_length_read_needs_no_socket(self):
        """recv_exact(n=0) 直接返回 b''，不应触发 recv。"""
        sock = FakeSocket([])
        self.assertEqual(recv_exact(sock, 0), b"")
        self.assertEqual(sock.requests, [])

    def test_send_frame_over_real_socketpair(self):
        """用真实 socketpair 验证 send_frame 与 recv_frame 能对接。"""
        left, right = socket.socketpair()
        try:
            send_frame(left, 0x06, 99, b"real-socket")
            frame = recv_frame(right)
            self.assertEqual((frame.msg_type, frame.seq, frame.payload), (0x06, 99, b"real-socket"))
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
