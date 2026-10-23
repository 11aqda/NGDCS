"""C_INPUT 编解码 + 输入保质期（INPUT_TTL）的单元测试。"""

import unittest

from protocol.framing import ProtocolError
from protocol.messages import (
    C_HEARTBEAT,
    C_INPUT,
    INPUT,
    KEY_LEFT,
    KEY_RIGHT,
    KEYS_MASK,
    S_HEARTBEAT_ACK,
    pack_keys,
    unpack_keys,
)
from server.main import Client, GameServer
from server.movement import PLAYER_SPEED_PER_TICK


def make_server(**kwargs):
    """造一个不碰 socket 的服务端 + 一个占位客户端。"""
    server = GameServer(**kwargs)
    client = Client(player_id=1, color=0, x=360, y=760, writer=None)
    server.clients[1] = client
    return server, client


class KeysCodecTest(unittest.TestCase):
    def test_type_codes_match_protocol_doc(self):
        # 02-协议设计.md §5.1 / §5.2
        self.assertEqual(C_INPUT, 0x06)
        self.assertEqual(C_HEARTBEAT, 0x07)
        self.assertEqual(S_HEARTBEAT_ACK, 0x87)

    def test_payload_is_exactly_one_byte(self):
        self.assertEqual(INPUT.size, 1)

    def test_round_trip_all_states(self):
        for keys in (0, KEY_LEFT, KEY_RIGHT, KEY_LEFT | KEY_RIGHT):
            with self.subTest(keys=keys):
                self.assertEqual(unpack_keys(pack_keys(keys)), keys)

    def test_wrong_length_rejected(self):
        # 多一字节 / 少一字节都是协议错误：帧层的 length 对了，不代表业务载荷对
        for payload in (b"", b"\x01\x02"):
            with self.subTest(payload=payload):
                with self.assertRaises(ProtocolError):
                    unpack_keys(payload)

    def test_out_of_range_rejected(self):
        for keys in (-1, 256):
            with self.subTest(keys=keys):
                with self.assertRaises(ProtocolError):
                    pack_keys(keys)

    def test_reserved_bits_pass_through_codec(self):
        # 协议层只校验长度，不判断位含义 —— 保留位留给业务层用 KEYS_MASK 掩掉。
        # 这样将来加新位（比如上下移动 bit 2）时旧服务端不会直接报错断连。
        self.assertEqual(unpack_keys(pack_keys(0xFF)), 0xFF)

    def test_keys_mask_covers_both_directions(self):
        self.assertEqual(KEYS_MASK, 0b11)


class InputTtlTest(unittest.TestCase):
    def test_fresh_input_is_used(self):
        server, client = make_server(input_ttl=0.5)
        client.keys = KEY_LEFT
        client.last_input_at = 100.0
        self.assertEqual(server.active_keys(client, 100.4), KEY_LEFT)

    def test_exactly_at_ttl_is_still_fresh(self):
        # 边界：差值 == ttl 不算过期（用的是 > 而不是 >=）
        server, client = make_server(input_ttl=0.5)
        client.keys = KEY_RIGHT
        client.last_input_at = 100.0
        self.assertEqual(server.active_keys(client, 100.5), KEY_RIGHT)

    def test_stale_input_becomes_idle(self):
        # 输入有保质期：客户端失联后不能让它一直「幽灵移动」
        server, client = make_server(input_ttl=0.5)
        client.keys = KEY_LEFT
        client.last_input_at = 100.0
        self.assertEqual(server.active_keys(client, 100.6), 0)

    def test_update_players_moves_with_input(self):
        server, client = make_server()
        client.keys = KEY_RIGHT
        client.last_input_at = 500.0

        server.update_players(500.0)
        self.assertEqual(client.x, 360 + PLAYER_SPEED_PER_TICK)

        client.keys = KEY_LEFT
        client.last_input_at = 500.05
        server.update_players(500.05)
        self.assertEqual(client.x, 360)

    def test_update_players_holds_still_when_stale(self):
        server, client = make_server(input_ttl=0.5)
        client.keys = KEY_LEFT
        client.last_input_at = 100.0

        server.update_players(101.0)
        self.assertEqual(client.x, 360)


if __name__ == "__main__":
    unittest.main()