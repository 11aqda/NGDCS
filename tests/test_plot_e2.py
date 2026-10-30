"""E2 出图（图 6-4 / 6-5 / 6-6）的测试。

重点不是"图好看不好看"，而是三件容易错的事：

1. **横轴是连接数**，不是实体数（E9 才是实体数）—— 认错档位名就会出空图
2. **RTT 只能从机器人汇总里取**（服务端 CSV 里没有），路径取不到时
   图 6-6 应当**跳过而不是画一张空图**
3. 多轮要**先平均再画**，否则同一个连接数会出现两个点
"""

import json
import tempfile
import unittest
from pathlib import Path

from tools.plot import (
    HAVE_MPL,
    load_e2_rtt,
    parse_e2_clients,
    plot_e2,
)


def make_point(clients: int, tick: float = 1.0, cpu: float = 2.0,
               mem: float = 50.0) -> dict:
    """造一个已经合并过多轮的档位汇总（`series` 元素的样子）。"""
    return {
        "level": f"E2-c{clients}",
        "scenario_id": f"E2-c{clients}",
        "players": clients,
        "enemies": 30,
        "bullets": 200,
        "entities": clients + 230,
        "tick_ms_avg": tick,
        "tick_ms_p95": tick * 1.2,
        "cpu_percent": cpu,
        "mem_mb": mem,
        "snapshot_bytes": 1927,
        "bw_per_client_bps": 1927 * 20,
        "runs": 2,
    }


class ParseClientsTest(unittest.TestCase):
    def test_e2_level(self):
        self.assertEqual(parse_e2_clients("E2-c10"), 10)
        self.assertEqual(parse_e2_clients("E2-c400"), 400)

    def test_other_experiments_are_rejected(self):
        for level in ("E9-e30-b200", "E1-e30-b200-json", "E2-probe", "c10"):
            self.assertIsNone(parse_e2_clients(level), level)

    def test_zero_is_allowed(self):
        self.assertEqual(parse_e2_clients("E2-c0"), 0)


class LoadRttTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, p50: float, p95: float, p99: float) -> None:
        (self.dir / f"{name}.json").write_text(
            json.dumps({"rtt_p50_ms": p50, "rtt_p95_ms": p95,
                        "rtt_p99_ms": p99, "interval_p50_ms": 50.0}),
            encoding="utf-8",
        )

    def test_averages_two_reps(self):
        self._write("E2-c10-r1", 1.0, 2.0, 4.0)
        self._write("E2-c10-r2", 3.0, 4.0, 8.0)
        rtt = load_e2_rtt(self.dir)
        self.assertEqual(rtt[10]["runs"], 2)
        self.assertAlmostEqual(rtt[10]["p50"], 2.0, places=3)
        self.assertAlmostEqual(rtt[10]["p99"], 6.0, places=3)

    def test_ignores_other_experiments(self):
        self._write("E2-c10-r1", 1.0, 2.0, 4.0)
        (self.dir / "E9-e30-b200-r1.json").write_text(
            json.dumps({"rtt_p50_ms": 99.0}), encoding="utf-8")
        rtt = load_e2_rtt(self.dir)
        self.assertEqual(set(rtt), {10})

    def test_missing_p99_is_tolerated(self):
        """老数据没有 p99（该字段是 2026-10-30 才加的），不能让整张图空掉。"""
        (self.dir / "E2-c10-r1.json").write_text(
            json.dumps({"rtt_p50_ms": 1.0, "rtt_p95_ms": 2.0}), encoding="utf-8")
        rtt = load_e2_rtt(self.dir)
        self.assertAlmostEqual(rtt[10]["p50"], 1.0, places=3)
        self.assertIsNone(rtt[10]["p99"])

    def test_broken_json_is_skipped(self):
        (self.dir / "E2-c10-r1.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(load_e2_rtt(self.dir), {})

    def test_empty_dir(self):
        self.assertEqual(load_e2_rtt(self.dir), {})


@unittest.skipUnless(HAVE_MPL, "需要 matplotlib")
class PlotE2Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "figs"
        self.runs = Path(self._tmp.name) / "runs"
        self.runs.mkdir(parents=True)
        for clients in (10, 50, 200):
            (self.runs / f"E2-c{clients}-r1.json").write_text(
                json.dumps({"rtt_p50_ms": 1.0, "rtt_p95_ms": 2.0,
                            "rtt_p99_ms": 5.0, "interval_p50_ms": 50.0}),
                encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_three_figures_written(self):
        series = [make_point(10), make_point(50), make_point(200, tick=3.0, cpu=9.0)]
        written = plot_e2(series, self.out, self.runs)
        names = {p.name for p in written}
        self.assertEqual(names, {
            "fig6-04-clients-vs-cpu-mem.png",
            "fig6-05-clients-vs-tick.png",
            "fig6-06-clients-vs-rtt.png",
        })
        for path in written:
            self.assertTrue(path.exists() and path.stat().st_size > 0, path)

    def test_unsorted_input_is_sorted(self):
        series = [make_point(200), make_point(10), make_point(50)]
        written = plot_e2(series, self.out, self.runs)
        self.assertEqual(len(written), 3)

    def test_rtt_figure_skipped_without_runs(self):
        """没有机器人汇总时，图 6-4/6-5 照出，图 6-6 跳过 —— 不画空图。"""
        empty = Path(self._tmp.name) / "no_runs"
        empty.mkdir()
        written = plot_e2([make_point(10)], self.out, empty)
        names = {p.name for p in written}
        self.assertNotIn("fig6-06-clients-vs-rtt.png", names)
        self.assertEqual(len(written), 2)

    def test_rejects_non_e2_data(self):
        with self.assertRaises(ValueError):
            plot_e2([{"level": "E9-e30-b200", "tick_ms_avg": 1.0}], self.out, self.runs)


if __name__ == "__main__":
    unittest.main()