"""E5 的支撑代码测试：tick 率可配 + 统计窗口恒 1 秒。

## 为什么这几条必须有测试

E5 的整个结论建立在"**跨档可比**"上。如果窗口不是恒 1 秒，
10 Hz 的 `bytes_out` 代表 2 秒、30 Hz 代表 0.67 秒 —— 带宽曲线会画出一条
斜率错误的直线，**而且不会报错**。这种静默错误只有测试能守住。

所以这里断言的是：
1. `stats_every_ticks == tick_hz`（窗口恒等于 1 秒的 tick 数）
2. `tick_interval == 1 / tick_hz`
3. 默认仍是 20 Hz（不能悄悄改掉所有历史实验的基准）
"""

import unittest

from server.main import DEFAULT_TICK_HZ, GameServer


class TickRateTest(unittest.TestCase):
    def test_default_is_still_20hz(self):
        """默认值不能动 —— E1/E2/E9 的基线都是 20 Hz 下测的。"""
        self.assertEqual(DEFAULT_TICK_HZ, 20)
        self.assertEqual(GameServer().tick_hz, 20)

    def test_window_is_always_one_second(self):
        """**核心断言**：窗口的 tick 数 == tick 率，即窗口恒为 1 秒。"""
        for hz in (10, 15, 20, 30, 60):
            server = GameServer(tick_hz=hz)
            self.assertEqual(server.stats_every_ticks, hz, f"{hz} Hz 的窗口不是 1 秒")

    def test_tick_interval_matches_rate(self):
        for hz in (10, 15, 20, 30):
            server = GameServer(tick_hz=hz)
            self.assertAlmostEqual(server.tick_interval, 1.0 / hz, places=9)

    def test_10hz_interval_is_100ms(self):
        self.assertAlmostEqual(GameServer(tick_hz=10).tick_interval, 0.1, places=9)

    def test_30hz_interval_is_about_33ms(self):
        self.assertAlmostEqual(GameServer(tick_hz=30).tick_interval, 1 / 30, places=9)

    def test_negative_rate_is_not_silently_accepted(self):
        """0 或负数会让 `1/tick_hz` 炸掉或变成无穷 —— 宁可当场抛错。

        这不是给用户看的校验（CLI 另有检查），而是防止有人写
        `GameServer(tick_hz=0)` 之后在 tick 循环里出现难查的死循环。
        """
        with self.assertRaises(ZeroDivisionError):
            GameServer(tick_hz=0)


if __name__ == "__main__":
    unittest.main()