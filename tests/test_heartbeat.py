"""心跳编解码、RTT 计算与超时判定的单元测试。

超时用**假的 now** 注入，不真的 sleep 15 秒 —— 测试要毫秒级、可重复。
"""

import unittest

from protocol.framing import ProtocolError
from protocol.messages import (
    HEARTBEAT,
    HEARTBEAT_ACK,
    now_ms,
    pack_heartbeat,
    pack_heartbeat_ack,
    rtt_ms,
    unpack_heartbeat,
    unpack_heartbeat_ack,
)
from server.main import Client, GameServer


def make_server(**kwargs):
    server = GameServer(**kwargs)
    client = Client(player_id=1, color=0, x=360, y=760, writer=None)
    server.clients[1] = client
    return server, client


class HeartbeatCodecTest(unittest.TestCase):
    def test_payload_sizes_match_protocol_doc(self):
        # 02-协议设计.md §6：client_time uint32；ack 再带一个 server_time
        self.assertEqual(HEARTBEAT.size, 4)
        self.assertEqual(HEARTBEAT_ACK.size, 8)

    def test_heartbeat_round_trip(self):
        self.assertEqual(unpack_heartbeat(pack_heartbeat(12345678)), 12345678)

    def test_heartbeat_ack_round_trip(self):
        payload = pack_heartbeat_ack(12345678, 87654321)
        self.assertEqual(unpack_heartbeat_ack(payload), (12345678, 87654321))

    def test_wrong_length_rejected(self):
        with self.assertRaises(ProtocolError):
            unpack_heartbeat(b"\x01\x02")
        with self.assertRaises(ProtocolError):
            unpack_heartbeat_ack(b"\x01\x02\x03\x04")

    def test_out_of_range_rejected(self):
        for value in (-1, 1 << 32):
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    pack_heartbeat(value)
                with self.assertRaises(ProtocolError):
                    pack_heartbeat_ack(value, 0)


class RttTest(unittest.TestCase):
    def test_now_ms_fits_in_uint32(self):
        self.assertTrue(0 <= now_ms() <= 0xFFFFFFFF)

    def test_rtt_from_explicit_timestamps(self):
        self.assertEqual(rtt_ms(1000, 1004), 4)

    def test_rtt_survives_32bit_wraparound(self):
        # 已经绕过一圈：0xFFFFFFF0 → 0x00000010 是 32 ms，不是 -4294967264
        self.assertEqual(rtt_ms(0xFFFFFFF0, 0x00000010), 32)

    def test_rtt_of_immediate_ack_is_zero(self):
        self.assertEqual(rtt_ms(12345, 12345), 0)


class TimeoutTest(unittest.TestCase):
    def test_fresh_client_not_timed_out(self):
        server, client = make_server(timeout=15.0)
        client.last_recv_at = 100.0
        self.assertEqual(server.check_timeouts(110.0), [])

    def test_exactly_at_timeout_is_still_alive(self):
        # 边界：差值 == timeout 不算超时（用的是 > 而不是 >=）
        server, client = make_server(timeout=15.0)
        client.last_recv_at = 100.0
        self.assertEqual(server.check_timeouts(115.0), [])

    def test_stale_client_is_timed_out(self):
        server, client = make_server(timeout=15.0)
        client.last_recv_at = 100.0
        self.assertEqual(server.check_timeouts(115.1), [client])

    def test_timeout_zero_disables_check(self):
        # --timeout 0 用来做「纯广播」基线实验：客户端不发心跳也不会被踢
        server, client = make_server(timeout=0)
        client.last_recv_at = 0.0
        self.assertEqual(server.check_timeouts(1e9), [])

    def test_check_timeouts_does_not_close_anything(self):
        # 只判定不关闭 —— 关闭统一由 tick_loop 做，清理统一由 handle_client 做
        server, client = make_server(timeout=15.0)
        client.last_recv_at = 100.0
        server.check_timeouts(200.0)
        self.assertIn(1, server.clients)


if __name__ == "__main__":
    unittest.main()