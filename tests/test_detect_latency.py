"""E8 检测时效脚本的纯函数测试（分组统计）。"""

import unittest

from tools.detect_latency import summarize


def row(timeout: float, mode: str, latency: float | None, ok: bool = True) -> dict:
    data = {"timeout_s": timeout, "mode": mode, "ok": ok}
    if latency is not None:
        data["latency_ms"] = latency
    return data


class SummarizeTest(unittest.TestCase):
    def test_groups_by_timeout_and_mode(self):
        rows = [
            row(3, "freeze", 3350.0), row(3, "freeze", 3360.0), row(3, "freeze", 3362.0),
            row(3, "kill", 11.6),
        ]
        stats = summarize(rows)
        self.assertEqual(len(stats), 2)
        freeze = [s for s in stats if s["mode"] == "freeze"][0]
        self.assertEqual(freeze["runs"], 3)
        self.assertAlmostEqual(freeze["mean_ms"], 3357.3, places=1)
        self.assertAlmostEqual(freeze["min_ms"], 3350.0, places=1)
        self.assertAlmostEqual(freeze["max_ms"], 3362.0, places=1)

    def test_overhead_is_measured_beyond_timeout(self):
        """「超出超时值」是本实验的核心量：三档应当几乎相同。"""
        stats = summarize([row(10, "freeze", 10350.0)])
        self.assertAlmostEqual(stats[0]["overhead_ms"], 350.0, places=1)

    def test_failed_runs_are_excluded(self):
        rows = [row(3, "freeze", 3350.0), row(3, "freeze", None, ok=False)]
        stats = summarize(rows)
        self.assertEqual(stats[0]["runs"], 1)

    def test_empty(self):
        self.assertEqual(summarize([]), [])


if __name__ == "__main__":
    unittest.main()