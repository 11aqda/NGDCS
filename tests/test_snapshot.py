"""S_SNAPSHOT 编解码测试：快照头 + 四类实体条目。

条目大小与 `02-协议设计.md §6.2` 逐字节对齐 —— 这些断言就是「代码没跑偏文档」的证明。
"""

import unittest

from protocol.framing import ProtocolError
from protocol.messages import ENEMY_BOSS, ENEMY_DIVE
from protocol.snapshot import (
    BULLET,
    ENEMY,
    ITEM,
    PLAYER,
    SNAPSHOT_HEADER,
    BulletSnapshot,
    EnemySnapshot,
    ItemSnapshot,
    PlayerSnapshot,
    pack_snapshot,
    unpack_snapshot,
)


class EntrySizeTest(unittest.TestCase):
    """条目大小必须和 02 §6.2 完全一致，差一个字节整条流就错位了。"""

    def test_sizes_match_protocol_doc(self):
        self.assertEqual(SNAPSHOT_HEADER.size, 13)
        self.assertEqual(PLAYER.size, 11)
        self.assertEqual(ENEMY.size, 9)
        self.assertEqual(BULLET.size, 8)
        self.assertEqual(ITEM.size, 7)


class PlayerSnapshotTest(unittest.TestCase):
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
        self.assertEqual(snapshot.enemies, ())
        self.assertEqual(snapshot.bullets, ())
        self.assertEqual(snapshot.items, ())

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

    def test_max_values(self):
        player = PlayerSnapshot(0xFFFF, 0xFFFF, 0xFFFF, 0xFF, 0xFF, 0xFF, 0xFFFF)
        snapshot = unpack_snapshot(pack_snapshot(0xFFFFFFFF, [player]))
        self.assertEqual(snapshot.players[0], player)


class EntitySnapshotTest(unittest.TestCase):
    def test_round_trip_all_four_kinds(self):
        players = [PlayerSnapshot(1, 360, 760)]
        enemies = [EnemySnapshot(7, 100, 50, ENEMY_DIVE, 3)]
        bullets = [
            BulletSnapshot(0, 200, 30, 0x11, 128),
            BulletSnapshot(1, 360, 900, 0x01, 0),
        ]
        items = [ItemSnapshot(5, 400, 500, 0x01)]

        snapshot = unpack_snapshot(
            pack_snapshot(9, players, enemies, bullets, items)
        )

        self.assertEqual(snapshot.players, tuple(players))
        self.assertEqual(snapshot.enemies, tuple(enemies))
        self.assertEqual(snapshot.bullets, tuple(bullets))
        self.assertEqual(snapshot.items, tuple(items))
        self.assertEqual(snapshot.entity_count, 5)

    def test_payload_length_is_exact(self):
        payload = pack_snapshot(
            1,
            [PlayerSnapshot(1, 1, 2)],
            [EnemySnapshot(1, 3, 4)],
            [BulletSnapshot(0, 5, 6)],
            [ItemSnapshot(1, 7, 8)],
        )
        self.assertEqual(
            len(payload),
            SNAPSHOT_HEADER.size + PLAYER.size + ENEMY.size + BULLET.size + ITEM.size,
        )

    def test_counts_are_written_into_header(self):
        payload = pack_snapshot(
            1,
            [PlayerSnapshot(1, 0, 0), PlayerSnapshot(2, 0, 0)],
            [EnemySnapshot(1, 0, 0)] * 3,
            [BulletSnapshot(0, 0, 0)] * 4,
            [ItemSnapshot(1, 0, 0)] * 5,
        )
        counts = SNAPSHOT_HEADER.unpack_from(payload, 0)[4:8]
        self.assertEqual(counts, (2, 3, 4, 5))

    def test_entity_count_while_on_screen(self):
        # 30 敌机 + 200 子弹 + 4 玩家 = 234：正好是 E9 的设计目标规模
        snapshot = unpack_snapshot(
            pack_snapshot(
                1,
                [PlayerSnapshot(i, 0, 0) for i in range(4)],
                [EnemySnapshot(i, 0, 0) for i in range(30)],
                [BulletSnapshot(0, 0, 0) for _ in range(200)],
            )
        )
        self.assertEqual(snapshot.entity_count, 234)
        self.assertEqual(len(snapshot.bullets), 200)

    def test_too_many_enemies_rejected(self):
        # enemy_count 是 uint8，256 个就溢出了
        with self.assertRaises(ProtocolError):
            pack_snapshot(1, [], [EnemySnapshot(i, 0, 0) for i in range(256)])

    def test_too_many_players_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_snapshot(1, [PlayerSnapshot(i, 0, 0) for i in range(256)])

    def test_unknown_enemy_type_is_preserved(self):
        # 解码端要能原样带出没见过的类型（前向兼容），而不是报错
        snapshot = unpack_snapshot(
            pack_snapshot(1, [], [EnemySnapshot(1, 0, 0, 0x42, 9)])
        )
        self.assertEqual(snapshot.enemies[0].type, 0x42)
        self.assertEqual(snapshot.enemies[0].hp, 9)

    def test_trailing_garbage_rejected(self):
        # 多出来的字节若是被当成下一条消息，就是粘包 bug 的经典来源
        payload = pack_snapshot(1, [PlayerSnapshot(1, 0, 0)]) + b"\x00"
        with self.assertRaises(ProtocolError):
            unpack_snapshot(payload)


class BossFlagTest(unittest.TestCase):
    """boss_present 由敌机列表**推导**，不单独传参 —— 两个字段不可能矛盾。"""

    def test_no_boss_when_no_boss_enemy(self):
        snapshot = unpack_snapshot(
            pack_snapshot(1, [], [EnemySnapshot(1, 0, 0, ENEMY_DIVE)])
        )
        self.assertFalse(snapshot.boss_present)

    def test_boss_flag_derived_from_type(self):
        snapshot = unpack_snapshot(
            pack_snapshot(
                1,
                [],
                [EnemySnapshot(1, 0, 0, ENEMY_DIVE), EnemySnapshot(2, 0, 0, ENEMY_BOSS)],
            )
        )
        self.assertTrue(snapshot.boss_present)

    def test_boss_flag_with_no_enemies(self):
        self.assertFalse(unpack_snapshot(pack_snapshot(1, [])).boss_present)


if __name__ == "__main__":
    unittest.main()