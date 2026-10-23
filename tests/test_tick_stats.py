"""tick 统计窗口（E9 的数据源）的单元测试。"""

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
        result = TickStats().flush()
        self.assertEqual(result["ticks"], 0)
        self.assertEqual(result["avg_ms"], 0.0)
        self.assertEqual(result["max_ms"], 0.0)
        self.assertEqual(result["snapshot_bytes"], 0)
        self.assertEqual(result["packets_out"], 0)

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

    def test_counts_incoming_frames(self):
        stats = TickStats()
        for _ in range(7):
            stats.record_in_frame(13)

        result = stats.flush()
        # 窗口约 1 秒（20 个 tick），所以 packets_in 就是每秒帧数
        self.assertEqual(result["packets_in"], 7)
        self.assertEqual(result["bytes_in"], 7 * 13)

    def test_counts_outgoing_frames(self):
        # 广播时每个收件人各记一次，这才是真实下行带宽
        stats = TickStats()
        for _ in range(4):
            stats.record_out_frame(1951)

        result = stats.flush()
        self.assertEqual(result["packets_out"], 4)
        self.assertEqual(result["bytes_out"], 4 * 1951)

    def test_snapshot_bytes_is_counted_once_per_tick(self):
        # 和 bytes_out 是两个量：快照大小是「一份」，bytes_out 是「一份 × 收件人」
        stats = TickStats()
        stats.record_snapshot(1939)
        stats.record_snapshot(1939)
        stats.record_out_frame(1951)
        stats.record_out_frame(1951)

        result = stats.flush()
        self.assertEqual(result["snapshot_bytes"], 1939)
        self.assertEqual(result["bytes_out"], 3902)

    def test_flush_clears_the_window(self):
        stats = TickStats()
        stats.record_tick(0.01)
        stats.record_in_frame(13)
        stats.flush()

        second = stats.flush()
        self.assertEqual(second["ticks"], 0)
        self.assertEqual(second["packets_in"], 0)
        self.assertEqual(second["bytes_out"], 0)


if __name__ == "__main__":
    unittest.main()