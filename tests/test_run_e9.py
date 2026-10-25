"""E9 运行器（tools/run_e9.py）的单元测试。

跑批脚本本身也要可信：实验条件一旦写错，18 轮数据的可比性就没了，
而且**不会报错** —— 只会让第 7 轮和第 13 轮的参数悄悄不一致。
所以命令拼装、档位解析、命名约定、采集校验这几件事都单独测。
"""

import tempfile
import unittest
from pathlib import Path

from tools.run_e9 import (
    DEFAULT_LEVELS,
    build_bot_cmd,
    build_server_cmd,
    count_rows,
    format_percent,
    parse_levels,
    scenario_name,
)


class FakeArgs:
    port = 9527
    clients = 4
    duration = 180.0
    ramp = 4.0
    seed = 1
    bot_seed = 99
    metrics = Path("data/server_metrics.csv")


class NamingTest(unittest.TestCase):
    def test_scenario_name_pattern(self):
        # tools/plot.py 靠 `-rN` 后缀解析轮次，命名不能随意改
        self.assertEqual(scenario_name("E9", 30, 200, 2), "E9-e30-b200-r2")
        self.assertEqual(scenario_name("E9", 250, 2000, 1), "E9-e250-b2000-r1")

    def test_default_levels_are_ascending(self):
        # 横轴顺序靠实体总数排序，档位表本身也应当是递增的
        totals = [e + b for e, b in DEFAULT_LEVELS]
        self.assertEqual(totals, sorted(totals))

    def test_default_levels_include_the_documented_six(self):
        # 03-实验清单 §8 原本定的 6 档必须还在（追加不等于替换）
        documented = {(10, 50), (20, 100), (30, 200), (50, 400), (80, 600), (100, 800)}
        self.assertTrue(documented.issubset(set(DEFAULT_LEVELS)))

    def test_enemy_count_fits_uint8(self):
        # enemy_count 在快照头里是 uint8，超过 255 会在编码时炸
        self.assertTrue(all(enemies <= 0xFF for enemies, _ in DEFAULT_LEVELS))


class ParseLevelsTest(unittest.TestCase):
    def test_single(self):
        self.assertEqual(parse_levels("30/200"), ((30, 200),))

    def test_multiple_with_spaces(self):
        self.assertEqual(
            parse_levels(" 30/200 , 100/800 "), ((30, 200), (100, 800))
        )

    def test_ignores_empty_chunks(self):
        self.assertEqual(parse_levels("30/200,,"), ((30, 200),))

    def test_missing_slash_is_rejected(self):
        # 写错格式必须立刻炸，不能默默跑出一个错误档位
        with self.assertRaises(ValueError):
            parse_levels("30-200")

    def test_non_numeric_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_levels("三十/200")


class CommandTest(unittest.TestCase):
    def test_server_cmd_carries_e9_controls(self):
        cmd = build_server_cmd(FakeArgs(), 30, 200, "E9-e30-b200-r1")

        self.assertIn("-m", cmd)
        self.assertIn("server.main", cmd)
        for flag, value in (
            ("--enemies", "30"),
            ("--bullets", "200"),
            ("--scenario", "E9-e30-b200-r1"),
            ("--seed", "1"),
        ):
            self.assertIn(flag, cmd, flag)
            self.assertEqual(cmd[cmd.index(flag) + 1], value, flag)

    def test_bot_cmd_carries_control_variables(self):
        cmd = build_bot_cmd(FakeArgs(), "E9-e30-b200-r1", Path("out.json"))

        for flag, value in (
            ("--clients", "4"),
            ("--duration", "180.0"),
            ("--ramp", "4.0"),
            ("--seed", "99"),
        ):
            self.assertIn(flag, cmd, flag)
            self.assertEqual(cmd[cmd.index(flag) + 1], value, flag)

    def test_bot_cmd_writes_clean_json(self):
        # 用 --out 让机器人写干净 JSON，而不是从日志里抠
        cmd = build_bot_cmd(FakeArgs(), "x", Path("data/runs/x.json"))
        self.assertEqual(cmd[cmd.index("--out") + 1], str(Path("data/runs/x.json")))

    def test_commands_use_the_same_interpreter(self):
        # 必须用当前解释器（venv），否则会跑到系统 Python 上去
        import sys

        self.assertEqual(build_server_cmd(FakeArgs(), 1, 1, "x")[0], sys.executable)
        self.assertEqual(build_bot_cmd(FakeArgs(), "x", Path("o"))[0], sys.executable)


class CountRowsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "m.csv"

    def test_counts_only_the_matching_scenario(self):
        self.path.write_text(
            "timestamp,t_mono,scenario_id,enemies\n"
            "2026-10-25T00:00:00,1.0,E9-e30-b200-r1,30\n"
            "2026-10-25T00:00:01,2.0,E9-e30-b200-r1,30\n"
            "2026-10-25T00:00:02,3.0,E9-e100-b800-r1,100\n",
            encoding="utf-8",
        )
        self.assertEqual(count_rows(self.path, "E9-e30-b200-r1"), 2)
        self.assertEqual(count_rows(self.path, "E9-e100-b800-r1"), 1)

    def test_does_not_confuse_r1_with_r10(self):
        # 前缀相同但轮次不同：不能把 r10 算进 r1
        self.path.write_text(
            "scenario_id,enemies\n"
            "E9-e30-b200-r1,30\n"
            "E9-e30-b200-r10,30\n",
            encoding="utf-8",
        )
        self.assertEqual(count_rows(self.path, "E9-e30-b200-r1"), 1)

    def test_missing_file_is_zero(self):
        self.assertEqual(count_rows(Path(self._tmp.name) / "nope.csv", "x"), 0)


class FormatTest(unittest.TestCase):
    def test_percent(self):
        self.assertEqual(format_percent(5.43), "5.4%")

    def test_none_is_na(self):
        # 没装 psutil 时整机 CPU 采不到，不能显示成 0%
        self.assertEqual(format_percent(None), "n/a")


if __name__ == "__main__":
    unittest.main()