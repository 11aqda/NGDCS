"""protocol.snapshot 的最小快照编解码测试。"""

import unittest

from protocol.framing import ProtocolError
from protocol.snapshot import (
    PLAYER,
    SNAPSHOT_HEADER,
    PlayerSnapshot,
    pack_snapshot,
    unpack_snapshot,
)


class SnapshotTest(unittest.TestCase):
    def test_header_and_player_sizes(self):
        self.assertEqual(SNAPSHOT_HEADER.size, 13)
        self.assertEqual(PLAYER.size, 11)

    def test_round_trip_two_players(self):
        players = [
            PlayerSnapshot(1, 100, 200, 3, 2, 1, 42),
            PlayerSnapshot(2, 300, 400, 5, 4, 1, 999),
        ]
        snapshot = unpack_snapshot(pack_snapshot(123, players))

        self.assertEqual(snapshot.tick, 123)
        self.assertEqual(snapshot.level, 1)
        self.assertEqual(snapshot.wave, 1)
        self.assertEqual(snapshot.wave_state, 0)
        self.assertEqual(snapshot.players, tuple(players))

    def test_empty_players(self):
        snapshot = unpack_snapshot(pack_snapshot(1, []))
        self.assertEqual(snapshot.players, ())

    def test_truncated_payload(self):
        with self.assertRaises(ProtocolError):
            unpack_snapshot(b"\x00" * (SNAPSHOT_HEADER.size - 1))

    def test_player_count_mismatch(self):
        # 头里说 2 个玩家，实际一个条目都没有
        header = SNAPSHOT_HEADER.pack(1, 1, 1, 0, 2, 0, 0, 0, 0)
        with self.assertRaises(ProtocolError):
            unpack_snapshot(header)

    def test_non_player_counts_rejected(self):
        # 本阶段只支持玩家快照
        header = SNAPSHOT_HEADER.pack(1, 1, 1, 0, 0, 1, 0, 0, 0)
        with self.assertRaises(ProtocolError):
            unpack_snapshot(header)

    def test_max_values(self):
        player = PlayerSnapshot(0xFFFF, 0xFFFF, 0xFFFF, 0xFF, 0xFF, 0xFF, 0xFFFF)
        snapshot = unpack_snapshot(pack_snapshot(0xFFFFFFFF, [player]))
        self.assertEqual(snapshot.players[0], player)


if __name__ == "__main__":
    unittest.main()
