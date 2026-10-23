"""玩家运动学（服务端权威、整数定点）的单元测试。"""

import unittest

from protocol.messages import KEY_LEFT, KEY_RIGHT
from protocol.world import PLAYER_MARGIN, WORLD_WIDTH
from server.main import TICK_HZ
from server.movement import (
    MAX_X,
    MIN_X,
    PLAYER_SPEED_PER_TICK,
    apply_input,
    clamp_x,
    keys_to_dx,
)


class KeysToDxTest(unittest.TestCase):
    def test_speed_is_300_px_per_second(self):
        # 15 px/tick × 20 tick/s = 300 px/s → 2.4 秒横穿 720 px 屏幕
        self.assertEqual(PLAYER_SPEED_PER_TICK * TICK_HZ, 300)

    def test_left_and_right(self):
        self.assertEqual(keys_to_dx(KEY_LEFT), -PLAYER_SPEED_PER_TICK)
        self.assertEqual(keys_to_dx(KEY_RIGHT), PLAYER_SPEED_PER_TICK)

    def test_no_key_does_not_move(self):
        self.assertEqual(keys_to_dx(0), 0)

    def test_both_keys_cancel_out(self):
        # 有意为之：真实玩家可能同时按住 A 和 D，抵消最符合直觉
        self.assertEqual(keys_to_dx(KEY_LEFT | KEY_RIGHT), 0)

    def test_reserved_bits_are_masked(self):
        # 保留位（bit 2~7）必须被掩掉，不能影响移动
        self.assertEqual(keys_to_dx(KEY_LEFT | 0b11111100), -PLAYER_SPEED_PER_TICK)


class ClampTest(unittest.TestCase):
    def test_bounds_keep_a_margin(self):
        self.assertEqual(MIN_X, PLAYER_MARGIN)
        self.assertEqual(MAX_X, WORLD_WIDTH - PLAYER_MARGIN)

    def test_clamp_both_ends(self):
        self.assertEqual(clamp_x(-9999), MIN_X)
        self.assertEqual(clamp_x(9999), MAX_X)
        self.assertEqual(clamp_x(360), 360)


class ApplyInputTest(unittest.TestCase):
    def test_walks_left_and_right(self):
        self.assertEqual(apply_input(360, KEY_RIGHT), 375)
        self.assertEqual(apply_input(360, KEY_LEFT), 345)

    def test_stops_at_left_wall(self):
        # 一直按住左键：走到 MIN_X 就停住，不会越界（也不是「卡死」，松手就恢复）
        x = 360
        for _ in range(100):
            x = apply_input(x, KEY_LEFT)
        self.assertEqual(x, MIN_X)

    def test_stops_at_right_wall(self):
        x = 360
        for _ in range(100):
            x = apply_input(x, KEY_RIGHT)
        self.assertEqual(x, MAX_X)

    def test_deterministic(self):
        # 整数定点位移的收益：同样的输入序列必然得到同样的轨迹，实验可复现
        keys_sequence = [KEY_LEFT, KEY_LEFT, KEY_RIGHT, 0, KEY_RIGHT, KEY_RIGHT]

        def run():
            x = 360
            for keys in keys_sequence:
                x = apply_input(x, keys)
            return x

        self.assertEqual(run(), run())
        self.assertEqual(run(), 375)


if __name__ == "__main__":
    unittest.main()