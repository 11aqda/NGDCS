"""读指标 CSV 出图 —— E9 的图 6-17 / 6-18 / 6-19。

E9 是「实体数 → 带宽 / CPU」的核心实验（`03-实验清单.md §5`），
这三张图直接支撑「同屏敌机上限 = 30、子弹上限 = 300」这个设计决策（D-011），
构成「设计 → 实测 → 反推约束」的闭环。

数据来自 `server/metrics.py` 每秒写一行的 CSV。用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.plot --csv data/server_metrics.csv --out docs/figures

两个容易踩的坑，这里都处理了：

1. **matplotlib 默认画不了中文** —— 不设字体的话标题全是方块。
2. **开头的几十秒不能要** —— 进程刚起来、客户端还没连满、缓存没热，
   这一段会把均值拉偏。所以默认丢掉每个场景**开头 10 秒**（`--warmup`）。
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

# ⚠️ 必须在 import matplotlib **之前**设好缓存目录。
# matplotlib 默认把字体缓存写到 C:\Users\<用户>\AppData\Local\matplotlib；
# 那个目录在开发机上不可写，它就会退而在**当前工作目录**建一个 matplotlib-xxxx
# 临时目录 —— 等于往仓库根目录拉屎，每次跑还重新建一次、导入慢好几秒。
# 显式指到项目内的 .cache/（已在 .gitignore 里）。
_MPL_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "matplotlib"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))

try:
    import matplotlib

    matplotlib.use("Agg")  # 无窗口后端：没有桌面 / 在后台也能出图
    import matplotlib.pyplot as plt

    HAVE_MPL = True
except ImportError:  # pragma: no cover - 取决于环境
    plt = None
    HAVE_MPL = False

# 不设中文字体，中文标题会画成一个个方块
if HAVE_MPL:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

# CSV 里需要当数字用的列（cpu_percent / mem_mb 可能为空，见 server/metrics.py）
NUMERIC_FIELDS = (
    "t_mono",
    "client_count",
    "enemies",
    "bullets",
    "tick_ms_avg",
    "tick_ms_p95",
    "tick_ms_max",
    "snapshot_bytes",
    "cpu_percent",
    "mem_mb",
    "packets_out",
    "bytes_out",
    "packets_in",
    "bytes_in",
)

# tick 预算：20 Hz → 50 ms。单帧耗时逼近它就意味着掉帧
TICK_BUDGET_MS = 50.0

# D-011 定的「舒适线」：单核占用超过 50% 就没有余量应对峰值
CPU_COMFORT_PERCENT = 50.0


def load_rows(path: str | Path) -> list[dict]:
    """读 CSV；数字列转 float，空值转 None（psutil 没装时 cpu/mem 是空的）。"""
    rows: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row: dict = {"scenario_id": (raw.get("scenario_id") or "adhoc").strip()}
            for field in NUMERIC_FIELDS:
                text = (raw.get(field) or "").strip()
                row[field] = float(text) if text else None
            rows.append(row)
    return rows


def group_by_scenario(rows: list[dict]) -> dict[str, list[dict]]:
    """按 scenario_id 切分 —— 这就是 §4.3 要求每行都带场景 ID 的原因。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["scenario_id"]].append(row)
    return dict(groups)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[dict], warmup_s: float = 10.0) -> dict:
    """丢掉开头 warmup_s 秒，再对剩下的行取平均。

    用 t_mono（单调时钟）算相对时间 —— 这也是 §4.3「时间戳用单调时钟」的兑现。
    """
    timed = [r for r in rows if r["t_mono"] is not None]
    if not timed:
        return {}

    start = min(r["t_mono"] for r in timed)
    kept = [r for r in timed if r["t_mono"] - start >= warmup_s]
    if not kept:  # 实验太短，热身窗口比整个实验还长：退化成全部数据
        kept = timed

    def values(field: str) -> list[float]:
        return [r[field] for r in kept if r[field] is not None]

    players = _mean(values("client_count"))
    enemies = _mean(values("enemies"))
    bullets = _mean(values("bullets"))
    bytes_out = _mean(values("bytes_out"))

    return {
        "rows": len(kept),
        "players": players,
        "enemies": enemies,
        "bullets": bullets,
        "entities": players + enemies + bullets,
        "tick_ms_avg": _mean(values("tick_ms_avg")),
        "tick_ms_p95": _mean(values("tick_ms_p95")),
        "snapshot_bytes": _mean(values("snapshot_bytes")),
        "cpu_percent": _mean(values("cpu_percent")),
        "mem_mb": _mean(values("mem_mb")),
        # 每行是一个约 1 秒的窗口，所以 bytes_out 就是 B/s；再除以客户端数
        "bw_per_client_bps": bytes_out / players if players else 0.0,
    }


def series_from_groups(groups: dict[str, list[dict]], warmup_s: float = 10.0) -> list[dict]:
    """每个场景一条记录，按实体总数排序（画图的横轴顺序）。"""
    series = []
    for scenario_id, rows in groups.items():
        summary = summarize(rows, warmup_s)
        if not summary:
            continue
        summary["scenario_id"] = scenario_id
        series.append(summary)
    series.sort(key=lambda item: item["entities"])
    return series


def _annotate(ax, xs, ys, labels) -> None:
    for x, y, label in zip(xs, ys, labels):
        ax.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=8,
        )


def plot_e9(series: list[dict], out_dir: str | Path) -> list[Path]:
    """出 E9 的三张图。返回写出的文件路径。"""
    if not HAVE_MPL:
        raise RuntimeError("需要 matplotlib 才能出图：pip install matplotlib")
    if not series:
        raise ValueError("没有任何可用数据；检查 CSV 路径与 scenario_id")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    xs = [s["entities"] for s in series]
    labels = [f"{s['enemies']:.0f}/{s['bullets']:.0f}" for s in series]

    # ---- 图 6-17：实体数 vs 单帧耗时 ----
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ys = [s["tick_ms_avg"] for s in series]
    p95 = [s["tick_ms_p95"] for s in series]
    errors = [max(0.0, hi - lo) for hi, lo in zip(p95, ys)]

    ax.errorbar(xs, ys, yerr=errors, marker="o", capsize=3, label="tick 耗时均值（误差棒 = p95）")
    ax.axhline(TICK_BUDGET_MS, color="crimson", linestyle="--", linewidth=1,
               label=f"tick 预算 {TICK_BUDGET_MS:.0f} ms（20 Hz）")
    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("单帧耗时 (ms)")
    ax.set_title("图 6-17 实体数 vs 单帧耗时")
    ax.grid(alpha=0.3)
    ax.legend()
    _annotate(ax, xs, ys, [f"敌/弹 {lb}" for lb in labels])
    path = out_dir / "fig6-17-entities-vs-tick.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    # ---- 图 6-18：实体数 vs 带宽 ----
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bw = [s["bw_per_client_bps"] / 1024 for s in series]
    ax.plot(xs, bw, marker="o", color="tab:blue", label="下行带宽 / 客户端 (KB/s)")
    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("下行带宽 (KB/s per 客户端)", color="tab:blue")
    ax.tick_params(axis="y", labelcolor="tab:blue")

    snap_ax = ax.twinx()
    snap = [s["snapshot_bytes"] for s in series]
    snap_ax.plot(xs, snap, marker="s", linestyle="--", color="tab:orange",
                 label="单份快照大小 (B)")
    snap_ax.set_ylabel("快照大小 (B)", color="tab:orange")
    snap_ax.tick_params(axis="y", labelcolor="tab:orange")

    ax.set_title("图 6-18 实体数 vs 带宽")
    ax.grid(alpha=0.3)
    lines = ax.get_lines() + snap_ax.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], loc="upper left")
    path = out_dir / "fig6-18-entities-vs-bandwidth.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    # ---- 图 6-19：实体数 vs 单核占用 ----
    fig, ax = plt.subplots(figsize=(7, 4.5))
    cpu = [s["cpu_percent"] for s in series]
    ax.plot(xs, cpu, marker="o", color="tab:red", label="服务端进程单核占用")
    ax.axhline(CPU_COMFORT_PERCENT, color="gray", linestyle="--", linewidth=1,
               label=f"{CPU_COMFORT_PERCENT:.0f}% 舒适线（D-011）")
    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("单核占用 (%)")
    ax.set_title("图 6-19 实体数 vs 单核占用")
    ax.grid(alpha=0.3)
    ax.legend()
    _annotate(ax, xs, cpu, [f"敌/弹 {lb}" for lb in labels])
    path = out_dir / "fig6-19-entities-vs-cpu.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="出 E9 的三张图（图 6-17/6-18/6-19）")
    parser.add_argument("--csv", default="data/server_metrics.csv", help="指标 CSV")
    parser.add_argument("--out", default="docs/figures", help="图片输出目录")
    parser.add_argument(
        "--warmup",
        type=float,
        default=10.0,
        help="每个场景开头丢掉多少秒（进程刚起来 / 客户端没连满）",
    )
    parser.add_argument("--scenario", default="", help="只画 scenario_id 以它开头的场景")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv)
    if args.scenario:
        rows = [r for r in rows if r["scenario_id"].startswith(args.scenario)]
    series = series_from_groups(group_by_scenario(rows), args.warmup)

    if not series:
        print(f"[plot] {args.csv} 里没有可用数据")
        return

    print(f"{'scenario':<28}{'玩家':>5}{'敌机':>6}{'子弹':>6}"
          f"{'实体':>6}{'tick_ms':>9}{'快照B':>8}{'KB/s':>8}{'CPU%':>7}")
    for s in series:
        print(
            f"{s['scenario_id']:<28}{s['players']:>5.0f}{s['enemies']:>6.0f}"
            f"{s['bullets']:>6.0f}{s['entities']:>6.0f}{s['tick_ms_avg']:>9.3f}"
            f"{s['snapshot_bytes']:>8.0f}{s['bw_per_client_bps'] / 1024:>8.1f}"
            f"{s['cpu_percent']:>7.1f}"
        )

    for path in plot_e9(series, args.out):
        print(f"[plot] 已写出 {path}")


if __name__ == "__main__":
    main()