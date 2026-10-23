"""指标落盘（server/metrics.py）的单元测试。

重点是 §4.3 的两条原则：**追加写不覆盖**、**每行带 scenario_id**。
"""

import csv
import tempfile
import unittest
from pathlib import Path

from server.metrics import (
    METRICS_FIELDS,
    SCENARIO_FIELDS,
    MetricsRecorder,
    cpu_percent_from_deltas,
    write_scenario,
)


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sample_stats(**overrides) -> dict:
    stats = {
        "ticks": 20,
        "avg_ms": 0.5,
        "p50_ms": 0.4,
        "p95_ms": 0.8,
        "max_ms": 1.2,
        "snapshot_bytes": 1939,
        "packets_in": 80,
        "bytes_in": 1040,
        "packets_out": 80,
        "bytes_out": 7804,
    }
    stats.update(overrides)
    return stats


class CpuPercentTest(unittest.TestCase):
    """单核占用 = ΔCPU 秒数 ÷ Δ墙钟秒数 × 100（100% = 一个核跑满）。"""

    def test_one_full_core(self):
        self.assertAlmostEqual(cpu_percent_from_deltas(1.0, 1.0), 100.0)

    def test_partial_core(self):
        # 一秒里花了 50 ms CPU：占单核 5%，量纲与 D-011 的「8.9% 单核」一致
        self.assertAlmostEqual(cpu_percent_from_deltas(0.05, 1.0), 5.0)

    def test_sixty_percent(self):
        self.assertAlmostEqual(cpu_percent_from_deltas(0.6, 1.0), 60.0)

    def test_scales_with_window(self):
        # 同样 0.1 秒 CPU，窗口越长百分比越低
        self.assertAlmostEqual(cpu_percent_from_deltas(0.1, 0.5), 20.0)
        self.assertAlmostEqual(cpu_percent_from_deltas(0.1, 2.0), 5.0)

    def test_zero_window_does_not_divide_by_zero(self):
        self.assertEqual(cpu_percent_from_deltas(0.1, 0.0), 0.0)


class MetricsRecorderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "server_metrics.csv"

    def make(self, scenario_id: str = "", **kwargs) -> MetricsRecorder:
        # 关掉 psutil 采样：窗口里的瞬时 CPU 值不可断言，只测「写得对不对」
        kwargs.setdefault("enable_process_stats", False)
        return MetricsRecorder(self.path, scenario_id=scenario_id, **kwargs)

    def test_writes_header_and_one_row(self):
        recorder = self.make("E9-e30-b200-01")
        recorder.write(client_count=4, enemies=30, bullets=200, stats=sample_stats())
        recorder.close()

        rows = read_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scenario_id"], "E9-e30-b200-01")
        self.assertEqual(rows[0]["client_count"], "4")
        self.assertEqual(rows[0]["enemies"], "30")
        self.assertEqual(rows[0]["bullets"], "200")
        self.assertEqual(rows[0]["tick_ms_avg"], "0.5")
        self.assertEqual(rows[0]["tick_ms_p95"], "0.8")
        self.assertEqual(rows[0]["snapshot_bytes"], "1939")
        self.assertEqual(rows[0]["bytes_out"], "7804")

    def test_header_matches_declared_fields(self):
        recorder = self.make()
        recorder.write(client_count=0, enemies=0, bullets=0, stats=sample_stats())
        recorder.close()

        with self.path.open(encoding="utf-8", newline="") as handle:
            header = handle.readline().strip().split(",")
        self.assertEqual(header, METRICS_FIELDS)

    def test_scenario_id_defaults_to_adhoc(self):
        # 随手跑一次也会写数据，用 adhoc 标记，出图时按 scenario 过滤掉
        recorder = self.make()
        self.assertEqual(recorder.scenario_id, "adhoc")
        recorder.close()

    def test_appends_instead_of_overwriting(self):
        # §4.3：一次实验可能分段跑，不能丢历史
        for _ in range(2):
            recorder = self.make("E9-e10-b50-01")
            recorder.write(
                client_count=4, enemies=10, bullets=50, stats=sample_stats()
            )
            recorder.close()

        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(text.count(",".join(METRICS_FIELDS)), 1)  # 表头只有一份
        self.assertEqual(len(read_rows(self.path)), 2)

    def test_t_mono_is_monotonic_and_non_negative(self):
        recorder = self.make()
        for _ in range(3):
            recorder.write(client_count=0, enemies=0, bullets=0, stats=sample_stats())
        recorder.close()

        times = [float(row["t_mono"]) for row in read_rows(self.path)]
        self.assertTrue(all(t >= 0 for t in times))
        self.assertEqual(times, sorted(times))

    def test_timestamp_is_wall_clock_iso(self):
        recorder = self.make()
        recorder.write(client_count=0, enemies=0, bullets=0, stats=sample_stats())
        recorder.close()

        stamp = read_rows(self.path)[0]["timestamp"]
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_creates_parent_directories(self):
        nested = Path(self._tmp.name) / "data" / "nested" / "m.csv"
        recorder = MetricsRecorder(nested, enable_process_stats=False)
        recorder.write(client_count=0, enemies=0, bullets=0, stats=sample_stats())
        recorder.close()
        self.assertTrue(nested.exists())

    def test_process_stats_columns_are_blank_when_disabled(self):
        # psutil 没装时 CPU / 内存留空，实验照跑不误
        recorder = self.make()
        recorder.write(client_count=0, enemies=0, bullets=0, stats=sample_stats())
        recorder.close()

        row = read_rows(self.path)[0]
        self.assertEqual(row["cpu_percent"], "")
        self.assertEqual(row["mem_mb"], "")


class ScenarioFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "server_scenario.csv"

    def test_writes_scenario_row(self):
        write_scenario(
            self.path, "E9-e30-b200-01", enemies=30, bullets=200, seed=1, tick_rate=20
        )

        rows = read_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scenario_id"], "E9-e30-b200-01")
        self.assertEqual(rows[0]["enemies"], "30")
        self.assertEqual(rows[0]["bullets"], "200")
        self.assertEqual(rows[0]["tick_rate"], "20")
        self.assertEqual(rows[0]["seed"], "1")
        # E1 / E4 / E5 才会填真实值，现在先把 schema 定下来
        self.assertEqual(rows[0]["encoder"], "binary")
        self.assertEqual(rows[0]["inject_loss"], "0.0")
        self.assertEqual(rows[0]["inject_delay"], "0.0")

    def test_header_matches_declared_fields(self):
        write_scenario(self.path, "x")
        with self.path.open(encoding="utf-8", newline="") as handle:
            header = handle.readline().strip().split(",")
        self.assertEqual(header, SCENARIO_FIELDS)

    def test_appends_multiple_scenarios(self):
        write_scenario(self.path, "E9-e10-b50-01", enemies=10, bullets=50)
        write_scenario(self.path, "E9-e20-b100-01", enemies=20, bullets=100)

        rows = read_rows(self.path)
        self.assertEqual([r["scenario_id"] for r in rows],
                         ["E9-e10-b50-01", "E9-e20-b100-01"])


if __name__ == "__main__":
    unittest.main()