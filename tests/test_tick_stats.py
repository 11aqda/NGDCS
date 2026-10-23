"""tick 耗时统计（E9 实验的数据源）的单元测试。"""

import unittest

from server.stats import TickStats, percentile


class PercentileTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(percentile([], 0.5), 0.0)

    def test_median_and_p95(self):
        values = [0.05, 0.06, 0.04, 0.07, 0.05]
        self.assertAlmostEqual(percentile(values, 0.50), 0.05)
        self.assertAlmostEqual(percentile(values, 0.95), 0.07)

    def test_single_value(self):
        self.assertAlmostEqual(percentile([0.02], 0.95), 0.02)


class TickStatsTest(unittest.TestCase):
    def test_flush_empty_window_returns_zeros(self):
        stats = TickStats()
        result = stats.flush()
        self.assertEqual(result["ticks"], 0)
        self.assertEqual(result["inputs"], 0)
        self.assertEqual(result["avg_ms"], 0.0)
        self.assertEqual(result["max_ms"], 0.0)

    def test_aggregates_durations(self):
        stats = TickStats()
        stats.record_tick(0.001)  # 1 ms
        stats.record_tick(0.003)  # 3 ms
        stats.record_tick(0.002)  # 2 ms

        result = stats.flush()
        self.assertEqual(result["ticks"], 3)
        self.assertAlmostEqual(result["avg_ms"], 2.0, places=3)
        self.assertAlmostEqual(result["p50_ms"], 2.0, places=3)
        self.assertAlmostEqual(result["max_ms"], 3.0, places=3)

    def test_counts_input_frames(self):
        stats = TickStats()
        for _ in range(7):
            stats.record_input()

        # 窗口约 1 秒（20 个 tick），所以 inputs 就是每秒输入帧数
        self.assertEqual(stats.flush()["inputs"], 7)

    def test_flush_clears_the_window(self):
        stats = TickStats()
        stats.record_tick(0.01)
        stats.record_input()
        stats.flush()

        second = stats.flush()
        self.assertEqual(second["ticks"], 0)
        self.assertEqual(second["inputs"], 0)


if __name__ == "__main__":
    unittest.main()