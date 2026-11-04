"""机器人侧 `err_px` 采集的接线测试。

重点不是数学（那在 `tests/test_interp.py` 里），而是**接线有没有接对**：

1. **默认必须是关的** —— 打开会给每帧做 `unpack_snapshot`，与客户端渲染同量级开销。
   E2/E9 的基线都是"只数帧不解析"下测的，默认打开会悄悄改变那些数据。
2. 关掉时 `summarize()` 必须给出 `None` 而不是 `0`（0 会被画图当成"误差为零"）。
3. `sim_loss` 要能反映在汇总里，否则复现时不知道这批数据是什么条件。
"""

import unittest

from bot.agent import BotConfig, BotResult
from bot.main import summarize


class ErrPxDefaultOffTest(unittest.TestCase):
    def test_measure_is_off_by_default(self):
        """**关键**：不能因为加了新功能就改变历史实验的负载。"""
        self.assertFalse(BotConfig().measure_err_px)

    def test_sim_loss_defaults_to_zero(self):
        self.assertEqual(BotConfig().sim_loss, 0.0)

    def test_can_be_enabled(self):
        config = BotConfig(measure_err_px=True, sim_loss=0.2)
        self.assertTrue(config.measure_err_px)
        self.assertAlmostEqual(config.sim_loss, 0.2)


class SummaryTest(unittest.TestCase):
    def _summarize(self, results, config=None):
        return summarize(results, config or BotConfig(), len(results), 10.0, 5.0)

    def test_without_samples_fields_are_null(self):
        """没开采集 → null。**不能是 0**，否则图上会出现一条"误差为零"的假线。"""
        summary = self._summarize([BotResult(), BotResult()])
        self.assertIsNone(summary["err_px_mean"])
        self.assertIsNone(summary["err_px_p95"])
        self.assertIsNone(summary["err_px_max"])
        self.assertEqual(summary["err_px_samples"], 0)

    def test_samples_are_merged_across_bots(self):
        first, second = BotResult(), BotResult()
        first.err_track.samples.extend([1.0, 3.0])
        second.err_track.samples.extend([5.0])

        summary = self._summarize([first, second])
        self.assertEqual(summary["err_px_samples"], 3)
        self.assertAlmostEqual(summary["err_px_mean"], 3.0, places=6)
        self.assertEqual(summary["err_px_max"], 5.0)

    def test_sim_loss_is_recorded(self):
        """条件必须写进汇总，否则以后拿到这批 JSON 不知道是什么丢包率下测的。"""
        summary = self._summarize([BotResult()], BotConfig(sim_loss=0.15))
        self.assertAlmostEqual(summary["sim_loss"], 0.15)

    def test_zero_sample_still_reports_sim_loss(self):
        summary = self._summarize([BotResult()], BotConfig(measure_err_px=True, sim_loss=0.0))
        self.assertEqual(summary["sim_loss"], 0.0)


if __name__ == "__main__":
    unittest.main()