"""指标 CSV 的表头迁移工具。

**为什么需要它**：`server_metrics.csv` 是**追加写**的（一次实验可能分段跑，不能覆盖），
而 `_open_for_append()` 只在「文件不存在或为空」时写表头 ——
所以一旦给 `METRICS_FIELDS` 加了新列，**已有文件的老表头不会更新**，
新行却按新字段数写出，于是**从新列往后整列错位**。

2026-10-26 就真的踩到了：加 `encode_ms` 时文件里已有 3312 行 E9 数据，
结果 E1 的 2194 行全部错位 —— 表头 22 列、数据 23 列。
`csv.DictWriter` 是按 `fieldnames` 顺序写值的，所以**盘上的值顺序是对的、只是缺个列名**，
本工具据此把文件修回来。

用法：

    # 先看会发生什么，不动文件
    .venv\\Scripts\\python.exe -X utf8 -m tools.migrate_metrics --dry-run

    # 确认后原地修复（会先备份成 .bak）
    .venv\\Scripts\\python.exe -X utf8 -m tools.migrate_metrics

**匹配是按列名、不是按位置**，所以它也能处理"列顺序调整"的情况。
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:  # 允许直接 `python tools/migrate_metrics.py`
    sys.path.insert(0, str(PROJECT_ROOT))

from server.metrics import METRICS_FIELDS  # noqa: E402

DEFAULT_CSV = PROJECT_ROOT / "data" / "server_metrics.csv"


def migrate_rows(
    old_fields: list[str], new_fields: list[str], rows: list[list[str]]
) -> tuple[list[list[str]], dict]:
    """把数据行统一到新字段表。

    - 字段数已等于新表头的行：原样保留（本次运行新写出的行就是这种）
    - 字段数等于旧表头的行：**按列名**映射到新字段，缺的新列补空字符串
    - 其他字段数：报错并指出是第几行 —— 不猜，猜错就是静默污染

    返回 `(新行列表, 统计)`。
    """
    old_count, new_count = len(old_fields), len(new_fields)
    stats = {"already_new": 0, "padded": 0, "padded_fields": {}}
    out: list[list[str]] = []

    for index, row in enumerate(rows, start=2):  # 第 1 行是表头
        if len(row) == new_count:
            out.append(list(row))
            stats["already_new"] += 1
        elif len(row) == old_count:
            by_name = dict(zip(old_fields, row))
            missing = [f for f in new_fields if f not in by_name]
            for field in missing:
                stats["padded_fields"][field] = stats["padded_fields"].get(field, 0) + 1
            out.append([by_name.get(field, "") for field in new_fields])
            stats["padded"] += 1
        else:
            raise ValueError(
                f"第 {index} 行有 {len(row)} 个字段，既不是旧表头的 {old_count} "
                f"也不是新表头的 {new_count} —— 停下来人工确认，别猜"
            )
    return out, stats


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        return header, list(reader)


def write_csv(path: Path, fields: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把指标 CSV 迁移到当前的 METRICS_FIELDS")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=None, help="输出到别的文件（默认原地）")
    parser.add_argument("--dry-run", action="store_true", help="只看结果，不写文件")
    parser.add_argument("--no-backup", action="store_true", help="原地修改时不备份")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.csv.exists():
        print(f"[migrate] 文件不存在：{args.csv}")
        raise SystemExit(1)

    old_fields, rows = read_csv(args.csv)
    print(f"[migrate] {args.csv}")
    print(f"  当前表头 {len(old_fields)} 列：" + ",".join(old_fields))
    print(f"  目标表头 {len(METRICS_FIELDS)} 列：" + ",".join(METRICS_FIELDS))

    if old_fields == list(METRICS_FIELDS):
        print("  ✓ 表头已是最新，无需迁移")
        return

    added = [f for f in METRICS_FIELDS if f not in old_fields]
    removed = [f for f in old_fields if f not in METRICS_FIELDS]
    if added:
        print(f"  新增列：{', '.join(added)}")
    if removed:
        print(f"  移除列：{', '.join(removed)} → 旧行的这些值会丢，确认这是你要的")

    new_rows, stats = migrate_rows(old_fields, list(METRICS_FIELDS), rows)
    print(f"  已是新格式 {stats['already_new']} 行；补齐 {stats['padded']} 行")
    for field, count in stats["padded_fields"].items():
        print(f"    补空值：{field} × {count} 行")

    if args.dry_run:
        print("  （--dry-run：没有写文件）")
        return

    target = args.out or args.csv
    if target == args.csv and not args.no_backup:
        backup = args.csv.with_suffix(args.csv.suffix + ".bak")
        shutil.copy2(args.csv, backup)
        print(f"  已备份 → {backup}")
    write_csv(target, list(METRICS_FIELDS), new_rows)
    print(f"  ✓ 已写出 {target}（{len(new_rows)} 行）")


if __name__ == "__main__":
    main()