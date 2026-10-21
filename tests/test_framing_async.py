"""asyncio 版帧接收的边界测试。"""

import asyncio
import unittest

from protocol.framing import (
    HEADER,
    MAGIC,
    VERSION,
    ProtocolError,
    pack_frame,
    recv_frame_async,
)


class AsyncFramingTest(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip(self):
        reader = asyncio.StreamReader()
        reader.feed_data(pack_frame(0x84, 42, b"hello"))
        reader.feed_eof()

        frame = await recv_frame_async(reader)

        self.assertEqual((frame.msg_type, frame.seq, frame.payload), (0x84, 42, b"hello"))

    async def test_clean_eof_returns_none(self):
        reader = asyncio.StreamReader()
        reader.feed_eof()
        self.assertIsNone(await recv_frame_async(reader))

    async def test_truncated_header_raises(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x00" * (HEADER.size - 1))
        reader.feed_eof()

        with self.assertRaises(ProtocolError):
            await recv_frame_async(reader)

    async def test_truncated_payload_raises(self):
        reader = asyncio.StreamReader()
        reader.feed_data(HEADER.pack(MAGIC, VERSION, 0x84, 1, 5) + b"ab")
        reader.feed_eof()

        with self.assertRaises(ProtocolError):
            await recv_frame_async(reader)

    async def test_zero_length_payload(self):
        reader = asyncio.StreamReader()
        reader.feed_data(pack_frame(0x84, 1, b""))
        reader.feed_eof()

        frame = await recv_frame_async(reader)
        self.assertEqual(frame.payload, b"")


if __name__ == "__main__":
    unittest.main()
