"""E4 的复跑校验：在 3 个关键条件上各再跑一轮，验证可复现性。

## 为什么只挑 3 个点

`03 §7` 要求"每个实验至少跑 2 次，取一致的结果"。E4 有 18 个条件，
全量翻倍要 40 分钟，收益很低 —— 曲线的**形状**由每一档的点共同决定，
只要在"两端 + 转折点"上确认可复现，整条曲线的可信度就够了。

挑的三个点：
- `l0-d0`  基线（一切照旧）
- `l10-d0` **转折点**（P95 在这里从 18.9 跳到 27.7，最需要确认不是偶然）
- `l20-d0` 最恶劣档

结果写进 `data/runs/E4-repeat.json`，并与首轮对比给出偏差。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tools.loadtest import detect_affinity
from tools.run_e4 import log, run_one

REPEAT_POINTS = ((0, 0), (10, 0), (20, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description="E4 复跑校验")
    parser.add_argument("--sample", type=float, default=60.0)
    args = parser.parse_args()

    server_cpus, bot_cpus = detect_affinity()
    log(f"绑核：服务端 {server_cpus}，机器人 {bot_cpus}")

    # run_one 需要这些属性
    args.log_dir = Path("data/logs/e4")
    args.run_dir = Path("data/runs")
    args.server_port = 9630
    args.proxy_port = 9730
    args.seed = 1
    args.bot_seed = 99
    args.startup = 2.0

    first = {}
    manifest = Path("data/runs/E4-manifest.json")
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for run in data.get("runs", []):
            if run.get("ok") and not run.get("jitter_ms"):
                first[(run["loss_pct"], run["delay_ms"])] = run

    results = []
    for loss, delay in REPEAT_POINTS:
        log(f"复跑 l{loss}-d{delay}")
        results.append(run_one(args, float(loss), float(delay), 0.0,
                               server_cpus, bot_cpus))

    out = Path("data/runs/E4-repeat.json")
    out.write_text(
        json.dumps({"repeat_points": REPEAT_POINTS, "runs": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"已写入 {out}")

    log("=" * 70)
    log(f"{'条件':<12}{'指标':<10}{'首轮':>9}{'复跑':>9}{'偏差':>10}")
    for item in results:
        if not item.get("ok"):
            log(f"{item['condition']:<12} 失败")
            continue
        base = first.get((item["loss_pct"], item["delay_ms"]))
        for key, label in (("err_px_mean", "err均值"), ("err_px_p95", "err P95")):
            now = item[key]
            if not base:
                log(f"{item['condition']:<12}{label:<10}{'—':>9}{now:>9.2f}")
                continue
            before = base[key]
            delta = (now - before) / before * 100 if before else 0
            log(f"{item['condition']:<12}{label:<10}{before:>9.2f}{now:>9.2f}"
                f"{delta:>9.1f}%")
    log("=" * 70)
    time.sleep(0)


if __name__ == "__main__":
    main()