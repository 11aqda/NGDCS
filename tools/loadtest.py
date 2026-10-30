"""E2 实验运行器：固定实体、逐档递增**连接数**，加到失败为止。

## 与 E9 的区别（别搞混）

| | 自变量 | 因变量看什么 |
|---|---|---|
| **E9** | 实体数（敌机/子弹） | 单帧耗时构成、带宽、单核占用 |
| **E2** | **连接数**（10 → 400） | CPU/内存、tick 耗时、RTT 分位数 |

E9 固定客户端数、加实体；E2 反过来：**固定实体（D-029 的 4 玩家 + 30 敌机 + 200 子弹）、加连接数**。

## 三个刻意的设计

### ① 绑核：服务端和机器人抢 CPU 会互相污染

服务端是**单线程 asyncio**，机器人集群也是纯 Python。两者放同一批核上，
测出来的 `tick_ms` 分不清是"连接数涨了"还是"被机器人挤了"。

本机 16 逻辑核 / 8 物理核（AMD Zen3，超线程成对 (0,1)(2,3)…），所以：

- **服务端** → 物理核 0 = `[0, 1]`（单线程循环可以落在该核任一线程）
- **机器人** → 其余 7 个物理核 = `[2..15]`

实际用的亲和性会写进 `manifest.json`，换机器跑也能看出条件变没变。

### ② 加到失败为止，且**区分谁先崩**

失败判定（任一成立即算该档失败）：

- 服务端指标里**连续 3 个窗口** `tick_ms > 50`
- 机器人 `errors > 0`
- `clients_connected < clients`（有新连接 5 s 内没握上手）
- 服务端日志出现 `tick loop 已崩溃`

失败时记录 `blame`：`server` / `bot` / `both` —— 这两者含义完全不同，
服务端崩说明**系统的天花板**，机器人崩说明**测试端先撑不住**，结论要分开写。

### ③ 每档 10 s 预热 + 60 s 采样，两轮偏差大就补长

预热期数据丢弃（`tools/plot.py` 按 `t_mono` 丢前 10 s）。两轮的关键指标
（CPU%、tick 均值）偏差 **> 10%** 时，自动补跑一轮 **120 s 采样**，并标注在清单里。

## 用法

    # 只看计划，不执行
    .venv\\Scripts\\python.exe -X utf8 -m tools.loadtest --dry-run

    # 正式跑（10/20/50/100/200，都过则加到 250/300/400）
    .venv\\Scripts\\python.exe -X utf8 -m tools.loadtest

    # 只跑指定的档
    .venv\\Scripts\\python.exe -X utf8 -m tools.loadtest --tiers 10,20

产出：`data/server_metrics.csv`、`data/runs/<场景>.json`、`data/logs/`、
以及本批的 `data/runs/manifest.json`（含亲和性、每档结论、失败归因）。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from server.metrics import MetricsRecorder
from tools.run_e9 import CRASH_MARKER, count_rows, system_cpu_percent

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 起始档；全过则继续往 EXTEND_TIERS 加，上限 400
DEFAULT_TIERS = (10, 20, 50, 100, 200)
EXTEND_TIERS = (250, 300, 400)

# 实体固定为 E9 目标档，保证两套实验在同一实体规模下可比
FIXED_PLAYERS = 4
FIXED_ENEMIES = 30
FIXED_BULLETS = 200

WARMUP_S = 10.0
SAMPLE_S = 60.0
EXTENDED_SAMPLE_S = 120.0
TICK_BUDGET_MS = 50.0
CONSECUTIVE_BAD_WINDOWS = 3
DEVIATION_LIMIT = 0.10


def log(message: str) -> None:
    print(f"[e2] {message}", flush=True)


# ---------------------------------------------------------------- 绑核


def detect_affinity() -> tuple[list[int], list[int]]:
    """返回 (服务端核, 机器人核)。

    AMD Zen3 上 16 逻辑核 = 8 物理核 × 2 超线程，成对为 (0,1)(2,3)…
    所以"一个物理核"取一对逻辑核。若机器不是成对拓扑，退化为
    "服务端 1 个逻辑核、机器人其余"，并如实记录 —— **不要假装绑对了**。
    """
    try:
        import psutil
    except ImportError:  # pragma: no cover - 环境缺 psutil 时不应跑实验
        return [], []

    logical = psutil.cpu_count(logical=True) or 0
    physical = psutil.cpu_count(logical=False) or 0
    available = sorted(psutil.Process().cpu_affinity())
    if not available:
        return [], []

    if physical and logical == physical * 2:
        # 超线程成对：物理核 i 占用逻辑核 (2i, 2i+1)
        server = [available[0], available[1]] if len(available) >= 2 else available[:1]
        bots = [cpu for cpu in available if cpu not in server]
        return server, bots

    # 无法确认拓扑：只给服务端 1 个逻辑核，其余给机器人，并在清单里注明
    return available[:1], available[1:]


def bind(pid: int, cpus: list[int]) -> bool:
    """把进程绑到指定核；失败返回 False（不中断实验，但会记录）。"""
    if not cpus:
        return False
    try:
        import psutil

        psutil.Process(pid).cpu_affinity(cpus)
        return True
    except Exception:  # noqa: BLE001 - 绑核是尽力而为，失败不能毁掉整批实验
        return False


# ---------------------------------------------------------------- 场景与命令


def scenario_name(clients: int, rep: int) -> str:
    """`E2-c10-r1` —— 档位（连接数）+ 轮次。

    末尾保留 `-r<数字>`，这样 `tools/plot.py` 现有的轮次解析不用改。
    """
    return f"E2-c{clients}-r{rep}"


def build_server_cmd(args, name: str) -> list[str]:
    return [
        sys.executable, "-X", "utf8", "-u", "-m", "server.main",
        str(args.port),
        "--enemies", str(FIXED_ENEMIES),
        "--bullets", str(FIXED_BULLETS),
        "--scenario", name,
        "--metrics", str(args.metrics),
        "--seed", str(args.seed),
        # D-029：实验期实体数恒定，漂移即报错停跑
        "--fixed-entities",
        "--no-stats",
    ]


def build_bot_cmd(args, clients: int, ramp: int, duration: float, out_path: Path) -> list[str]:
    return [
        sys.executable, "-X", "utf8", "-u", "-m", "bot.main",
        "--port", str(args.port),
        "--clients", str(clients),
        "--duration", str(int(duration)),
        "--ramp", str(ramp),
        "--seed", str(args.bot_seed),
        "--out", str(out_path),
    ]


def ramp_for(clients: int) -> int:
    """让所有客户端在 5 s 内连完，剩下的预热时间用来「稳住」。

    连接太慢会挤占预热、连接太猛（一次性 400 个）又会把 accept 队列打爆，
    所以在 5 s 内铺开是折中。
    """
    return max(10, math.ceil(clients / 5))


# ---------------------------------------------------------------- 读数


def read_scenario_rows(metrics: Path, scenario: str) -> list[dict]:
    """取出某场景的全部指标行（服务端每秒一行）。"""
    if not metrics.exists():
        return []
    import csv

    rows: list[dict] = []
    with metrics.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("scenario_id") == scenario:
                rows.append(row)
    return rows


def _f(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def analyze(rows: list[dict], summary: dict | None, clients: int) -> dict:
    """判失败 + 归因。**先看服务端，再看机器人**。"""
    verdict: dict = {
        "bad_run": 0,          # 连续超预算的最长连击
        "tick_p95_ms": None,
        "tick_mean_ms": None,
        "cpu_percent": None,
        "blame": "",
        "reasons": [],
    }

    # ---- 服务端侧 ----
    tick_ms = [v for v in (_f(r, "tick_ms_avg") for r in rows) if v is not None]
    if tick_ms:
        verdict["tick_mean_ms"] = round(sum(tick_ms) / len(tick_ms), 3)
        ordered = sorted(tick_ms)
        verdict["tick_p95_ms"] = round(ordered[int(len(ordered) * 0.95) - 1], 3)

    run = 0
    worst = 0
    for value in tick_ms:
        if value > TICK_BUDGET_MS:
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    verdict["bad_run"] = worst
    if worst >= CONSECUTIVE_BAD_WINDOWS:
        verdict["reasons"].append(
            f"服务端连续 {worst} 个窗口 tick_ms > {TICK_BUDGET_MS:g}ms"
        )

    # 单核占用：取 CPU 秒数首尾差 ÷ 墙钟秒（E9 已确立的口径，低负载下比逐行值可靠）
    cpu_values = [v for v in (_f(r, "cpu_percent") for r in rows) if v is not None]
    if cpu_values:
        verdict["cpu_percent"] = round(sum(cpu_values) / len(cpu_values), 2)
    if not verdict["cpu_percent"] and rows:
        first = _f(rows[0], "cpu_seconds")
        last = _f(rows[-1], "cpu_seconds")
        span = _f(rows[-1], "t_mono") - _f(rows[0], "t_mono")
        if first is not None and last is not None and span and span > 0:
            verdict["cpu_percent"] = round((last - first) / span * 100, 2)

    # ---- 机器人侧 ----
    if summary:
        connected = summary.get("clients_connected") or 0
        errors = summary.get("errors")
        verdict["clients_connected"] = connected
        verdict["bot_errors"] = errors
        if connected < clients:
            verdict["reasons"].append(
                f"只有 {connected}/{clients} 个客户端连上（有新连接 5s 内没握手）"
            )
        if errors:
            verdict["reasons"].append(f"机器人报错 {errors} 次")
        if summary.get("error_samples"):
            verdict["error_samples"] = summary["error_samples"][:3]
    else:
        verdict["reasons"].append("机器人没有写出汇总文件")

    # ---- 归因 ----
    server_bad = any("服务端" in r for r in verdict["reasons"]) or verdict.get("server_crashed")
    bot_bad = any("机器人" in r or "客户端" in r for r in verdict["reasons"])
    verdict["blame"] = "both" if server_bad and bot_bad else (
        "server" if server_bad else ("bot" if bot_bad else "")
    )
    return verdict


# ---------------------------------------------------------------- 跑一轮


def run_one(args, clients: int, rep: int, sample_s: float,
            server_cpus: list[int], bot_cpus: list[int]) -> dict:
    name = scenario_name(clients, rep)
    log_path = args.log_dir / f"{name}.log"
    bot_json = args.run_dir / f"{name}.json"
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.mkdir(parents=True, exist_ok=True)

    duration = WARMUP_S + sample_s
    ramp = ramp_for(clients)
    result: dict = {
        "scenario": name,
        "clients": clients,
        "rep": rep,
        "warmup_s": WARMUP_S,
        "sample_s": sample_s,
        "duration_s": duration,
        "ramp": ramp,
        "entities": {"players": FIXED_PLAYERS, "enemies": FIXED_ENEMIES,
                     "bullets": FIXED_BULLETS},
    }

    result["system_cpu_before"] = system_cpu_percent(0.3)
    started = time.time()

    with log_path.open("w", encoding="utf-8") as srvlog:
        server = subprocess.Popen(
            build_server_cmd(args, name),
            cwd=PROJECT_ROOT, stdout=srvlog, stderr=subprocess.STDOUT,
        )
        result["server_affinity_ok"] = bind(server.pid, server_cpus)

        bot_log = args.log_dir / f"{name}.bot.log"
        try:
            time.sleep(args.startup)
            with bot_log.open("w", encoding="utf-8") as blog:
                bot = subprocess.Popen(
                    build_bot_cmd(args, clients, ramp, duration, bot_json),
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
                server.wait(timeout=10)

    result["seconds"] = round(time.time() - started, 1)
    result["system_cpu_after"] = system_cpu_percent(0.3)

    summary = None
    if bot_json.exists():
        try:
            summary = json.loads(bot_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result["error"] = f"机器人 JSON 解析失败：{exc}"
    else:
        result["error"] = result.get("error") or "机器人没有写出汇总文件"

    if summary:
        for key in ("snapshots", "snapshots_per_s", "interval_p50_ms",
                    "rtt_p50_ms", "rtt_p95_ms", "rtt_p99_ms"):
            result[key] = summary.get(key)

    rows = read_scenario_rows(args.metrics, name)
    result["metric_rows"] = count_rows(args.metrics, name)
    result["server_crashed"] = CRASH_MARKER in log_path.read_text(
        encoding="utf-8", errors="replace")
    if result["server_crashed"]:
        result["error"] = result.get("error") or "服务端 tick loop 崩溃"

    verdict = analyze(rows, summary, clients)
    result.update(verdict)
    # `error` 只在失败路径才被赋值，所以这里统一用 get —— 否则成功那一轮会 KeyError
    error = result.get("error")
    if error and error not in verdict["reasons"]:
        verdict["reasons"].append(error)
    result["ok"] = not verdict["reasons"]
    return result


# ---------------------------------------------------------------- 主流程


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E2 并发数实验（绑核 + 加到失败为止）")
    parser.add_argument("--port", type=int, default=9530)
    parser.add_argument("--tiers", default="", help="只跑这些档，如 10,20,50；默认按阶梯自动加")
    parser.add_argument("--reps", type=int, default=2, help="每档轮数")
    parser.add_argument("--sample", type=float, default=SAMPLE_S, help="采样秒数")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bot-seed", type=int, default=99)
    parser.add_argument("--startup", type=float, default=2.0, help="服务端起后等几秒再上机器人")
    parser.add_argument("--teardown", type=float, default=1.5)
    parser.add_argument("--max-tier", type=int, default=max(EXTEND_TIERS))
    parser.add_argument("--no-bind", action="store_true", help="不绑核（仅用于排查）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--metrics", type=Path,
                        default=PROJECT_ROOT / "data" / "server_metrics.csv")
    parser.add_argument("--run-dir", type=Path, default=PROJECT_ROOT / "data" / "runs")
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "data" / "logs")
    return parser.parse_args()


def plan_tiers(args) -> list[int]:
    if args.tiers:
        return [int(c) for c in args.tiers.split(",") if c.strip()]
    return [c for c in (*DEFAULT_TIERS, *EXTEND_TIERS) if c <= args.max_tier]


def main() -> None:
    args = parse_args()
    tiers = plan_tiers(args)
    server_cpus, bot_cpus = ([], []) if args.no_bind else detect_affinity()

    log(f"档位（连接数）: {tiers}")
    log(f"实体固定: {FIXED_PLAYERS} 玩家 + {FIXED_ENEMIES} 敌机 + {FIXED_BULLETS} 子弹"
        f"（--fixed-entities，D-029）")
    log(f"每档 {args.reps} 轮，预热 {WARMUP_S:g}s + 采样 {args.sample:g}s")
    log(f"绑核: 服务端 {server_cpus or '不绑'} / 机器人 {bot_cpus or '不绑'}")

    estimated = sum(args.reps * (WARMUP_S + args.sample + args.startup + args.teardown)
                    for _ in tiers)
    log(f"预计耗时约 {estimated / 60:.1f} 分钟（不含失败后的补跑）")

    if args.dry_run:
        for clients in tiers:
            for rep in range(1, args.reps + 1):
                log(f"  {scenario_name(clients, rep)}  ramp={ramp_for(clients)}/s")
        return

    if not args.metrics.exists():
        raise SystemExit(f"指标文件不存在：{args.metrics}")
    # 开跑前先探一次表头：schema 不一致要在这里就炸，别等跑完
    MetricsRecorder(args.metrics, scenario_id="E2-probe").close()

    manifest = {
        "experiment": "E2",
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entities": {"players": FIXED_PLAYERS, "enemies": FIXED_ENEMIES,
                     "bullets": FIXED_BULLETS},
        "fixed_entities": True,
        "warmup_s": WARMUP_S,
        "sample_s": args.sample,
        "reps": args.reps,
        "server_cpus": server_cpus,
        "bot_cpus": bot_cpus,
        "tiers_planned": tiers,
        "runs": [],
        "verdict": {},
    }

    failing_at: int | None = None
    for clients in tiers:
        reps: list[dict] = []
        for rep in range(1, args.reps + 1):
            log(f"--- {scenario_name(clients, rep)} 开始 ---")
            result = run_one(args, clients, rep, args.sample, server_cpus, bot_cpus)
            reps.append(result)
            manifest["runs"].append(result)
            status = "✅" if result["ok"] else "❌"
            log(f"{status} {result['scenario']}  tick={result.get('tick_mean_ms')}ms  "
                f"cpu={result.get('cpu_percent')}%  用时 {result.get('seconds')}s"
                + (f"  归因={result.get('blame')}" if not result["ok"] else ""))
            if not result["ok"]:
                for reason in result.get("reasons", []):
                    log(f"     · {reason}")

        # 两轮偏差 > 10% → 补一轮长采样
        values = [r.get("tick_mean_ms") for r in reps if r.get("tick_mean_ms")]
        if len(values) >= 2:
            lo, hi = min(values), max(values)
            deviation = (hi - lo) / lo if lo else 0.0
            manifest["verdict"].setdefault(str(clients), {})["deviation"] = round(deviation, 3)
            if deviation > DEVIATION_LIMIT:
                log(f"⚠️ {clients} 档两轮偏差 {deviation:.1%} > "
                    f"{DEVIATION_LIMIT:.0%}，补跑一轮 {EXTENDED_SAMPLE_S:g}s 采样")
                extra = run_one(args, clients, args.reps + 1, EXTENDED_SAMPLE_S,
                                server_cpus, bot_cpus)
                manifest["runs"].append(extra)
                manifest["verdict"][str(clients)]["extended_rep"] = extra["scenario"]

        ok_all = all(r["ok"] for r in reps)
        manifest["verdict"].setdefault(str(clients), {})["ok"] = ok_all
        if not ok_all:
            failing_at = clients
            blames = {r.get("blame") for r in reps if not r["ok"]}
            manifest["verdict"][str(clients)]["blame"] = sorted(b for b in blames if b)
            log(f"⛔ {clients} 档失败，按「首次失败即停」结束加档")
            break
        log(f"✔ {clients} 档通过")

    manifest["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["failing_at"] = failing_at
    manifest["passed_tiers"] = [c for c in tiers
                                if manifest["verdict"].get(str(c), {}).get("ok")]
    manifest_path = args.run_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"清单 -> {manifest_path}")
    if failing_at is None:
        log("全部档位通过，未找到失败点")
    else:
        log(f"失败点：{failing_at} 个连接")


if __name__ == "__main__":
    main()