"""E5：**tick 率**的影响 —— 带宽 / CPU / 单 tick 耗时。

## 实验设计

- **自变量**：`--tick-hz ∈ {10, 15, 20, 30}`
- **控制变量**（D-029）：4 玩家 / 30 敌机 / 200 子弹，`--fixed-entities`，
  同一 `--seed`、同一编码器（binary）、同一台机器、绑核方案不变
- **每档 2 轮**，每轮 10 s 预热 + **180 s（3 分钟）采样**

## 为什么必须先把统计窗口改成恒 1 秒

指标 CSV 是**每秒一行**（服务端按 `stats_every_ticks = tick_hz` 个 tick 上报）。
如果窗口写死 20 个 tick，10 Hz 下窗口就是 2 秒、30 Hz 下 0.67 秒 ——
`bytes_out` 这一行代表的**时间跨度不同**，"每秒字节数"就不可比了。
而且它**不会报错**，只会让结论悄悄错掉。见 `server/main.py` 的注释。

## 三个口径

| 指标 | 口径 | 为什么这么算 |
|---|---|---|
| 带宽 | `bytes_out` 的均值 | CSV 每秒一行，所以均值就是 B/s |
| CPU | `cpu_seconds` 首尾差 ÷ 墙钟秒 × 100 | E9 已确立的口径；低负载下逐行 `cpu_percent` 噪声大 |
| 单 tick 耗时 | `tick_ms_avg` 的均值与 p95 | 每行是**该窗口内所有 tick 的平均**，不是单个 tick |

## 预期（写在这里，实验结果要能证伪）

带宽 ≈ `快照字节 × tick_hz`（几乎线性，因为每 tick 都发全量快照）；
CPU 随 tick 率上升（每秒做更多次模拟+碰撞）；
**单 tick 耗时应基本不变** —— 每个 tick 干的活是一样的。
如果单 tick 耗时也随频率明显变化，说明有缓存/调度层面的效应，要在报告里解释。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.run_e5            # 全量（约 26 分钟）
    .venv\\Scripts\\python.exe -X utf8 -m tools.run_e5 --quick    # 冒烟（约 2 分钟）
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

# 复用 E2 的基础设施：绑核、场景名解析、指标行读取、崩溃标记
from tools.loadtest import (
    CRASH_MARKER,
    FIXED_BULLETS,
    FIXED_ENEMIES,
    FIXED_PLAYERS,
    PROJECT_ROOT,
    bind,
    count_rows,
    detect_affinity,
    ramp_for,
    read_scenario_rows,
    system_cpu_percent,
)

# tick 率档位：覆盖"明显卡顿"(10) 到"很流畅"(30)，20 是当前默认值
DEFAULT_TIERS = (10, 15, 20, 30)
DEFAULT_REPS = 2
WARMUP_S = 10.0
SAMPLE_S = 180.0

# tick 预算：50 ms = 20 Hz 的帧间隔。**这不是 E5 的判定标准**
# （10 Hz 的预算应该是 100 ms），只用来标出"这一档已经吃掉多少预算"
BUDGET_RATIO_NOTE = "tick_ms_avg / (1000 / tick_hz)"


def log(message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    print(f"[e5 {stamp}] {message}", flush=True)


def scenario_name(tick_hz: int, rep: int) -> str:
    """`E5-h20-r1` —— 横轴是 tick 率（h = Hz），不是连接数。"""
    return f"E5-h{tick_hz}-r{rep}"


def build_server_cmd(args: argparse.Namespace, name: str, tick_hz: int) -> list[str]:
    return [
        sys.executable, "-X", "utf8", "-u", "-m", "server.main",
        str(args.port),
        "--enemies", str(FIXED_ENEMIES),
        "--bullets", str(FIXED_BULLETS),
        "--scenario", name,
        "--metrics", str(args.metrics),
        "--seed", str(args.seed),
        "--tick-hz", str(tick_hz),   # ← E5 的自变量
        "--fixed-entities",
        "--no-stats",
    ]


def build_bot_cmd(args: argparse.Namespace, duration: float,
                  out_path: Path) -> list[str]:
    return [
        sys.executable, "-X", "utf8", "-u", "-m", "bot.main",
        "--port", str(args.port),
        "--clients", str(FIXED_PLAYERS),
        "--duration", str(int(duration)),
        "--ramp", str(ramp_for(FIXED_PLAYERS)),
        "--seed", str(args.bot_seed),
        "--out", str(out_path),
    ]


def _num(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def summarize(rows: list[dict], tick_hz: int) -> dict:
    """把某场景的逐秒行汇总成 E5 要的三个数。

    **只取 `client_count == FIXED_PLAYERS` 的行**：服务端一启动就开始写指标，
    前几秒还没有机器人连上来，那些行里没有快照流量，混进来会把带宽拉低。
    """
    full = [r for r in rows if (_num(r, "client_count") or 0) >= FIXED_PLAYERS]
    if len(full) > WARMUP_S:
        full = full[int(WARMUP_S):]  # 丢掉预热段

    if not full:
        return {"windows": 0, "error": "没有满负载的采样行"}

    bandwidth = [v for v in (_num(r, "bytes_out") for r in full) if v is not None]
    tick_ms = [v for v in (_num(r, "tick_ms_avg") for r in full) if v is not None]
    snap_bytes = [v for v in (_num(r, "snapshot_bytes") for r in full) if v is not None]
    packets = [v for v in (_num(r, "packets_out") for r in full) if v is not None]

    result: dict = {"windows": len(full), "tick_hz": tick_hz}

    if bandwidth:
        mean_bw = sum(bandwidth) / len(bandwidth)
        result["bandwidth_bps"] = round(mean_bw, 1)
        result["bandwidth_kbps"] = round(mean_bw / 1024, 2)
    if packets:
        result["packets_out_per_s"] = round(sum(packets) / len(packets), 1)
    if snap_bytes:
        result["snapshot_bytes"] = round(sum(snap_bytes) / len(snap_bytes), 1)
    if tick_ms:
        ordered = sorted(tick_ms)
        result["tick_mean_ms"] = round(sum(tick_ms) / len(tick_ms), 3)
        result["tick_p95_ms"] = round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 3)
        result["tick_max_ms"] = round(max(tick_ms), 3)
        # 这一档吃了多少 tick 预算（预算 = 1000/tick_hz ms）
        budget = 1000.0 / tick_hz
        result["budget_ms"] = round(budget, 1)
        result["budget_used_percent"] = round(result["tick_mean_ms"] / budget * 100, 1)

    # CPU：首尾差 ÷ 墙钟秒（E9 口径）
    first_cpu = _num(full[0], "cpu_seconds")
    last_cpu = _num(full[-1], "cpu_seconds")
    span = (_num(full[-1], "t_mono") or 0) - (_num(full[0], "t_mono") or 0)
    if first_cpu is not None and last_cpu is not None and span > 0:
        result["cpu_percent"] = round((last_cpu - first_cpu) / span * 100, 2)
    else:
        cpu_values = [v for v in (_num(r, "cpu_percent") for r in full) if v is not None]
        if cpu_values:
            result["cpu_percent"] = round(sum(cpu_values) / len(cpu_values), 2)

    return result


def run_one(args: argparse.Namespace, tick_hz: int, rep: int,
            server_cpus: list[int], bot_cpus: list[int]) -> dict:
    name = scenario_name(tick_hz, rep)
    log_path = args.log_dir / f"{name}.log"
    bot_json = args.run_dir / f"{name}.json"
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.mkdir(parents=True, exist_ok=True)

    duration = WARMUP_S + args.sample
    result: dict = {
        "scenario": name,
        "tick_hz": tick_hz,
        "rep": rep,
        "warmup_s": WARMUP_S,
        "sample_s": args.sample,
        "entities": {"players": FIXED_PLAYERS, "enemies": FIXED_ENEMIES,
                     "bullets": FIXED_BULLETS},
    }

    log(f"▶ {name}：{tick_hz} Hz，采样 {args.sample:.0f}s")
    with log_path.open("w", encoding="utf-8") as srvlog:
        server = subprocess.Popen(
            build_server_cmd(args, name, tick_hz),
            cwd=PROJECT_ROOT, stdout=srvlog, stderr=subprocess.STDOUT,
        )
        result["server_affinity_ok"] = bind(server.pid, server_cpus)
        bot_log = args.log_dir / f"{name}.bot.log"
        try:
            time.sleep(args.startup)
            with bot_log.open("w", encoding="utf-8") as blog:
                bot = subprocess.Popen(
                    build_bot_cmd(args, duration, bot_json),
                    cwd=PROJECT_ROOT, stdout=blog, stderr=subprocess.STDOUT,
                )
                result["bot_affinity_ok"] = bind(bot.pid, bot_cpus)
                try:
                    bot.wait(timeout=duration + 120)
                except subprocess.TimeoutExpired:
                    result["error"] = "机器人超时，已强杀"
                    bot.kill()
                    bot.wait(timeout=10)
            time.sleep(args.teardown)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                server.kill()

    text = log_path.read_text(encoding="utf-8", errors="replace")
    result["server_crashed"] = CRASH_MARKER in text
    rows = read_scenario_rows(args.metrics, name)
    result["metric_rows"] = count_rows(args.metrics, name)
    result.update(summarize(rows, tick_hz))

    if result["server_crashed"]:
        result["error"] = result.get("error") or "服务端 tick loop 崩溃"
    result["ok"] = not result.get("error")
    log(
        f"  {name}: 带宽 {result.get('bandwidth_kbps', '?')} KB/s, "
        f"CPU {result.get('cpu_percent', '?')}%, "
        f"tick {result.get('tick_mean_ms', '?')} ms, "
        f"预算占用 {result.get('budget_used_percent', '?')}%"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E5 tick 率实验")
    parser.add_argument("--port", type=int, default=9585)
    parser.add_argument("--metrics", type=Path,
                        default=PROJECT_ROOT / "data" / "server_metrics.csv")
    parser.add_argument("--log-dir", type=Path,
                        default=PROJECT_ROOT / "data" / "logs" / "e5")
    parser.add_argument("--run-dir", type=Path,
                        default=PROJECT_ROOT / "data" / "runs")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bot-seed", type=int, default=99)
    parser.add_argument("--startup", type=float, default=1.5)
    parser.add_argument("--teardown", type=float, default=1.0)
    parser.add_argument("--sample", type=float, default=SAMPLE_S,
                        help="每轮采样时长（秒）")
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--tiers", type=int, nargs="+", default=list(DEFAULT_TIERS))
    parser.add_argument("--quick", action="store_true",
                        help="冒烟：20/30 Hz 各 1 轮、采样 20 s")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.quick:
        args.tiers = [20, 30]
        args.reps = 1
        args.sample = 20.0

    server_cpus, bot_cpus = detect_affinity()
    log(f"绑核：服务端 {server_cpus}，机器人 {bot_cpus}")

    results: list[dict] = []
    total = len(args.tiers) * args.reps
    index = 0
    for tick_hz in args.tiers:
        for rep in range(1, args.reps + 1):
            index += 1
            log(f"[{index}/{total}] {tick_hz} Hz 第 {rep} 轮")
            results.append(run_one(args, tick_hz, rep, server_cpus, bot_cpus))

    args.run_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.run_dir / "E5-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "experiment": "E5",
                "variable": "tick_hz",
                "tiers": args.tiers,
                "reps": args.reps,
                "sample_s": args.sample,
                "warmup_s": WARMUP_S,
                "entities": {"players": FIXED_PLAYERS, "enemies": FIXED_ENEMIES,
                             "bullets": FIXED_BULLETS},
                "budget_note": BUDGET_RATIO_NOTE,
                "runs": results,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    log(f"清单已写入 {manifest}")

    # 逐档汇总（同一档的多轮取均值）
    log("=" * 76)
    log(f"{'tick':>6} {'带宽 KB/s':>10} {'CPU %':>7} {'tick ms':>8} {'p95 ms':>7} {'预算占用':>9}")
    for tick_hz in args.tiers:
        group = [r for r in results if r["tick_hz"] == tick_hz and r.get("ok")]
        if not group:
            log(f"{tick_hz:>4}Hz  —— 没有成功的轮次")
            continue

        def mean(key: str) -> float | None:
            values = [r[key] for r in group if isinstance(r.get(key), (int, float))]
            return sum(values) / len(values) if values else None

        bw, cpu = mean("bandwidth_kbps"), mean("cpu_percent")
        tick, p95 = mean("tick_mean_ms"), mean("tick_p95_ms")
        used = mean("budget_used_percent")
        log(
            f"{tick_hz:>4}Hz {bw if bw is None else round(bw, 2):>10} "
            f"{cpu if cpu is None else round(cpu, 2):>7} "
            f"{tick if tick is None else round(tick, 3):>8} "
            f"{p95 if p95 is None else round(p95, 3):>7} "
            f"{used if used is None else round(used, 1):>8}%"
        )
    log("=" * 76)
    log("下一步：python -X utf8 -m tools.plot --figures e5")


if __name__ == "__main__":
    main()