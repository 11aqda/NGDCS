"""非阻塞 FrameParser 的边界测试。"""

import unittest

from protocol.framing import (
    HEADER,
    MAGIC,
    MAX_PAYLOAD,
    VERSION,
    FrameParser,
    ProtocolError,
    pack_frame,
)


class FrameParserTest(unittest.TestCase):
    def test_empty_buffer(self):
        self.assertIsNone(FrameParser().next_frame())

    def test_frame_in_two_parts(self):
        raw = pack_frame(0x84, 1, b"hello")
        parser = FrameParser()

        parser.feed(raw[:5])
        self.assertIsNone(parser.next_frame())

        parser.feed(raw[5:])
        frame = parser.next_frame()
        self.assertEqual((frame.msg_type, frame.seq, frame.payload), (0x84, 1, b"hello"))
        self.assertIsNone(parser.next_frame())

    def test_two_frames_in_one_feed(self):
        parser = FrameParser()
        parser.feed(pack_frame(0x7F, 1, b"one") + pack_frame(0x7F, 2, b"two"))

        first = parser.next_frame()
        second = parser.next_frame()
        self.assertEqual((first.seq, first.payload), (1, b"one"))
        self.assertEqual((second.seq, second.payload), (2, b"two"))
        self.assertIsNone(parser.next_frame())

    def test_payload_split(self):
        raw = pack_frame(0x84, 5, b"abcdef")
        parser = FrameParser()

        parser.feed(raw[: HEADER.size + 2])  # 头 + 2 B 载荷
        self.assertIsNone(parser.next_frame())

        parser.feed(raw[HEADER.size + 2 :])
        self.assertEqual(parser.next_frame().payload, b"abcdef")

    def test_bad_magic_raises(self):
        parser = FrameParser()
        parser.feed(HEADER.pack(MAGIC ^ 0xFFFF, VERSION, 0x84, 1, 0))
        with self.assertRaises(ProtocolError):
            parser.next_frame()

    def test_oversized_length_raises(self):
        parser = FrameParser()
        parser.feed(HEADER.pack(MAGIC, VERSION, 0x84, 1, MAX_PAYLOAD + 1))
        with self.assertRaises(ProtocolError):
            parser.next_frame()

    def test_empty_payload(self):
        parser = FrameParser()
        parser.feed(pack_frame(0x84, 1, b""))
        frame = parser.next_frame()
        self.assertEqual(frame.payload, b"")
        self.assertIsNone(parser.next_frame())

    def test_every_split_point(self):
        raw = pack_frame(0x84, 9, b"0123456789")
        for split in range(len(raw) + 1):
            with self.subTest(split=split):
                parser = FrameParser()
                parser.feed(raw[:split])
                frame = parser.next_frame()
                if frame is None:
                    parser.feed(raw[split:])
                    frame = parser.next_frame()
                self.assertEqual(frame.payload, b"0123456789")


if __name__ == "__main__":
    unittest.main()
