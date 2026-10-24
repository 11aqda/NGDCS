"""tick 统计窗口（E9 的数据源）的单元测试。

2026-10-25 起 tick 按四个阶段拆解，这里最要紧的一条是
`test_phases_sum_to_total` —— 四段严格相加等于总耗时，
是图 6-20 能画成 100% 堆叠的前提。
"""

import unittest

from server.stats import (
    COMMS_PHASES,
    LOGIC_PHASES,
    PHASE_LABELS,
    PHASES,
    TickStats,
    percentile,
)


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


class PhaseTest(unittest.TestCase):
    """四段拆解：sim / collision / ser / net。"""

    def test_phase_constants_are_consistent(self):
        self.assertEqual(set(LOGIC_PHASES) | set(COMMS_PHASES), set(PHASES))
        self.assertEqual(set(PHASE_LABELS), set(PHASES))
        # 逻辑侧和通信侧不能有重叠，否则堆叠图会算两遍
        self.assertEqual(set(LOGIC_PHASES) & set(COMMS_PHASES), set())

    def test_each_phase_is_averaged_over_its_own_count(self):
        stats = TickStats()
        stats.record_phase("sim", 0.001)
        stats.record_phase("sim", 0.003)  # 平均 2 ms
        stats.record_phase("collision", 0.010)  # 只有一次 → 10 ms

        result = stats.flush()
        self.assertAlmostEqual(result["sim_ms"], 2.0, places=3)
        self.assertAlmostEqual(result["collision_ms"], 10.0, places=3)
        self.assertEqual(result["ser_ms"], 0.0)
        self.assertEqual(result["net_ms"], 0.0)

    def test_phases_sum_to_total(self):
        # 计时点首尾相接（started→sim→collision→ser→net），
        # 所以四段之和**严格等于**总耗时，堆叠图不存在「其它」那一块
        stats = TickStats()
        stats.record_tick(0.020)
        stats.record_phase("sim", 0.005)
        stats.record_phase("collision", 0.012)
        stats.record_phase("ser", 0.002)
        stats.record_phase("net", 0.001)

        result = stats.flush()
        self.assertAlmostEqual(
            sum(result[f"{phase}_ms"] for phase in PHASES),
            result["avg_ms"],
            places=3,
        )

    def test_unknown_phase_is_rejected(self):
        # 拼错阶段名必须立刻炸，否则那一秒的数据会静默丢失
        with self.assertRaises(ValueError):
            TickStats().record_phase("collison", 0.001)  # 故意拼错

    def test_collision_and_comms_are_separable(self):
        # 用户的核心要求：碰撞耗时与通信耗时必须能分开看出来
        stats = TickStats()
        stats.record_tick(0.020)
        stats.record_phase("sim", 0.002)
        stats.record_phase("collision", 0.015)
        stats.record_phase("ser", 0.002)
        stats.record_phase("net", 0.001)

        result = stats.flush()
        logic = sum(result[f"{p}_ms"] for p in LOGIC_PHASES)
        comms = sum(result[f"{p}_ms"] for p in COMMS_PHASES)

        self.assertAlmostEqual(logic, 17.0, places=3)
        self.assertAlmostEqual(comms, 3.0, places=3)
        self.assertGreater(result["collision_ms"], comms)  # 这次瓶颈在逻辑侧


class HitsTest(unittest.TestCase):
    def test_hits_accumulate_within_the_window(self):
        stats = TickStats()
        stats.record_hits(3)
        stats.record_hits(0)
        stats.record_hits(7)
        self.assertEqual(stats.flush()["hits"], 10)

    def test_hits_cleared_on_flush(self):
        stats = TickStats()
        stats.record_hits(5)
        stats.flush()
        self.assertEqual(stats.flush()["hits"], 0)

    def test_phases_cleared_on_flush(self):
        stats = TickStats()
        stats.record_phase("collision", 0.01)
        stats.flush()

        second = stats.flush()
        for phase in PHASES:
            self.assertEqual(second[f"{phase}_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()