"""快照编码器的测试（E1 实验的基础）。

**最要紧的一条**：`binary_fast` 与 `binary` 必须产出**逐字节相同**的载荷。
E1 要回答"实现方式能带来多少差异"，这个前提不成立的话整个实验就没有意义 ——
跑得快可能只是因为**少编码了东西**。

所以这里用多种实体组合做全等断言，并且顺手验一遍 `binary_fast` 的产物能被
`unpack_snapshot` 正确解回来（全等 + 可解析，两个都过了才算数）。
"""

import json
import struct
import unittest

from protocol.encoders import (
    ENCODER_NAMES,
    BinaryEncoder,
    FastBinaryEncoder,
    JsonEncoder,
    _fast_struct,
    get_encoder,
    unpack_snapshot_json,
)
from protocol.messages import ENEMY_BOSS, ENEMY_DIVE
from protocol.snapshot import (
    BulletSnapshot,
    EnemySnapshot,
    ItemSnapshot,
    PlayerSnapshot,
    ProtocolError,
    unpack_snapshot,
)


def players(n=2):
    return [
        PlayerSnapshot(
            player_id=i + 1, x=100 + i * 10, y=200 + i, power=1,
            color=i % 8, flags=1, score=i * 100,
        )
        for i in range(n)
    ]


def enemies(n=3, boss=False):
    out = [
        EnemySnapshot(enemy_id=i + 1, x=50 + i, y=60 + i, type=ENEMY_DIVE, hp=3)
        for i in range(n)
    ]
    if boss:
        out.append(EnemySnapshot(enemy_id=99, x=360, y=80, type=ENEMY_BOSS, hp=200))
    return out


def bullets(n=4):
    # angle 是 uint8（0~255，02 §4.5），所以这里必须取模 ——
    # 200 颗子弹时 i*8 会到 1592，直接 struct.error
    return [
        BulletSnapshot(owner_id=1, x=10 + i, y=20 + i, type=0x10, angle=(i * 8) % 256)
        for i in range(n)
    ]


def items(n=2):
    return [ItemSnapshot(item_id=i + 1, x=30 + i, y=40, type=0x01) for i in range(n)]


# 覆盖各种"空 / 只有一类 / 全都有 / 有 BOSS"的组合
CASES = [
    ("全空", 0, 0, 0, 0, False),
    ("只有玩家", 3, 0, 0, 0, False),
    ("只有敌机", 0, 5, 0, 0, False),
    ("只有子弹", 0, 0, 7, 0, False),
    ("只有道具", 0, 0, 0, 3, False),
    ("标准规模", 4, 30, 200, 0, False),
    ("带 BOSS", 2, 4, 6, 2, True),
    ("大数量", 8, 100, 300, 5, False),
]


class EquivalenceTest(unittest.TestCase):
    """`binary_fast` 必须与 `binary` 逐字节相同。"""

    def test_byte_identical_across_all_cases(self):
        binary, binary_fast = BinaryEncoder(), FastBinaryEncoder()
        for label, np, ne, nb, ni, boss in CASES:
            with self.subTest(case=label):
                args = (players(np), enemies(ne, boss), bullets(nb), items(ni))
                self.assertEqual(
                    binary_fast.encode(1234, *args),
                    binary.encode(1234, *args),
                    f"{label}：binary_fast 与 binary 产物不一致 —— "
                    f"E1 的对比就不成立了（可能少编码了东西）",
                )

    def test_header_fields_come_from_arguments(self):
        # level / wave / wave_state 也要逐字节一致，不能只对实体部分
        binary, binary_fast = BinaryEncoder(), FastBinaryEncoder()
        args = (players(2), enemies(3), bullets(4), items(1))
        for level, wave, state in ((1, 1, 0), (3, 7, 2), (0, 0, 0)):
            with self.subTest(level=level, wave=wave, state=state):
                self.assertEqual(
                    binary_fast.encode(9, *args, level, wave, state),
                    binary.encode(9, *args, level, wave, state),
                )

    def test_binary_fast_output_parses_back(self):
        """全等还不够 —— 产物必须真的能被协议解回来。"""
        binary_fast = FastBinaryEncoder()
        payload = binary_fast.encode(
            777, players(2), enemies(3, boss=True), bullets(4), items(2), level=2, wave=5
        )
        snap = unpack_snapshot(payload)

        self.assertEqual(snap.tick, 777)
        self.assertEqual(snap.level, 2)
        self.assertEqual(snap.wave, 5)
        self.assertEqual(len(snap.players), 2)
        self.assertEqual(len(snap.enemies), 4)  # 3 + BOSS
        self.assertEqual(len(snap.bullets), 4)
        self.assertEqual(len(snap.items), 2)
        self.assertEqual(snap.enemies[-1].type, ENEMY_BOSS)

    def test_boss_flag_is_derived_not_passed(self):
        # 与 pack_snapshot 同样的推导规则：有 BOSS 才置 1。
        # 用 unpack 取、不数下标 —— 快照头 !IBBBBBHBB 里 boss_present 在第 13 字节，
        # 数错了测试照样"通过"，却什么也没验证到
        binary_fast = FastBinaryEncoder()
        self.assertFalse(
            unpack_snapshot(binary_fast.encode(1, players(1), enemies(2), bullets(0))).boss_present
        )
        self.assertFalse(
            unpack_snapshot(binary_fast.encode(1, players(1), enemies(0), bullets(0))).boss_present
        )
        self.assertTrue(
            unpack_snapshot(
                binary_fast.encode(1, players(1), enemies(2, boss=True), bullets(0))
            ).boss_present
        )


class CountLimitTest(unittest.TestCase):
    def test_binary_fast_rejects_too_many_enemies(self):
        # enemy_count 是 uint8：超过 255 必须在编码前报协议错，而不是 struct.error
        with self.assertRaises(ProtocolError):
            FastBinaryEncoder().encode(1, players(1), enemies(300), bullets(0))

    def test_binary_fast_rejects_too_many_players(self):
        with self.assertRaises(ProtocolError):
            FastBinaryEncoder().encode(1, players(300), enemies(0), bullets(0))

    def test_binary_fast_accepts_the_uint16_bullet_limit(self):
        # 子弹上限是 uint16（0xFFFF），E9 顶格用到的 2000 远在范围内
        payload = FastBinaryEncoder().encode(1, players(1), enemies(0), bullets(2000))
        self.assertEqual(len(unpack_snapshot(payload).bullets), 2000)


class FormatCacheTest(unittest.TestCase):
    """格式串缓存 —— 不缓存的话 `binary_fast` 会比 `binary` 还慢。"""

    def test_same_counts_reuse_one_struct(self):
        a = _fast_struct(4, 30, 200, 0)
        b = _fast_struct(4, 30, 200, 0)
        self.assertIs(a, b, "相同实体数应命中同一缓存的 Struct")

    def test_different_counts_get_different_struct(self):
        self.assertIsNot(_fast_struct(4, 30, 200, 0), _fast_struct(4, 30, 201, 0))

    def test_struct_size_matches_the_protocol_formula(self):
        # 13 字节头 + 11/9/8/7 字节条目 —— 与 02 §6.2 的布局公式一致
        layout = _fast_struct(4, 30, 200, 5)
        self.assertEqual(layout.size, 13 + 4 * 11 + 30 * 9 + 200 * 8 + 5 * 7)

    def test_format_is_derived_from_the_struct_definitions(self):
        # 派生而非手抄：协议改了这里自动跟着改（手抄一份就会悄悄不一致）
        self.assertEqual(_fast_struct(1, 0, 0, 0).size, 13 + 11)

    def test_big_endian_is_kept(self):
        # 整帧只在最前面留一个 `!`；漏了它就会变成小端，协议直接崩
        payload = FastBinaryEncoder().encode(1, players(1), enemies(0), bullets(0))
        # tick 是大端 uint32 打在头 4 字节
        self.assertEqual(struct.unpack("!I", payload[:4])[0], 1)


class JsonEncoderTest(unittest.TestCase):
    def test_output_is_valid_json(self):
        raw = JsonEncoder().encode(5, players(2), enemies(3), bullets(4), items(1))
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual(data["t"], 5)
        self.assertEqual(len(data["p"]), 2)
        self.assertEqual(len(data["e"]), 3)
        self.assertEqual(len(data["b"]), 4)
        self.assertEqual(len(data["i"]), 1)

    def test_entries_are_objects_with_short_keys(self):
        data = json.loads(
            JsonEncoder().encode(1, players(1), enemies(0), bullets(0)).decode()
        )
        self.assertIsInstance(data["p"][0], dict)
        self.assertEqual(data["p"][0]["i"], 1)

    def test_no_whitespace_padding(self):
        # separators 去掉空格：这是"认真写 JSON"该做的
        raw = JsonEncoder().encode(1, players(1), enemies(0), bullets(0)).decode()
        self.assertNotIn(": ", raw)
        self.assertNotIn(", ", raw)

    def test_boss_flag_matches_binary(self):
        json_enc, binary_fast = JsonEncoder(), FastBinaryEncoder()
        for boss in (False, True):
            with self.subTest(boss=boss):
                args = (players(1), enemies(2, boss), bullets(0))
                data = json.loads(json_enc.encode(1, *args).decode())
                self.assertEqual(
                    data["bp"],
                    unpack_snapshot(binary_fast.encode(1, *args)).boss_present,
                )

    def test_json_is_far_larger_than_binary(self):
        # E1 的核心预期：体积差好几倍
        args = (players(4), enemies(30), bullets(200), items(0))
        binary = len(FastBinaryEncoder().encode(1, *args))
        js = len(JsonEncoder().encode(1, *args))
        self.assertGreater(js / binary, 3.0, f"binary {binary} B vs json {js} B")


class JsonRoundTripTest(unittest.TestCase):
    """JSON 是**完整可用**的协议路径（编解码双向），不是一次性的序列化函数。"""

    def test_round_trip_preserves_every_field(self):
        for label, np, ne, nb, ni, boss in CASES:
            with self.subTest(case=label):
                args = (players(np), enemies(ne, boss), bullets(nb), items(ni))
                original = unpack_snapshot(
                    BinaryEncoder().encode(42, *args, level=3, wave=7, wave_state=1)
                )
                decoded = unpack_snapshot_json(
                    JsonEncoder().encode(42, *args, level=3, wave=7, wave_state=1)
                )
                self.assertEqual(decoded, original)

    def test_json_carries_the_same_entities_as_binary(self):
        """公平实现的可执行证据：三种编码装的是同一批数据。"""
        args = (players(4), enemies(30), bullets(200), items(0))
        from_binary = unpack_snapshot(BinaryEncoder().encode(1, *args))
        from_json = unpack_snapshot_json(JsonEncoder().encode(1, *args))

        self.assertEqual(from_json, from_binary)
        self.assertEqual(
            (len(from_json.players), len(from_json.enemies),
             len(from_json.bullets), len(from_json.items)),
            (4, 30, 200, 0),
        )

    def test_all_three_agree_on_one_state(self):
        args = (players(2), enemies(4, boss=True), bullets(6), items(2))
        binary = unpack_snapshot(BinaryEncoder().encode(9, *args))
        fast = unpack_snapshot(FastBinaryEncoder().encode(9, *args))
        js = unpack_snapshot_json(JsonEncoder().encode(9, *args))
        self.assertEqual(binary, fast)
        self.assertEqual(binary, js)

    def test_boss_flag_survives_the_round_trip(self):
        data = unpack_snapshot_json(
            JsonEncoder().encode(1, players(1), enemies(2, boss=True), bullets(0))
        )
        self.assertTrue(data.boss_present)
        self.assertEqual(data.enemies[-1].type, ENEMY_BOSS)


class FactoryTest(unittest.TestCase):
    def test_all_names_resolve(self):
        for name in ENCODER_NAMES:
            with self.subTest(name=name):
                self.assertEqual(get_encoder(name).name, name)

    def test_unknown_name_raises(self):
        # 不静默退回 binary —— 否则 `--encoder jsno` 会白跑一轮还标错编码
        with self.assertRaises(ValueError):
            get_encoder("jsno")

    def test_default_is_the_protocol_encoder(self):
        self.assertIsInstance(get_encoder("binary"), BinaryEncoder)


if __name__ == "__main__":
    unittest.main()