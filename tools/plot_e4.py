"""E4 的出图器：从 `data/runs/E4-manifest.json` 画图 6-8 / 6-9 / 6-10。

独立成文件而不是塞进 `plot.py`：E4 的数据源是机器人汇总 JSON（不是服务端指标 CSV），
口径也完全不同（看 P95 而不是均值）。混在一起会让 `plot.py` 更难读。

## 三张图各自要说什么

- **6-8 丢包率 vs 插值误差**：横轴丢包率（固定 delay=0）。
  主线画 **P95**、辅线画均值 —— 因为 TCP 上丢包表现为**重传延迟**，
  它的影响集中在尾部：均值几乎不动，P95 明显抬升。
- **6-9 延迟 vs 插值误差**：横轴延迟（固定 loss=0）。
  实测近似**一条平线** —— 恒定延迟只是把所有事件整体平移，不改变插值误差。
  所以这张图**必须配上抖动对照**，否则读者会以为"实验没做出来"。
- **6-10 丢包 × 延迟 热力图**：颜色是 err P95，看两个因素有没有交互作用。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.plot_e4
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ⚠️ 必须在 import matplotlib **之前**设好缓存目录（和 plot.py 同一处理）。
# 不设的话它会往仓库根目录建 matplotlib-xxxx 临时目录，等于每次跑都拉一次垃圾。
_MPL_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "matplotlib"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

# 中文字体：沿用 plot.py 的处理方式（必须在中文字体设置之后再 import pyplot）
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "DengXian", "SimSun", "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt  # noqa: E402

MANIFEST = Path("data/runs/E4-manifest.json")
OUT_DIR = Path("docs/figures")


def load_manifest(path: Path = MANIFEST) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到 {path}，先跑 tools.run_e4")
    return json.loads(path.read_text(encoding="utf-8"))


def _grid(data: dict) -> dict[tuple[float, float], dict]:
    """(丢包率, 延迟) -> 结果。只保留主矩阵（抖动=0）的那些点。"""
    cells: dict[tuple[float, float], dict] = {}
    for run in data.get("runs", []):
        if not run.get("ok") or run.get("jitter_ms"):
            continue
        cells[(run["loss_pct"], run["delay_ms"])] = run
    return cells


def _jitter_series(data: dict) -> list[dict]:
    points = [r for r in data.get("runs", []) if r.get("ok") and r.get("jitter_ms")]
    points.append({"jitter_ms": 0.0, **next(
        (r for r in data["runs"] if r.get("ok")
         and r.get("loss_pct") == 0 and r.get("delay_ms") == 0), {})})
    return sorted(points, key=lambda r: r["jitter_ms"])


def plot_loss_vs_err(data: dict, out_dir: Path) -> list[Path]:
    """图 6-8：丢包率 vs 插值误差（delay = 0）。"""
    cells = _grid(data)
    points = [(loss, run) for (loss, delay), run in cells.items() if delay == 0]
    if not points:
        return []
    points.sort(key=lambda pair: pair[0])

    xs = [loss for loss, _ in points]
    means = [run["err_px_mean"] for _, run in points]
    p95s = [run["err_px_p95"] for _, run in points]

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.plot(xs, p95s, marker="s", linewidth=2, color="#9c4221",
            markersize=7, label="P95（尾部，主要指标）")
    ax.plot(xs, means, marker="o", linewidth=2, color="#2b6cb0",
            markersize=7, label="均值")
    for x, y in zip(xs, p95s):
        ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=9)
    for x, y in zip(xs, means):
        ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points",
                    xytext=(0, -16), ha="center", fontsize=9)

    ax.set_xlabel("丢包率 (%)")
    ax.set_ylabel("插值误差 err_px (px)")
    ax.set_title("图 6-8   丢包率与插值误差（TCP）")
    ax.set_xticks(xs)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, max(p95s) * 1.3)
    ax.legend(loc="upper left", fontsize=9)
    ax.text(
        0.97, 0.05,
        "传输层是 TCP：丢包不会丢帧，而是触发重传\n"
        "→ 表现为 RTO 量级的延迟尖峰，故均值几乎不动、P95 明显抬升",
        transform=ax.transAxes, fontsize=7.5, va="bottom", ha="right",
        color="#555555",
    )
    fig.tight_layout()
    out = out_dir / "6-8-loss-vs-errpx.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return [out]


def plot_delay_vs_err(data: dict, out_dir: Path) -> list[Path]:
    """图 6-9：延迟 vs 插值误差（loss = 0）+ 抖动对照。"""
    cells = _grid(data)
    points = [(delay, run) for (loss, delay), run in cells.items() if loss == 0]
    jitter_points = _jitter_series(data)
    if not points and not jitter_points:
        return []

    points.sort(key=lambda pair: pair[0])
    xs = [delay for delay, _ in points]
    means = [run["err_px_mean"] for _, run in points]
    p95s = [run["err_px_p95"] for _, run in points]

    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    if xs:
        ax.plot(xs, means, marker="o", linewidth=2, color="#2b6cb0",
                markersize=7, label="恒定延迟 · 均值")
        ax.plot(xs, p95s, marker="s", linewidth=1.6, color="#2b6cb0",
                markersize=6, linestyle="--", label="恒定延迟 · P95")

    if len(jitter_points) >= 2:
        jitter_x = [run["jitter_ms"] for run in jitter_points]
        jitter_mean = [run["err_px_mean"] for run in jitter_points]
        jitter_p95 = [run["err_px_p95"] for run in jitter_points]
        ax.plot(jitter_x, jitter_mean, marker="^", linewidth=2, color="#b7791f",
                markersize=7, label="抖动注入 · 均值")
        ax.plot(jitter_x, jitter_p95, marker="v", linewidth=1.6, color="#b7791f",
                markersize=6, linestyle="--", label="抖动注入 · P95")

    ax.set_xlabel("网络损伤强度 (ms)　蓝=恒定延迟　橙=抖动幅度")
    ax.set_ylabel("插值误差 err_px (px)")
    ax.set_title("图 6-9   延迟与插值误差：恒定延迟无害，抖动才伤")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    ax.text(
        0.97, 0.42,
        "恒定延迟只是把事件整体平移，不改变快照之间的相对间隔\n"
        "→ 插值误差几乎不变；真正推高误差的是到达时间的方差（抖动）",
        transform=ax.transAxes, fontsize=7.5, va="top", ha="right",
        color="#555555",
    )
    fig.tight_layout()
    out = out_dir / "6-9-delay-vs-errpx.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return [out]


def plot_heatmap(data: dict, out_dir: Path) -> list[Path]:
    """图 6-10：丢包 × 延迟 热力图（颜色 = err P95）。"""
    cells = _grid(data)
    if not cells:
        return []

    losses = sorted({loss for loss, _ in cells})
    delays = sorted({delay for _, delay in cells})

    grid = []
    for loss in losses:
        row = []
        for delay in delays:
            run = cells.get((loss, delay))
            row.append(run["err_px_p95"] if run else float("nan"))
        grid.append(row)

    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    image = ax.imshow(grid, cmap="YlOrRd", aspect="auto", origin="lower")
    ax.set_xticks(range(len(delays)))
    ax.set_xticklabels([f"{d:g}" for d in delays])
    ax.set_yticks(range(len(losses)))
    ax.set_yticklabels([f"{loss:g}" for loss in losses])
    ax.set_xlabel("延迟 (ms，每方向)")
    ax.set_ylabel("丢包率 (%)")
    ax.set_title("图 6-10   丢包 × 延迟 对插值误差 P95 的影响")

    for row_index, loss in enumerate(losses):
        for col_index, delay in enumerate(delays):
            value = grid[row_index][col_index]
            if value != value:  # NaN
                continue
            ax.text(col_index, row_index, f"{value:.1f}", ha="center",
                    va="center", fontsize=9,
                    color="black" if value < max(max(r) for r in grid) * 0.7 else "white")

    fig.colorbar(image, ax=ax, label="err_px P95 (px)")
    fig.tight_layout()
    out = out_dir / "6-10-loss-delay-heatmap.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return [out]


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    data = load_manifest()

    written = []
    written += plot_loss_vs_err(data, out_dir)
    written += plot_delay_vs_err(data, out_dir)
    written += plot_heatmap(data, out_dir)

    if not written:
        print("[plot-e4] 没有可画的 E4 数据")
        return
    for path in written:
        print(f"[plot-e4] 已写出 {path}")


if __name__ == "__main__":
    main()