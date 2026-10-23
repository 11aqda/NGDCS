"""机器人指标汇总的单元测试。"""

import unittest

from bot.agent import BotConfig, BotResult
from bot.main import percentile, summarize


class BotMetricsTest(unittest.TestCase):
    def test_percentile_empty(self):
        self.assertEqual(percentile([], 0.5), 0.0)

    def test_percentile_median_and_p95(self):
        values = [0.05, 0.06, 0.04, 0.07, 0.05]
        self.assertAlmostEqual(percentile(values, 0.50), 0.05)
        self.assertAlmostEqual(percentile(values, 0.95), 0.07)

    def test_summarize_snapshot_metrics(self):
        results = [
            BotResult(connected=True, snapshots=10, bytes=100, intervals=[0.05] * 9),
            BotResult(connected=True, snapshots=10, bytes=100, intervals=[0.06] * 9),
        ]
        config = BotConfig(host="127.0.0.1", port=9527, duration=1.0)

        summary = summarize(results, config, clients=2, ramp=0.0, elapsed=2.0)

        self.assertEqual(summary["clients_connected"], 2)
        self.assertEqual(summary["snapshots"], 20)
        self.assertEqual(summary["bytes"], 200)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["snapshots_per_s"], 10.0)
        self.assertEqual(summary["avg_snapshots_per_bot"], 10.0)
        self.assertGreater(summary["interval_p50_ms"], 0)

    def test_summarize_input_and_heartbeat_metrics(self):
        # rtts 与 intervals 一样，单位是秒；汇总时换算成毫秒
        results = [
            BotResult(
                connected=True,
                inputs_sent=40,
                heartbeats_sent=2,
                heartbeats_acked=2,
                rtts=[0.001, 0.003],
            ),
            BotResult(
                connected=True,
                inputs_sent=40,
                heartbeats_sent=2,
                heartbeats_acked=1,
                rtts=[0.002],
            ),
        ]
        config = BotConfig(
            host="127.0.0.1", port=9527, duration=2.0, input_hz=20.0, heartbeat=1.0
        )

        summary = summarize(results, config, clients=2, ramp=0.0, elapsed=2.0)

        self.assertEqual(summary["inputs_sent"], 80)
        self.assertEqual(summary["inputs_per_s"], 40.0)
        self.assertEqual(summary["heartbeats_sent"], 4)
        self.assertEqual(summary["heartbeats_acked"], 3)
        self.assertEqual(summary["rtt_p50_ms"], 2.0)
        self.assertEqual(summary["rtt_p95_ms"], 3.0)
        self.assertEqual(summary["input_hz"], 20.0)

    def test_summarize_without_heartbeat_ack_yields_zero_rtt(self):
        results = [BotResult(connected=True, heartbeats_sent=1)]
        config = BotConfig(duration=1.0)

        summary = summarize(results, config, clients=1, ramp=0.0, elapsed=1.0)

        self.assertEqual(summary["rtt_p50_ms"], 0.0)
        self.assertEqual(summary["errors"], 0)


if __name__ == "__main__":
    unittest.main()