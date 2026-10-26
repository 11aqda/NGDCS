"""表头迁移工具的测试。

背景：2026-10-26 给 `METRICS_FIELDS` 加 `encode_ms` 时，文件里已有 3312 行旧数据，
老表头没更新、新行却多一个值 → **2194 行整列错位，且没有任何报错**。
这个工具就是用来把那种文件修回来的，所以它自己必须可靠。
"""

import csv
import tempfile
import unittest
from pathlib import Path

from server.metrics import METRICS_FIELDS, MetricsSchemaError, _open_for_append
from tools.migrate_metrics import migrate_rows, read_csv, write_csv

OLD_FIELDS = ["timestamp", "t_mono", "scenario_id", "ser_ms", "hits"]
NEW_FIELDS = ["timestamp", "t_mono", "scenario_id", "ser_ms", "encode_ms", "hits"]


class MigrateRowsTest(unittest.TestCase):
    def test_old_rows_get_empty_value_for_new_column(self):
        rows = [["t1", "1.0", "s", "0.2", "5"]]
        out, stats = migrate_rows(OLD_FIELDS, NEW_FIELDS, rows)

        self.assertEqual(out, [["t1", "1.0", "s", "0.2", "", "5"]])
        self.assertEqual(stats["padded"], 1)
        self.assertEqual(stats["padded_fields"], {"encode_ms": 1})

    def test_new_rows_are_kept_as_is(self):
        rows = [["t1", "1.0", "s", "0.2", "0.05", "5"]]
        out, stats = migrate_rows(OLD_FIELDS, NEW_FIELDS, rows)

        self.assertEqual(out, rows)
        self.assertEqual(stats["already_new"], 1)
        self.assertEqual(stats["padded"], 0)

    def test_mixed_file_is_handled(self):
        # 真实情形：同一个文件里既有旧行也有新行
        rows = [
            ["t1", "1.0", "s", "0.2", "5"],            # 旧（5 列）
            ["t2", "2.0", "s", "0.3", "0.06", "7"],    # 新（6 列）
        ]
        out, stats = migrate_rows(OLD_FIELDS, NEW_FIELDS, rows)

        self.assertEqual(out[0], ["t1", "1.0", "s", "0.2", "", "5"])
        self.assertEqual(out[1], rows[1])
        self.assertEqual((stats["padded"], stats["already_new"]), (1, 1))

    def test_matching_is_by_name_not_position(self):
        # 列顺序调整也能处理：旧表的 ser_ms 在新表里排到后面去
        reordered = ["timestamp", "scenario_id", "t_mono", "hits", "encode_ms", "ser_ms"]
        rows = [["t1", "1.0", "s", "0.2", "5"]]  # 顺序按 OLD_FIELDS
        out, _ = migrate_rows(OLD_FIELDS, reordered, rows)

        self.assertEqual(out[0], ["t1", "s", "1.0", "5", "", "0.2"])

    def test_unexpected_column_count_raises(self):
        # 既不是旧表头也不是新表头 → 停下来人工确认，别猜
        with self.assertRaises(ValueError) as ctx:
            migrate_rows(OLD_FIELDS, NEW_FIELDS, [["a", "b", "c"]])
        self.assertIn("人工确认", str(ctx.exception))

    def test_error_message_names_the_row(self):
        rows = [["t1", "1.0", "s", "0.2", "5"], ["bad"]]
        with self.assertRaises(ValueError) as ctx:
            migrate_rows(OLD_FIELDS, NEW_FIELDS, rows)
        self.assertIn("第 3 行", str(ctx.exception))  # 第 1 行是表头

    def test_no_rows(self):
        out, stats = migrate_rows(OLD_FIELDS, NEW_FIELDS, [])
        self.assertEqual(out, [])
        self.assertEqual(stats["padded"], 0)

    def test_removed_column_is_dropped(self):
        # 新表没有的列，值会丢 —— 这是预期行为，靠 --dry-run 让人先看到
        rows = [["t1", "1.0", "s", "0.2", "5"]]
        out, _ = migrate_rows(OLD_FIELDS, ["timestamp", "scenario_id"], rows)
        self.assertEqual(out, [["t1", "s"]])


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_read_write_round_trip(self):
        path = self.dir / "m.csv"
        write_csv(path, NEW_FIELDS, [["a", "b", "c", "d", "e", "f"]])

        fields, rows = read_csv(path)
        self.assertEqual(fields, NEW_FIELDS)
        self.assertEqual(rows, [["a", "b", "c", "d", "e", "f"]])

    def test_empty_file(self):
        path = self.dir / "empty.csv"
        path.write_text("", encoding="utf-8")
        self.assertEqual(read_csv(path), ([], []))


class SchemaGuardTest(unittest.TestCase):
    """`_open_for_append` 必须拒绝表头不匹配的文件，而不是闷头追加。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "m.csv"

    def test_new_file_gets_current_header(self):
        handle, _ = _open_for_append(self.path, list(METRICS_FIELDS))
        handle.close()

        with self.path.open(encoding="utf-8", newline="") as fh:
            self.assertEqual(next(csv.reader(fh)), list(METRICS_FIELDS))

    def test_matching_header_is_accepted(self):
        self.path.write_text(",".join(METRICS_FIELDS) + "\n", encoding="utf-8")
        handle, _ = _open_for_append(self.path, list(METRICS_FIELDS))
        handle.close()

    def test_stale_header_is_rejected(self):
        # 2026-10-26 的真实事故：表头少一列，数据多一列 → 整列错位且不报错
        stale = [f for f in METRICS_FIELDS if f != "encode_ms"]
        self.path.write_text(",".join(stale) + "\n" + "x," * len(stale) + "\n", encoding="utf-8")

        with self.assertRaises(MetricsSchemaError) as ctx:
            _open_for_append(self.path, list(METRICS_FIELDS))

        message = str(ctx.exception)
        self.assertIn("encode_ms", message)
        self.assertIn("migrate_metrics", message, "报错必须告诉人怎么修")

    def test_error_mentions_both_column_counts(self):
        self.path.write_text("a,b\n1,2\n", encoding="utf-8")
        with self.assertRaises(MetricsSchemaError) as ctx:
            _open_for_append(self.path, list(METRICS_FIELDS))

        message = str(ctx.exception)
        self.assertIn("2 列", message)
        self.assertIn(f"{len(METRICS_FIELDS)} 列", message)

    def test_rejection_does_not_write_anything(self):
        stale = [f for f in METRICS_FIELDS if f != "encode_ms"]
        original = ",".join(stale) + "\n" + "x," * len(stale) + "\n"
        self.path.write_text(original, encoding="utf-8")

        with self.assertRaises(MetricsSchemaError):
            _open_for_append(self.path, list(METRICS_FIELDS))

        self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_migrated_file_is_accepted(self):
        # 迁移工具修过之后必须能正常追加 —— 两个模块要对接得上
        stale = [f for f in METRICS_FIELDS if f != "encode_ms"]
        rows = [["x"] * len(stale)]
        new_rows, _ = migrate_rows(stale, list(METRICS_FIELDS), rows)

        self.path.write_text(",".join(stale) + "\n", encoding="utf-8")
        write_csv(self.path, list(METRICS_FIELDS), new_rows)

        handle, _ = _open_for_append(self.path, list(METRICS_FIELDS))
        handle.close()


if __name__ == "__main__":
    unittest.main()