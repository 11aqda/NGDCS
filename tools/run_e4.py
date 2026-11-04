"""E4：网络损伤对同步质量的影响 —— 丢包 / 延迟 / 抖动 vs 插值误差。

## 为什么用自研 TCP 代理而不是 netem

原计划 Ubuntu VM + `tc netem`。本机没有 WSL 发行版，装一个要下载并可能重启，
不该为一个实验去改系统。改用用户态代理 `tools/netem_proxy.py`（方案 B，
用户已确认；`bot --sim-loss` **不作为主实验**）。

## ⚠️ TCP 上"丢包"的真实表现（论文必须写清）

我们的传输层是 TCP，所以 netem 式的 IP 层丢包，应用层**不会少收快照**，
只会**来晚**（重传要等一个 RTO，Linux 最小 200 ms）。
本代理因此把"丢包率"实现为**按概率给数据块加一个 RTO 量级的延迟**。

这决定了结果的形状：丢包的影响**主要体现在尾部（P95）**，均值变化很小。

## 自变量

| 轴 | 档位 |
|---|---|
| 丢包率 | 0 / 5 / 10 / 20 %（每次 +200 ms 等效重传延迟） |
| 延迟 | 0 / 50 / 100 / 200 ms（**每个方向**，RTT 约 +2×） |
| 抖动（对照） | 0 / 50 / 100 ms（固定 delay=0、loss=0） |

控制变量：**8 玩家**、20 Hz、binary 编码器、30 敌机 / 200 子弹（`--fixed-entities`）。

抖动不属于原设计，但预实验发现**恒定延迟几乎不影响插值误差**，
真正推动误差的是到达时间的**方差**。所以加一组抖动对照，
否则图 6-9（延迟 vs 误差）会是一条平线、讲不出东西。

## 因变量

- `err_px_mean` / `err_px_p95`（主要看 P95，原因见上）
- `rtt_p50_ms`（标定实际达成的延迟，代理有 ±20 ms 的定时器误差）
- `interval_p95_ms`（快照到达间隔的尾部，直接对应"卡顿"）

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.run_e4           # 全量（约 21 分钟）
    .venv\\Scripts\\python.exe -X utf8 -m tools.run_e4 --quick   # 冒烟（约 2 分钟）
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
    PROJECT_ROOT,
    bind,
    detect_affinity,
    ramp_for,
)

# 按 03-实验清单 §E4：丢包 0/5/10/20、延迟 0/50/100/200、8 人
LOSS_TIERS = (0, 5, 10, 20)
DELAY_TIERS = (0, 50, 100, 200)
JITTER_TIERS = (0, 50, 100)   # 对照组
E4_PLAYERS = 8
WARMUP_S = 5.0
SAMPLE_S = 60.0


def log(message: str) -> None:
    print(f"[e4 {time.strftime('%H:%M:%S')}] {message}", flush=True)


def condition_name(loss: float, delay: float, jitter: float = 0.0) -> str:
    if jitter:
        return f"E4-j{jitter:g}"
    return f"E4-l{loss:g}-d{delay:g}"


def run_one(args, loss: float, delay: float, jitter: float,
            server_cpus: list[int], bot_cpus: list[int]) -> dict:
    name = condition_name(loss, delay, jitter)
    log_path = args.log_dir / f"{name}.log"
    bot_json = args.run_dir / f"{name}.json"
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.mkdir(parents=True, exist_ok=True)

    duration = WARMUP_S + args.sample
    server_cmd = [
        sys.executable, "-X", "utf8", "-u", "-m", "server.main",
        str(args.server_port),
        "--enemies", str(FIXED_ENEMIES),
        "--bullets", str(FIXED_BULLETS),
        "--fixed-entities",
        "--no-metrics", "--no-stats",
    ]
    proxy_cmd = [
        sys.executable, "-X", "utf8", "-u", "-m", "tools.netem_proxy",
        "--listen", str(args.proxy_port),
        "--upstream", str(args.server_port),
        "--delay-ms", str(delay),
        "--jitter-ms", str(jitter),
        "--loss-pct", str(loss),
        "--duration", str(int(duration) + 20),
        "--seed", str(args.seed),
    ]
    bot_cmd = [
        sys.executable, "-X", "utf8", "-u", "-m", "bot.main",
        "--port", str(args.proxy_port),
        "--clients", str(E4_PLAYERS),
        "--duration", str(int(duration)),
        "--ramp", str(ramp_for(E4_PLAYERS)),
        "--seed", str(args.bot_seed),
        "--err-px",
        "--out", str(bot_json),
    ]

    log(f"▶ {name}：丢包 {loss:g}% 延迟 {delay:g}ms 抖动 {jitter:g}ms，采样 {args.sample:.0f}s")
    server = proxy = None
    try:
        with log_path.open("w", encoding="utf-8") as srvlog:
            server = subprocess.Popen(server_cmd, cwd=PROJECT_ROOT,
                                      stdout=srvlog, stderr=subprocess.STDOUT)
            bind(server.pid, server_cpus)
            proxy_log = args.log_dir / f"{name}.proxy.log"
            proxy = subprocess.Popen(proxy_cmd, cwd=PROJECT_ROOT,
                                     stdout=proxy_log.open("w", encoding="utf-8"),
                                     stderr=subprocess.STDOUT)
            time.sleep(args.startup)
            bot_log = args.log_dir / f"{name}.bot.log"
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
        for proc in (proxy, server):
            if proc is None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
        time.sleep(0.5)

    result: dict = {
        "condition": name, "loss_pct": loss, "delay_ms": delay,
        "jitter_ms": jitter, "players": E4_PLAYERS, "sample_s": args.sample,
    }
    if not bot_json.exists():
        result["error"] = "机器人没有写出汇总文件"
        result["ok"] = False
        return result

    summary = json.loads(bot_json.read_text(encoding="utf-8"))
    for key in ("err_px_mean", "err_px_p95", "err_px_max", "err_px_samples",
                "rtt_p50_ms", "interval_p50_ms", "interval_p95_ms",
                "clients_connected", "errors"):
        result[key] = summary.get(key)
    result["ok"] = isinstance(result.get("err_px_p95"), (int, float))
    if not result["ok"]:
        result["error"] = "没有 err_px 样本"

    log(
        f"  {name}: err_mean={result.get('err_px_mean')} "
        f"err_p95={result.get('err_px_p95')} "
        f"rtt={result.get('rtt_p50_ms')}ms "
        f"interval_p95={result.get('interval_p95_ms')}ms"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E4 网络损伤实验（用户态代理）")
    parser.add_argument("--server-port", type=int, default=9620)
    parser.add_argument("--proxy-port", type=int, default=9720)
    parser.add_argument("--log-dir", type=Path,
                        default=PROJECT_ROOT / "data" / "logs" / "e4")
    parser.add_argument("--run-dir", type=Path,
                        default=PROJECT_ROOT / "data" / "runs")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bot-seed", type=int, default=99)
    parser.add_argument("--startup", type=float, default=2.0)
    parser.add_argument("--sample", type=float, default=SAMPLE_S)
    parser.add_argument("--quick", action="store_true",
                        help="冒烟：2 个条件 × 20 s")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server_cpus, bot_cpus = detect_affinity()
    log(f"绑核：服务端 {server_cpus}，机器人 {bot_cpus}")

    conditions: list[tuple[float, float, float]] = []
    if args.quick:
        args.sample = 20.0
        conditions = [(0, 0, 0), (20, 0, 0)]
    else:
        # 主矩阵：丢包 × 延迟（03 §E4 的定义）
        for loss in LOSS_TIERS:
            for delay in DELAY_TIERS:
                conditions.append((loss, delay, 0.0))
        # 抖动对照：预实验发现恒定延迟几乎不影响误差，真正有害的是方差
        for jitter in JITTER_TIERS:
            if jitter:
                conditions.append((0.0, 0.0, float(jitter)))

    results: list[dict] = []
    for index, (loss, delay, jitter) in enumerate(conditions, start=1):
        log(f"[{index}/{len(conditions)}]")
        results.append(run_one(args, loss, delay, jitter, server_cpus, bot_cpus))

    args.run_dir.mkdir(parents=True, exist_ok=True)
    path = args.run_dir / "E4-manifest.json"
    path.write_text(
        json.dumps(
            {"experiment": "E4", "players": E4_PLAYERS, "sample_s": args.sample,
             "warmup_s": WARMUP_S, "loss_tiers": LOSS_TIERS,
             "delay_tiers": DELAY_TIERS, "jitter_tiers": JITTER_TIERS,
             "transport": "TCP（丢包表现为重传延迟，不是丢帧）",
             "runs": results},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    log(f"已写入 {path}")

    log("=" * 78)
    log(f"{'条件':<16}{'err均值':>9}{'err P95':>9}{'RTT ms':>9}{'间隔P95':>9}")
    for item in results:
        if not item.get("ok"):
            log(f"{item['condition']:<16}  失败：{item.get('error')}")
            continue
        log(
            f"{item['condition']:<16}{item['err_px_mean']:>9.2f}"
            f"{item['err_px_p95']:>9.2f}{item['rtt_p50_ms']:>9.1f}"
            f"{item['interval_p95_ms']:>9.1f}"
        )
    log("=" * 78)
    log("下一步：python -X utf8 -m tools.plot --figures e4")


if __name__ == "__main__":
    main()