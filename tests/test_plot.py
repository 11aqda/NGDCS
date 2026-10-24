"""出图工具（tools/plot.py）的单元测试。

出图本身不好断言，所以重点测**可测的那部分**：CSV 解析、按场景切分、
丢热身窗口、每客户端带宽换算，最后再做一个「三张图真的写出来了」的冒烟测试。
"""

import csv
import tempfile
import unittest
from pathlib import Path

from server.metrics import METRICS_FIELDS
from tools.plot import (
    HAVE_MPL,
    group_by_scenario,
    load_rows,
    load_series,
    merge_runs,
    plot_e9,
    run_agreement,
    run_cpu_percent,
    split_scenario_id,
    summarize,
    summarize_runs,
)


def make_row(
    scenario_id: str,
    t_mono: float,
    *,
    enemies: int = 0,
    bullets: int = 0,
    clients: int = 4,
    tick_ms: float = 0.5,
    snapshot_bytes: int = 100,
    bytes_out: int = 2000,
    cpu_percent: float | None = 5.0,
) -> dict:
    """造一行**已经解析过**的数据 —— 形状与 load_rows() 的输出一致。

    写进 CSV 时 csv 模块会自己转成字符串；用来直接调 summarize() 时就是数字。

    四段默认按 1:6:2:1 分摊 tick_ms（碰撞占大头），
    这样它们的和**正好等于** tick_ms —— 和真实采集端的恒等式一致。
    """
    return {
        "timestamp": "2026-10-24T01:00:00",
        "t_mono": t_mono,
        "scenario_id": scenario_id,
        "client_count": clients,
        "enemies": enemies,
        "bullets": bullets,
        "tick_ms_avg": tick_ms,
        "tick_ms_p95": tick_ms * 1.5,
        "tick_ms_max": tick_ms * 2,
        "sim_ms": tick_ms * 0.1,
        "collision_ms": tick_ms * 0.6,
        "ser_ms": tick_ms * 0.2,
        "net_ms": tick_ms * 0.1,
        "hits": 0,
        "snapshot_bytes": snapshot_bytes,
        "cpu_percent": cpu_percent,
        # 累计 CPU 秒数：与 cpu_percent 自洽（整轮首尾差算出来正好等于 cpu_percent）
        "cpu_seconds": None if cpu_percent is None else t_mono * cpu_percent / 100.0,
        "mem_mb": 60.0,
        "packets_out": 80,
        "bytes_out": bytes_out,
        "packets_in": 80,
        "bytes_in": 1040,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=METRICS_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class LoadRowsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "m.csv"

    def test_parses_numbers(self):
        write_csv(self.path, [make_row("s1", 1.0, enemies=30, bullets=200)])
        row = load_rows(self.path)[0]

        self.assertEqual(row["scenario_id"], "s1")
        self.assertEqual(row["enemies"], 30.0)
        self.assertEqual(row["bullets"], 200.0)
        self.assertEqual(row["tick_ms_avg"], 0.5)
        self.assertIsInstance(row["t_mono"], float)

    def test_blank_numbers_become_none(self):
        # psutil 没装时 cpu_percent / mem_mb 是空字符串
        write_csv(self.path, [make_row("s1", 1.0, cpu_percent=None)])
        self.assertIsNone(load_rows(self.path)[0]["cpu_percent"])

    def test_blank_scenario_becomes_adhoc(self):
        row = make_row("", 1.0)
        write_csv(self.path, [row])
        self.assertEqual(load_rows(self.path)[0]["scenario_id"], "adhoc")


class SummarizeTest(unittest.TestCase):
    def test_warmup_rows_are_dropped(self):
        # 前 10 秒（进程刚起来、客户端没连满）不能算进去
        rows = [
            make_row("s1", float(t), tick_ms=10.0 if t < 10 else 2.0)
            for t in range(20)
        ]
        parsed = [
            {**row, "t_mono": float(row["t_mono"])} for row in rows
        ]
        summary = summarize(parsed, warmup_s=10.0)

        self.assertEqual(summary["rows"], 10)
        self.assertAlmostEqual(summary["tick_ms_avg"], 2.0)

    def test_warmup_longer_than_run_falls_back_to_all_rows(self):
        # 实验只有 3 秒，热身却要 10 秒：不能用空数据糊弄过去
        rows = [{**make_row("s1", float(t)), "t_mono": float(t)} for t in range(3)]
        summary = summarize(rows, warmup_s=10.0)
        self.assertEqual(summary["rows"], 3)

    def test_entity_total_includes_players(self):
        rows = [
            {**make_row("s1", float(t), enemies=30, bullets=200), "t_mono": float(t)}
            for t in range(5)
        ]
        summary = summarize(rows, warmup_s=0.0)
        self.assertEqual(summary["players"], 4.0)
        self.assertEqual(summary["entities"], 234.0)

    def test_bandwidth_is_per_client(self):
        # bytes_out 是「一份快照 × 收件人数」，除以客户端数才是每客户端带宽
        rows = [
            {
                **make_row("s1", float(t), clients=4, bytes_out=8000),
                "t_mono": float(t),
            }
            for t in range(5)
        ]
        summary = summarize(rows, warmup_s=0.0)
        self.assertAlmostEqual(summary["bw_per_client_bps"], 2000.0)

    def test_empty_rows(self):
        self.assertEqual(summarize([]), {})

    def test_logic_and_comms_are_split(self):
        # 用户的核心要求：碰撞（逻辑侧）与通信侧必须能分开看
        rows = [
            {**make_row("s1", float(t), tick_ms=10.0), "t_mono": float(t)}
            for t in range(5)
        ]
        summary = summarize(rows, warmup_s=0.0)

        self.assertAlmostEqual(summary["sim_ms"], 1.0, places=3)
        self.assertAlmostEqual(summary["collision_ms"], 6.0, places=3)
        self.assertAlmostEqual(summary["ser_ms"], 2.0, places=3)
        self.assertAlmostEqual(summary["net_ms"], 1.0, places=3)
        # 逻辑 = sim + collision = 7；通信 = ser + net = 3
        self.assertAlmostEqual(summary["logic_ms"], 7.0, places=3)
        self.assertAlmostEqual(summary["comms_ms"], 3.0, places=3)
        # 四段相加等于总耗时（堆叠图能画成 100% 的前提）
        self.assertAlmostEqual(summary["logic_ms"] + summary["comms_ms"], 10.0, places=3)

    def test_hits_are_summarized(self):
        rows = [
            {**make_row("s1", float(t)), "t_mono": float(t), "hits": 12}
            for t in range(4)
        ]
        self.assertAlmostEqual(summarize(rows, warmup_s=0.0)["hits"], 12.0)


class SeriesTest(unittest.TestCase):
    def test_groups_by_scenario(self):
        rows = [
            {**make_row("a", 0.0), "t_mono": 0.0},
            {**make_row("b", 0.0), "t_mono": 0.0},
            {**make_row("a", 1.0), "t_mono": 1.0},
        ]
        groups = group_by_scenario(rows)
        self.assertEqual(sorted(groups), ["a", "b"])
        self.assertEqual(len(groups["a"]), 2)

    def test_series_sorted_by_entity_count(self):
        # 画图的横轴顺序：实体数从小到大
        rows = [
            {**make_row("E9-e100-b800", 0.0, enemies=100, bullets=800), "t_mono": 0.0},
            {**make_row("E9-e10-b50", 0.0, enemies=10, bullets=50), "t_mono": 0.0},
        ]
        series, _ = load_series(rows, warmup_s=0.0)
        self.assertEqual([s["scenario_id"] for s in series], ["E9-e10-b50", "E9-e100-b800"])


class MultiRunTest(unittest.TestCase):
    """同一个档位跑多轮（`-rN` 后缀）。"""

    def test_split_without_suffix_is_run_one(self):
        self.assertEqual(split_scenario_id("E9-e30-b200"), ("E9-e30-b200", 1))

    def test_split_with_suffix(self):
        self.assertEqual(split_scenario_id("E9-e30-b200-r2"), ("E9-e30-b200", 2))
        self.assertEqual(split_scenario_id("E9-e250-b2000-r12"), ("E9-e250-b2000", 12))

    def test_only_trailing_suffix_counts(self):
        # 中间出现 -r 不算（避免把别人的命名习惯误判成轮次）
        self.assertEqual(split_scenario_id("E9-r5-e30"), ("E9-r5-e30", 1))

    def test_two_runs_stay_separate_before_merge(self):
        rows = [
            {**make_row("L-r1", float(t)), "t_mono": float(t)} for t in range(20)
        ] + [
            {**make_row("L-r2", float(t)), "t_mono": float(t)} for t in range(20)
        ]
        per_level = summarize_runs(group_by_scenario(rows), warmup_s=5.0)

        self.assertEqual(list(per_level), ["L"])
        self.assertEqual([r["run"] for r in per_level["L"]], [1, 2])
        # 每一轮各自丢热身：20 行 - 前 5 秒 = 15 行
        self.assertEqual([r["rows"] for r in per_level["L"]], [15, 15])

    def test_each_run_gets_its_own_warmup(self):
        """关键点：t_mono 每轮都从 0 开始，两轮必须各自丢热身。

        第 1 轮全程 1.0 ms；第 2 轮前 10 秒是 9.0 ms（不稳定）后面是 1.0 ms。
        如果两轮混在一起丢热身，第 2 轮那段 9.0 会被算进去 → 均值被拉高。
        """
        rows = [
            {**make_row("L-r1", float(t), tick_ms=1.0), "t_mono": float(t)}
            for t in range(20)
        ] + [
            {
                **make_row("L-r2", float(t), tick_ms=9.0 if t < 10 else 1.0),
                "t_mono": float(t),
            }
            for t in range(20)
        ]
        per_level = summarize_runs(group_by_scenario(rows), warmup_s=10.0)

        first, second = per_level["L"]
        self.assertAlmostEqual(first["tick_ms_avg"], 1.0, places=3)
        self.assertAlmostEqual(second["tick_ms_avg"], 1.0, places=3)

    def test_merge_averages_numeric_fields(self):
        merged = merge_runs(
            [
                {"level": "L", "run": 1, "entities": 234.0, "tick_ms_avg": 1.0, "hits": 10.0},
                {"level": "L", "run": 2, "entities": 234.0, "tick_ms_avg": 3.0, "hits": 20.0},
            ]
        )
        self.assertAlmostEqual(merged["tick_ms_avg"], 2.0)
        self.assertAlmostEqual(merged["hits"], 15.0)
        self.assertEqual(merged["runs"], 2)
        self.assertEqual(merged["scenario_id"], "L")  # 图上不带 -rN

    def test_merge_empty(self):
        self.assertEqual(merge_runs([]), {})

    def test_one_point_per_level(self):
        rows = []
        for level, enemies, bullets in (("L1", 10, 50), ("L2", 30, 200)):
            for run in (1, 2):
                for t in range(10):
                    rows.append(
                        {
                            **make_row(
                                f"{level}-r{run}",
                                float(t),
                                enemies=enemies,
                                bullets=bullets,
                            ),
                            "t_mono": float(t),
                        }
                    )
        series, per_level = load_series(rows, warmup_s=0.0)

        self.assertEqual(len(series), 2)  # 两个档位 = 两个点，不是四个
        self.assertEqual([s["scenario_id"] for s in series], ["L1", "L2"])
        self.assertTrue(all(s["runs"] == 2 for s in series))
        self.assertEqual(len(per_level["L1"]), 2)  # 但每轮的汇总都留着

    def test_agreement_zero_for_identical_runs(self):
        runs = [{"tick_ms_avg": 2.0}, {"tick_ms_avg": 2.0}]
        self.assertAlmostEqual(run_agreement(runs), 0.0)

    def test_agreement_reports_max_relative_gap(self):
        # 均值 2.0，两轮分别是 1.8 / 2.2 → 最大偏差 0.2/2.0 = 10%
        runs = [{"tick_ms_avg": 1.8}, {"tick_ms_avg": 2.2}]
        self.assertAlmostEqual(run_agreement(runs), 10.0)

    def test_agreement_needs_two_runs(self):
        self.assertEqual(run_agreement([{"tick_ms_avg": 2.0}]), 0.0)
        self.assertEqual(run_agreement([]), 0.0)

    def test_agreement_handles_zero_mean(self):
        self.assertEqual(run_agreement([{"tick_ms_avg": 0.0}, {"tick_ms_avg": 0.0}]), 0.0)


class RunCpuTest(unittest.TestCase):
    """整轮 CPU% 用「累计 CPU 秒数首尾差 ÷ 墙钟首尾差」算。

    起因（2026-10-25 实测）：低负载下逐秒 `cpu_percent` 被调度计时粒度量化，
    同一档位两轮的逐秒均值能差到 66%（2.6% vs 0.5%）。
    """

    def test_exact_from_cumulative(self):
        rows = [
            {**make_row("L", 0.0, cpu_percent=5.0), "t_mono": 0.0},
            {**make_row("L", 1.0, cpu_percent=5.0), "t_mono": 1.0},
            {**make_row("L", 2.0, cpu_percent=5.0), "t_mono": 2.0},
        ]
        self.assertAlmostEqual(run_cpu_percent(rows), 5.0, places=3)

    def test_ignores_the_noisy_per_row_column(self):
        """逐秒列被量化得很乱，累计列是干净的 —— 应当以累计列为准。"""
        rows = [
            {"t_mono": 0.0, "cpu_seconds": 0.000, "cpu_percent": 99.0},
            {"t_mono": 1.0, "cpu_seconds": 0.010, "cpu_percent": 0.0},
            {"t_mono": 2.0, "cpu_seconds": 0.021, "cpu_percent": 0.0},
            {"t_mono": 3.0, "cpu_seconds": 0.031, "cpu_percent": 1.56},
        ]
        # 整轮：0.031 s / 3 s = 1.03%；而逐秒均值是 (99+0+0+1.56)/4 = 25.1%
        self.assertAlmostEqual(run_cpu_percent(rows), 1.033, places=2)
        self.assertGreater(
            sum(r["cpu_percent"] for r in rows) / len(rows),
            20.0,
            "构造的逐秒数据本就该很离谱，否则这条测试没有意义",
        )

    def test_missing_cumulative_column_falls_back(self):
        # 旧 CSV（没有 cpu_seconds 列）→ 返回 0，由 summarize 退回逐秒均值
        rows = [{"t_mono": 0.0, "cpu_percent": 7.0}, {"t_mono": 1.0, "cpu_percent": 7.0}]
        self.assertEqual(run_cpu_percent(rows), 0.0)

        summary = summarize(
            [{**make_row("L", float(t)), "t_mono": float(t), "cpu_seconds": None}
             for t in range(3)],
            warmup_s=0.0,
        )
        self.assertAlmostEqual(summary["cpu_percent"], 5.0, places=3)

    def test_needs_at_least_two_points(self):
        self.assertEqual(run_cpu_percent([{"t_mono": 0.0, "cpu_seconds": 0.0}]), 0.0)
        self.assertEqual(run_cpu_percent([]), 0.0)

    def test_zero_time_span(self):
        rows = [
            {"t_mono": 1.0, "cpu_seconds": 0.0},
            {"t_mono": 1.0, "cpu_seconds": 0.5},
        ]
        self.assertEqual(run_cpu_percent(rows), 0.0)


@unittest.skipUnless(HAVE_MPL, "需要 matplotlib")
class PlotSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.csv_path = self.dir / "server_metrics.csv"
        self.out_dir = self.dir / "figures"

    def test_writes_four_figures(self):
        rows = []
        for scenario_id, enemies, bullets in (
            ("E9-e10-b50", 10, 50),
            ("E9-e30-b200", 30, 200),
            ("E9-e100-b800", 100, 800),
        ):
            for t in range(15):
                rows.append(
                    {
                        **make_row(
                            scenario_id,
                            float(t),
                            enemies=enemies,
                            bullets=bullets,
                            tick_ms=0.2 + enemies * 0.02,
                            snapshot_bytes=894 + enemies * 9 + bullets * 8,
                            bytes_out=20000,
                        ),
                        "t_mono": float(t),
                    }
                )
        write_csv(self.csv_path, rows)

        series, _ = load_series(load_rows(self.csv_path), 10.0)
        written = plot_e9(series, self.out_dir)

        self.assertEqual(len(written), 4)
        names = {path.name for path in written}
        self.assertIn("fig6-17-entities-vs-tick.png", names)
        self.assertIn("fig6-20-time-composition.png", names)
        for path in written:
            self.assertTrue(path.exists(), path)
            self.assertGreater(path.stat().st_size, 0, path)
            self.assertEqual(path.suffix, ".png")

    def test_empty_series_raises(self):
        with self.assertRaises(ValueError):
            plot_e9([], self.out_dir)


if __name__ == "__main__":
    unittest.main()