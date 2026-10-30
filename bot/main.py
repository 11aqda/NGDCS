"""阶段 1 · 第 7 步：机器人农场（CLI + 指标汇总）。

一个进程开 N 个“假客户端”，用于压测与实验数据采集。
单个机器人的逻辑在 bot/agent.py（连接、输入、心跳、收发），本文件只负责
**开多少个、怎么开、跑完怎么汇总**。

    --input-hz 0   就是 7a 的观察者机器人（只收不发）
    --input-hz 20  是 7b 的输入机器人（默认）

7b 起机器人**默认发心跳**：服务端有 15 秒超时（02 §7），不发心跳的客户端
15 秒后会被踢。想复现 7a 的「纯广播基线」就两边一起关：

    server:  python -m server.main --timeout 0
    bot:     python -m bot.main --clients 50 --duration 60 --input-hz 0 --heartbeat 0

用法：
    .venv\\Scripts\\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --ramp 5
    .venv\\Scripts\\python.exe -X utf8 -m bot.main --clients 50 --duration 60 --out bot_run.json
    .venv\\Scripts\\python.exe -X utf8 -m bot.main --input-hz 0 --heartbeat 0 --timeout 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from bot.agent import BotConfig, BotResult, run_farm

__all__ = ["BotConfig", "BotResult", "percentile", "summarize", "main"]


def percentile(values: list[float], p: float) -> float:
    """简单的分位数：p=0.5 中位数，p=0.95 是 95% 分位。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * p))
    return ordered[index]


def summarize(
    results: list[BotResult],
    config: BotConfig,
    clients: int,
    ramp: float,
    elapsed: float,
) -> dict:
    connected = sum(1 for r in results if r.connected)
    snapshots = sum(r.snapshots for r in results)
    total_bytes = sum(r.bytes for r in results)
    intervals = [value for r in results for value in r.intervals]
    rtts = [value for r in results for value in r.rtts]
    errors = [error for r in results for error in r.errors]
    inputs_sent = sum(r.inputs_sent for r in results)
    heartbeats_sent = sum(r.heartbeats_sent for r in results)
    heartbeats_acked = sum(r.heartbeats_acked for r in results)

    return {
        "host": config.host,
        "port": config.port,
        "clients_requested": clients,
        "clients_connected": connected,
        "duration_per_bot_s": config.duration,
        "ramp_per_s": ramp,
        "input_hz": config.input_hz,
        "heartbeat_s": config.heartbeat,
        "seed": config.seed,
        "elapsed_s": round(elapsed, 3),
        "snapshots": snapshots,
        "snapshots_per_s": round(snapshots / elapsed, 2) if elapsed else 0,
        "bytes": total_bytes,
        "bytes_per_s": round(total_bytes / elapsed, 2) if elapsed else 0,
        "avg_snapshots_per_bot": round(snapshots / connected, 2) if connected else 0,
        "inputs_sent": inputs_sent,
        "inputs_per_s": round(inputs_sent / elapsed, 2) if elapsed else 0,
        "heartbeats_sent": heartbeats_sent,
        "heartbeats_acked": heartbeats_acked,
        "interval_p50_ms": round(percentile(intervals, 0.50) * 1000, 3),
        "interval_p95_ms": round(percentile(intervals, 0.95) * 1000, 3),
        "rtt_p50_ms": round(percentile(rtts, 0.50) * 1000, 3),
        "rtt_p95_ms": round(percentile(rtts, 0.95) * 1000, 3),
        # P99 供图 6-6（RTT 分位数曲线）：只看均值会掩盖尾部抖动，
        # 而实时同步最怕的恰恰是尾部（卡一下在客户端就是"瞬移"）。
        "rtt_p99_ms": round(percentile(rtts, 0.99) * 1000, 3),
        "errors": len(errors),
        "error_samples": errors[:5],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="阶段 1 机器人（输入 + 心跳）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9527)
    parser.add_argument("--clients", type=int, default=20, help="机器人数量")
    parser.add_argument(
        "--duration", type=float, default=10.0, help="每个机器人的运行秒数"
    )
    parser.add_argument(
        "--ramp", type=float, default=5.0, help="每秒启动几个；0 表示一次性全部启动"
    )
    parser.add_argument(
        "--input-hz",
        type=float,
        default=20.0,
        help="每个机器人每秒发几次 C_INPUT；0 = 观察者（不发输入）",
    )
    parser.add_argument(
        "--heartbeat",
        type=float,
        default=5.0,
        help="心跳间隔秒数；0 = 不发（需服务端 --timeout 0，否则会被踢）",
    )
    parser.add_argument(
        "--key-hold", type=float, default=0.5, help="一个按键按住多久才换"
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="按键随机种子；0 = 系统随机，非 0 = 可复现"
    )
    parser.add_argument("--out", default="", help="把汇总写到 JSON 文件")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    config = BotConfig(
        host=args.host,
        port=args.port,
        duration=args.duration,
        input_hz=args.input_hz,
        heartbeat=args.heartbeat,
        key_hold=args.key_hold,
        seed=args.seed,
    )

    started = time.perf_counter()
    results = await run_farm(config, args.clients, args.ramp)
    elapsed = time.perf_counter() - started

    summary = summarize(results, config, args.clients, args.ramp, elapsed)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"[bot] summary written to {path}")


def main() -> None:
    try:
        asyncio.run(async_main(parse_args()))
    except KeyboardInterrupt:
        print("\n[bot] stopped")


if __name__ == "__main__":
    main()