"""`C_AUTH` / `S_AUTH_OK` / `S_AUTH_FAIL` 的编解码测试（步骤 10b）。

这三个消息是**长短连接分层唯一的衔接点**（D-005）：
HTTP 登录拿 token → TCP 上用它认证。所以字节格式必须严格，
畸形载荷要**明确失败**，不能被当成"匿名登录"悄悄放过去。
"""

import unittest

from protocol.framing import ProtocolError
from protocol.messages import (
    C_AUTH,
    ERR_AUTH_FAILED,
    S_AUTH_FAIL,
    S_AUTH_OK,
    TOKEN_MAX,
    pack_auth,
    pack_auth_fail,
    pack_auth_ok,
    unpack_auth,
    unpack_auth_fail,
    unpack_auth_ok,
)


class ConstantsTest(unittest.TestCase):
    def test_type_codes_match_design(self):
        """编号必须与 `02 §5` 一致 —— 客户端和服务端各写一份就靠这个对齐。"""
        self.assertEqual(C_AUTH, 0x01)
        self.assertEqual(S_AUTH_OK, 0x81)
        self.assertEqual(S_AUTH_FAIL, 0x82)
        self.assertEqual(ERR_AUTH_FAILED, 0x01)

    def test_direction_bit(self):
        """`0x0X` 客户端→服务端，`0x8X` 服务端→客户端（02 §5 的约定）。"""
        self.assertLess(C_AUTH, 0x80)
        self.assertGreaterEqual(S_AUTH_OK, 0x80)
        self.assertGreaterEqual(S_AUTH_FAIL, 0x80)


class AuthPackTest(unittest.TestCase):
    def test_round_trip(self):
        token = "a" * 64
        version, parsed = unpack_auth(pack_auth(token))
        self.assertEqual(version, 1)
        self.assertEqual(parsed, token)

    def test_payload_is_version_plus_token(self):
        payload = pack_auth("abc123")
        self.assertEqual(len(payload), 1 + 6)
        self.assertEqual(payload[0], 1)
        self.assertEqual(payload[1:], b"abc123")

    def test_empty_token_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_auth("")

    def test_too_long_token_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_auth("a" * (TOKEN_MAX + 1))

    def test_non_ascii_token_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_auth("令牌")

    def test_truncated_payload_rejected(self):
        with self.assertRaises(ProtocolError):
            unpack_auth(b"")

    def test_version_only_rejected(self):
        """只有 version 没有 token —— 不能被当成"空 token 的匿名登录"。"""
        with self.assertRaises(ProtocolError):
            unpack_auth(b"\x01")

    def test_overlong_token_in_wire_rejected(self):
        with self.assertRaises(ProtocolError):
            unpack_auth(b"\x01" + b"a" * (TOKEN_MAX + 1))

    def test_invalid_ascii_in_wire_rejected(self):
        with self.assertRaises(ProtocolError):
            unpack_auth(b"\x01" + b"\xff\xfe")


class AuthOkTest(unittest.TestCase):
    def test_round_trip_chinese_nickname(self):
        """昵称要支持中文（UTF-8 多字节），长度按**字节**算。"""
        payload = pack_auth_ok(7, "玩家甲")
        player_id, nickname = unpack_auth_ok(payload)
        self.assertEqual(player_id, 7)
        self.assertEqual(nickname, "玩家甲")

    def test_length_mismatch_rejected(self):
        payload = pack_auth_ok(1, "ab")
        with self.assertRaises(ProtocolError):
            unpack_auth_ok(payload[:-1])

    def test_empty_nickname_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_auth_ok(1, "")

    def test_too_long_nickname_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_auth_ok(1, "名" * 21)

    def test_player_id_out_of_range(self):
        with self.assertRaises(ProtocolError):
            pack_auth_ok(0x10000, "ab")


class AuthFailTest(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(unpack_auth_fail(pack_auth_fail()), ERR_AUTH_FAILED)

    def test_wrong_size_rejected(self):
        with self.assertRaises(ProtocolError):
            unpack_auth_fail(b"")


if __name__ == "__main__":
    unittest.main()