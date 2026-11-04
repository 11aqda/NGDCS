"""E5 补充实验：**tick 率 vs 插值误差**（图 6-12）。

## 为什么单独一个脚本

`tools/run_e5.py` 量的是**服务端**指标（带宽 / CPU / tick 耗时），来自指标 CSV。
图 6-12 要的是**客户端**指标（`err_px`），只能从机器人汇总 JSON 里拿。
两者数据源不同，硬塞进一个脚本反而绕。

## ⚠️ 理论预测**被实测推翻了**，记录在这里（不要事后悄悄改）

跑之前写下的预测是：

$$
\\text{err} \\approx v \\times \\frac{1}{f}
$$

即 **err 与 tick 率成反比**，10 Hz 应当是 20 Hz 的 2 倍。

**实测结果方向相反**（2026-11-04）：

| tick | err 均值 px | p95 | max |
|---|---|---|---|
| 10 Hz | **10.30** | 17.25 | 17.61 |
| 15 Hz | 9.17 | 18.05 | 18.53 |
| 20 Hz | 8.73 | 18.71 | 19.38 |
| 30 Hz | **7.05** | 19.60 | 20.62 |

### 为什么不成立

上式的 `v × (1/f)` 默认**速度是"每秒多少像素"**。但本项目的玩家速度是
`PLAYER_SPEED_PER_TICK`（**每 tick 固定 15 px**，见 `02 §4.5`）——
所以每个 tick 的位移**与频率无关，恒为 15 px**，`err` 自然不随 `1/f` 变化。

更进一层：频率越高，玩家的**实际速度**越大（10 Hz → 150 px/s，30 Hz → 450 px/s）。
30 Hz 下 1.6 秒就能走完 720 px 的场地，**大部分时间被墙卡住、位移为 0**，
平均误差反而更小。

证据：`err_mean / 15px` 从 10 Hz 的 **0.69** 掉到 30 Hz 的 **0.47** ——
正是"处于移动状态的帧变少了"。而 p95/max 反而随频率上升（17.3 → 19.6），
因为高频下每帧位移仍是 15 px、偶发两帧叠加时跳得更远。

### 结论

这不是测量错误，**是设计的耦合被量出来了**。它是 `docs/experiments/E5-tick率影响.md §5.3`
那条"每 tick 固定像素"限制的**第二个后果**（第一个是游戏速度随频率变）。
要把图 6-12 画成教科书里那种"频率越低误差越大"，必须先把速度改成"每秒多少像素"。

## 与主实验的差别

- 采样 **40 s**（不是 180 s）：`err_px` 是逐帧样本，30 s 就有 600+ 个，够稳定
- 只跑 2 档轮次，用于 §一致性

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.run_e5_errpx
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from tools.loadtest import (
    FIXED_BULLETS,
    FIXED_ENEMIES,
    FIXED_PLAYERS,
    PROJECT_ROOT,
    bind,
    detect_affinity,
    ramp_for,
)

DEFAULT_TIERS = (10, 15, 20, 30)
DEFAULT_REPS = 2
WARMUP_S = 5.0
SAMPLE_S = 40.0


def log(message: str) -> None:
    print(f"[e5-err {time.strftime('%H:%M:%S')}] {message}", flush=True)


def scenario_name(tick_hz: int, rep: int) -> str:
    return f"E5E-h{tick_hz}-r{rep}"


def run_one(args, tick_hz: int, rep: int,
            server_cpus: list[int], bot_cpus: list[int]) -> dict:
    name = scenario_name(tick_hz, rep)
    log_path = args.log_dir / f"{name}.log"
    bot_json = args.run_dir / f"{name}.json"
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.mkdir(parents=True, exist_ok=True)

    duration = WARMUP_S + args.sample
    server_cmd = [
        sys.executable, "-X", "utf8", "-u", "-m", "server.main",
        str(args.port),
        "--enemies", str(FIXED_ENEMIES),
        "--bullets", str(FIXED_BULLETS),
        "--tick-hz", str(tick_hz),
        "--fixed-entities",
        "--no-metrics", "--no-stats",
    ]
    bot_cmd = [
        sys.executable, "-X", "utf8", "-u", "-m", "bot.main",
        "--port", str(args.port),
        "--clients", str(FIXED_PLAYERS),
        "--duration", str(int(duration)),
        "--ramp", str(ramp_for(FIXED_PLAYERS)),
        "--seed", str(args.bot_seed + tick_hz),   # 每档不同种子，避免同一组按键
        "--err-px",                                # ← 采集插值误差
        "--out", str(bot_json),
    ]

    log(f"▶ {name}：{tick_hz} Hz，采集 {args.sample:.0f}s")
    with log_path.open("w", encoding="utf-8") as srvlog:
        server = subprocess.Popen(server_cmd, cwd=PROJECT_ROOT,
                                  stdout=srvlog, stderr=subprocess.STDOUT)
        bind(server.pid, server_cpus)
        bot_log = args.log_dir / f"{name}.bot.log"
        try:
            time.sleep(args.startup)
            with bot_log.open("w", encoding="utf-8") as blog:
                bot = subprocess.Popen(bot_cmd, cwd=PROJECT_ROOT,
                                       stdout=blog, stderr=subprocess.STDOUT)
                bind(bot.pid, bot_cpus)
                try:
                    bot.wait(timeout=duration + 120)
                except subprocess.TimeoutExpired:
                    bot.kill()
                    bot.wait(timeout=10)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                server.kill()

    result: dict = {"scenario": name, "tick_hz": tick_hz, "rep": rep,
                    "sample_s": args.sample}
    if not bot_json.exists():
        result["error"] = "机器人没有写出汇总文件"
        result["ok"] = False
        return result

    summary = json.loads(bot_json.read_text(encoding="utf-8"))
    for key in ("err_px_mean", "err_px_p95", "err_px_max", "err_px_samples"):
        result[key] = summary.get(key)
    result["ok"] = isinstance(result.get("err_px_mean"), (int, float))
    if not result["ok"]:
        result["error"] = "没有 err_px 样本"

    log(
        f"  {name}: err_mean={result.get('err_px_mean')} px, "
        f"p95={result.get('err_px_p95')}, max={result.get('err_px_max')}, "
        f"样本={result.get('err_px_samples')}"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E5 补充：tick 率 vs 插值误差")
    parser.add_argument("--port", type=int, default=9586)
    parser.add_argument("--log-dir", type=Path,
                        default=PROJECT_ROOT / "data" / "logs" / "e5err")
    parser.add_argument("--run-dir", type=Path,
                        default=PROJECT_ROOT / "data" / "runs")
    parser.add_argument("--bot-seed", type=int, default=99)
    parser.add_argument("--startup", type=float, default=1.5)
    parser.add_argument("--sample", type=float, default=SAMPLE_S)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--tiers", type=int, nargs="+", default=list(DEFAULT_TIERS))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server_cpus, bot_cpus = detect_affinity()
    log(f"绑核：服务端 {server_cpus}，机器人 {bot_cpus}")

    results: list[dict] = []
    index = 0
    total = len(args.tiers) * args.reps
    for tick_hz in args.tiers:
        for rep in range(1, args.reps + 1):
            index += 1
            log(f"[{index}/{total}] {tick_hz} Hz 第 {rep} 轮")
            results.append(run_one(args, tick_hz, rep, server_cpus, bot_cpus))

    args.run_dir.mkdir(parents=True, exist_ok=True)
    path = args.run_dir / "E5-errpx.json"
    path.write_text(
        json.dumps(
            {"experiment": "E5-errpx", "variable": "tick_hz",
             "metric": "err_px", "tiers": args.tiers, "reps": args.reps,
             "sample_s": args.sample, "warmup_s": WARMUP_S,
             "runs": results},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    log(f"已写入 {path}")

    log("=" * 66)
    log(f"{'tick':>6} {'err 均值 px':>12} {'p95':>9} {'max':>9} {'预期反比':>10}")
    baseline = None
    for tick_hz in args.tiers:
        group = [r for r in results if r["tick_hz"] == tick_hz and r.get("ok")]
        if not group:
            log(f"{tick_hz:>4}Hz   没有成功的轮次")
            continue
        mean = sum(r["err_px_mean"] for r in group) / len(group)
        p95 = sum(r["err_px_p95"] for r in group) / len(group)
        mx = sum(r["err_px_max"] for r in group) / len(group)
        if tick_hz == 20:
            baseline = mean
        log(f"{tick_hz:>4}Hz {mean:>12.2f} {p95:>9.2f} {mx:>9.2f}")
    if baseline:
        log("按 err ∝ 1/f 推算（以 20 Hz 为基准）：")
        for tick_hz in args.tiers:
            expected = baseline * 20.0 / tick_hz
            group = [r for r in results if r["tick_hz"] == tick_hz and r.get("ok")]
            if not group:
                continue
            actual = sum(r["err_px_mean"] for r in group) / len(group)
            log(f"  {tick_hz:>4}Hz  预期 {expected:6.2f} px  实测 {actual:6.2f} px  "
                f"偏差 {(actual - expected) / expected * 100:+6.1f}%")
    log("=" * 66)
    log("下一步：python -X utf8 -m tools.plot --figures e5")


if __name__ == "__main__":
    main()