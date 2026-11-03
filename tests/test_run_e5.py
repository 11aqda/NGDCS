"""E5 工具链的测试：汇总口径 + 场景名解析。

## 测试重点

`summarize()` 是 E5 出数的唯一入口，它必须：
1. **只统计满负载的行** —— 服务端一启动就写指标，前几秒没客户端，
   那些行的 `bytes_out` 只有心跳没有快照，混进来会把带宽拉低
2. **丢掉预热段** —— 进程刚起来、JIT/缓存没热
3. **带宽用 `bytes_out`**（服务端发给所有人的总字节），不是单客户端的
4. **CPU 用首尾差**，不是逐行均值（低负载下逐行值被计时粒度量化）
"""

import unittest

from tools.plot import parse_e5_hz
from tools.run_e5 import FIXED_PLAYERS, scenario_name, summarize


def _row(t_mono: float, client_count: int, bytes_out: float,
         tick_ms: float = 1.0, cpu_seconds: float = 0.0,
         snapshot_bytes: float = 1927.0, packets_out: float = 20.0) -> dict:
    return {
        "t_mono": str(t_mono),
        "client_count": str(client_count),
        "bytes_out": str(bytes_out),
        "tick_ms_avg": str(tick_ms),
        "cpu_seconds": str(cpu_seconds),
        "snapshot_bytes": str(snapshot_bytes),
        "packets_out": str(packets_out),
    }


class ScenarioNameTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(scenario_name(10, 1), "E5-h10-r1")
        self.assertEqual(scenario_name(30, 2), "E5-h30-r2")

    def test_parse_round_trip(self):
        for hz in (10, 15, 20, 30):
            name = scenario_name(hz, 1)
            # 去掉 -rN 后缀后要能被 parse_e5_hz 认出来
            self.assertEqual(parse_e5_hz(name.rsplit("-r", 1)[0]), hz)

    def test_does_not_match_other_experiments(self):
        for name in ("E2-c10", "E9-e30-b200", "E1-e30-b200-json", "E5-", "h20"):
            self.assertIsNone(parse_e5_hz(name), name)


class SummarizeTest(unittest.TestCase):
    def test_drops_rows_without_full_players(self):
        """**关键**：没连满的行不能算进带宽均值。"""
        rows = [_row(t, 0, 1000.0) for t in range(5)]           # 空转
        rows += [_row(10 + t, FIXED_PLAYERS, 200_000.0) for t in range(30)]
        result = summarize(rows, tick_hz=20)
        self.assertAlmostEqual(result["bandwidth_bps"], 200_000.0, places=0)

    def test_drops_warmup_seconds(self):
        """预热段（刚连满、还在爬坡）要被丢掉。"""
        # 前 20 秒带宽低（爬坡），后面稳定
        rows = [_row(100 + t, FIXED_PLAYERS, 50_000.0) for t in range(20)]
        rows += [_row(120 + t, FIXED_PLAYERS, 200_000.0) for t in range(60)]
        result = summarize(rows, tick_hz=20)
        self.assertGreater(result["bandwidth_bps"], 150_000.0)

    def test_bandwidth_in_kbps(self):
        rows = [_row(10 + t, FIXED_PLAYERS, 102_400.0) for t in range(40)]
        result = summarize(rows, tick_hz=20)
        self.assertAlmostEqual(result["bandwidth_kbps"], 100.0, places=1)

    def test_cpu_uses_first_last_difference(self):
        """CPU 口径：首尾 cpu_seconds 差 ÷ 墙钟秒。"""
        # 40 秒里烧了 2 秒 CPU → 5%
        rows = [
            _row(10 + t, FIXED_PLAYERS, 100_000.0,
                 cpu_seconds=10.0 + (2.0 * t / 39.0))
            for t in range(40)
        ]
        result = summarize(rows, tick_hz=20)
        self.assertAlmostEqual(result["cpu_percent"], 5.0, delta=0.3)

    def test_budget_used_scales_with_rate(self):
        """同样的 1 ms tick，10 Hz 只吃 1% 预算，30 Hz 吃 3%。"""
        rows = [_row(10 + t, FIXED_PLAYERS, 100_000.0, tick_ms=1.0) for t in range(40)]
        self.assertAlmostEqual(summarize(rows, 10)["budget_used_percent"], 1.0, places=1)
        self.assertAlmostEqual(summarize(rows, 30)["budget_used_percent"], 3.0, places=1)

    def test_tick_p95_present(self):
        rows = [_row(10 + t, FIXED_PLAYERS, 100_000.0, tick_ms=1.0 + t * 0.01)
                for t in range(40)]
        result = summarize(rows, tick_hz=20)
        self.assertGreaterEqual(result["tick_p95_ms"], result["tick_mean_ms"])

    def test_empty_input_is_soft(self):
        """没有可用行时不能崩，要能给出可读的原因。"""
        result = summarize([], tick_hz=20)
        self.assertEqual(result["windows"], 0)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()