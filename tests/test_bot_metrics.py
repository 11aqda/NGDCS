"""机器人指标汇总的单元测试。"""

import argparse
import unittest

from bot.main import BotResult, percentile, summarize


class BotMetricsTest(unittest.TestCase):
    def test_percentile_empty(self):
        self.assertEqual(percentile([], 0.5), 0.0)

    def test_percentile_median_and_p95(self):
        values = [0.05, 0.06, 0.04, 0.07, 0.05]
        self.assertAlmostEqual(percentile(values, 0.50), 0.05)
        self.assertAlmostEqual(percentile(values, 0.95), 0.07)

    def test_summarize(self):
        results = [
            BotResult(connected=True, snapshots=10, bytes=100, intervals=[0.05] * 9),
            BotResult(connected=True, snapshots=10, bytes=100, intervals=[0.06] * 9),
        ]
        args = argparse.Namespace(
            host="127.0.0.1", port=9527, clients=2, duration=1.0, ramp=0.0
        )

        summary = summarize(results, args, elapsed=2.0)

        self.assertEqual(summary["clients_connected"], 2)
        self.assertEqual(summary["snapshots"], 20)
        self.assertEqual(summary["bytes"], 200)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["snapshots_per_s"], 10.0)
        self.assertEqual(summary["avg_snapshots_per_bot"], 10.0)
        self.assertGreater(summary["interval_p50_ms"], 0)


if __name__ == "__main__":
    unittest.main()
