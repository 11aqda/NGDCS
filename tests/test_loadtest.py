"""E2 跑批脚本的纯函数测试。

`tools/loadtest.py` 里真正会出错的不是"起进程"，而是三处判据：

1. **场景命名** —— 末尾必须是 `-r<数字>`，否则 `tools/plot.py` 解析不出轮次
2. **失败判定与归因** —— 把"服务端崩"和"机器人崩"混为一谈，结论就写反了
3. **档位规划** —— 加档上限、只听指定档

这些都不需要真起服务端，所以用构造的行数据直接测。
"""

import unittest

from tools.loadtest import (
    CONSECUTIVE_BAD_WINDOWS,
    DEFAULT_TIERS,
    DEVIATION_LIMIT,
    EXTEND_TIERS,
    FIXED_BULLETS,
    FIXED_ENEMIES,
    TICK_BUDGET_MS,
    analyze,
    detect_affinity,
    plan_tiers,
    ramp_for,
    scenario_name,
)


def row(tick_ms: float, cpu: float = 10.0, t_mono: float = 0.0,
        cpu_seconds: float = 0.0) -> dict:
    return {
        "tick_ms_avg": str(tick_ms),
        "cpu_percent": str(cpu),
        "cpu_seconds": str(cpu_seconds),
        "t_mono": str(t_mono),
    }


class Namespace:
    """够 plan_tiers 用的最小 args。"""

    def __init__(self, tiers: str = "", max_tier: int = 400) -> None:
        self.tiers = tiers
        self.max_tier = max_tier


class ScenarioNameTest(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(scenario_name(10, 2), "E2-c10-r2")

    def test_ends_with_rep_suffix(self):
        """`plot.py` 用 `-r(\\d+)$` 抓轮次，后缀必须在最后。"""
        self.assertRegex(scenario_name(400, 1), r"-r(\d+)$")

    def test_tiers_are_distinguishable(self):
        names = {scenario_name(c, 1) for c in (10, 20, 100, 200)}
        self.assertEqual(len(names), 4)


class RampTest(unittest.TestCase):
    def test_small_tier_has_floor(self):
        """小档位不能因为 ramp 太小拖长连接时间。"""
        self.assertEqual(ramp_for(10), 10)

    def test_large_tier_connects_within_five_seconds(self):
        for clients in (100, 200, 400):
            self.assertGreaterEqual(ramp_for(clients) * 5, clients)

    def test_monotonic(self):
        values = [ramp_for(c) for c in (10, 20, 50, 100, 200, 400)]
        self.assertEqual(values, sorted(values))


class PlanTiersTest(unittest.TestCase):
    def test_default_escalates_until_max(self):
        self.assertEqual(plan_tiers(Namespace()),
                         list(DEFAULT_TIERS) + list(EXTEND_TIERS))

    def test_max_tier_truncates(self):
        self.assertEqual(plan_tiers(Namespace(max_tier=200)), list(DEFAULT_TIERS))

    def test_explicit_tiers_win(self):
        self.assertEqual(plan_tiers(Namespace(tiers="10,20")), [10, 20])


class AnalyzeTest(unittest.TestCase):
    def _good_rows(self, n: int = 10) -> list[dict]:
        return [row(1.0, cpu=2.0, t_mono=i, cpu_seconds=i * 0.02) for i in range(n)]

    def _good_summary(self, clients: int) -> dict:
        return {"clients_connected": clients, "errors": 0}

    def test_healthy_run_passes(self):
        result = analyze(self._good_rows(), self._good_summary(10), 10)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["blame"], "")
        self.assertAlmostEqual(result["tick_mean_ms"], 1.0, places=3)

    def test_consecutive_over_budget_blames_server(self):
        """连续 3 个窗口超预算 → 服务端先崩。**单次超预算不算**。"""
        rows = self._good_rows() + [row(TICK_BUDGET_MS + 1)] * CONSECUTIVE_BAD_WINDOWS
        result = analyze(rows, self._good_summary(10), 10)
        self.assertEqual(result["blame"], "server")
        self.assertEqual(result["bad_run"], CONSECUTIVE_BAD_WINDOWS)
        self.assertTrue(any("服务端" in r for r in result["reasons"]))

    def test_isolated_spikes_do_not_fail(self):
        """零星尖刺不该判失败 —— 要连续，否则一次 GC 抖动就毁掉整档。"""
        rows = []
        for i in range(10):
            rows.append(row(TICK_BUDGET_MS + 5 if i % 3 == 0 else 1.0))
        result = analyze(rows, self._good_summary(10), 10)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["bad_run"], 1)

    def test_missing_clients_blames_bot(self):
        result = analyze(self._good_rows(), {"clients_connected": 7, "errors": 0}, 10)
        self.assertEqual(result["blame"], "bot")
        self.assertTrue(any("客户端" in r for r in result["reasons"]))

    def test_bot_errors_blame_bot(self):
        result = analyze(self._good_rows(), {"clients_connected": 10, "errors": 3}, 10)
        self.assertEqual(result["blame"], "bot")

    def test_both_sides_bad(self):
        rows = [row(TICK_BUDGET_MS + 10)] * CONSECUTIVE_BAD_WINDOWS
        result = analyze(rows, {"clients_connected": 1, "errors": 2}, 10)
        self.assertEqual(result["blame"], "both")

    def test_no_bot_summary_is_a_failure(self):
        result = analyze(self._good_rows(), None, 10)
        self.assertTrue(result["reasons"])
        self.assertTrue(any("汇总文件" in r for r in result["reasons"]))

    def test_cpu_falls_back_to_cumulative_seconds(self):
        """低负载时逐行 cpu_percent 不可靠，要能用 cpu_seconds 首尾差重算。"""
        rows = [row(1.0, cpu=float("nan"), t_mono=0, cpu_seconds=5.0),
                row(1.0, cpu=float("nan"), t_mono=100, cpu_seconds=15.0)]
        for r in rows:
            r["cpu_percent"] = ""  # 模拟该列为空
        result = analyze(rows, self._good_summary(10), 10)
        self.assertAlmostEqual(result["cpu_percent"], 10.0, places=1)

    def test_p95_reported(self):
        rows = [row(v) for v in range(1, 21)]
        result = analyze(rows, self._good_summary(10), 10)
        self.assertIsNotNone(result["tick_p95_ms"])
        self.assertLessEqual(result["tick_p95_ms"], 20)


class AffinityTest(unittest.TestCase):
    def test_server_and_bots_are_disjoint(self):
        server, bots = detect_affinity()
        self.assertTrue(server and bots)
        self.assertFalse(set(server) & set(bots))

    def test_server_gets_one_physical_core(self):
        """服务端最多 2 个逻辑核（= 1 个物理核在超线程下的两个线程）。"""
        server, _ = detect_affinity()
        self.assertLessEqual(len(server), 2)

    def test_bots_get_the_rest(self):
        server, bots = detect_affinity()
        import psutil

        self.assertEqual(len(server) + len(bots), len(psutil.Process().cpu_affinity()))


class ConstantsTest(unittest.TestCase):
    def test_entities_match_e9_target_tier(self):
        """D-029：实体固定为 E9 目标档，两套实验才可比。"""
        self.assertEqual((FIXED_ENEMIES, FIXED_BULLETS), (30, 200))

    def test_deviation_limit(self):
        self.assertAlmostEqual(DEVIATION_LIMIT, 0.10)


if __name__ == "__main__":
    unittest.main()