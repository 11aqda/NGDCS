"""阶段 1 · 第 7 步（7a）：观察者机器人。

一个进程开 N 个“假客户端”：连接、收 welcome、收 snapshot、统计指标。
本阶段**不发输入、不改服务端**，只验证：

    - N 个连接能不能同时连上
    - 每个机器人是不是稳定收到 20 Hz 快照
    - 广播的带宽 / 间隔 / 错误数

用法：
    .venv\\Scripts\\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --ramp 5
    .venv\\Scripts\\python.exe -X utf8 -m bot.main --clients 50 --duration 60 --out bot_run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from protocol.framing import HEADER, ProtocolError, recv_frame_async
from protocol.messages import S_SNAPSHOT, S_WELCOME


@dataclass
class BotResult:
    connected: bool = False
    snapshots: int = 0
    bytes: int = 0
    intervals: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def run_bot(host: str, port: int, duration: float) -> BotResult:
    """一个观察者机器人：连接后只收快照，不发送任何消息。"""
    result = BotResult()

    try:
        reader, writer = await asyncio.open_connection(host, port)
        result.connected = True

        try:
            welcome = await recv_frame_async(reader)
            if welcome is None or welcome.msg_type != S_WELCOME:
                result.errors.append("no S_WELCOME")
                return result

            deadline = time.perf_counter() + duration
            last_snapshot_at = None

            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break

                try:
                    frame = await asyncio.wait_for(
                        recv_frame_async(reader), timeout=remaining
                    )
                except asyncio.TimeoutError:
                    break

                if frame is None:
                    result.errors.append("server closed")
                    break
                if frame.msg_type != S_SNAPSHOT:
                    continue

                now = time.perf_counter()
                if last_snapshot_at is not None:
                    result.intervals.append(now - last_snapshot_at)
                last_snapshot_at = now

                result.snapshots += 1
                result.bytes += HEADER.size + len(frame.payload)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass

    except (OSError, ProtocolError) as exc:
        result.errors.append(repr(exc))

    return result


async def run_farm(args: argparse.Namespace) -> list[BotResult]:
    """按 ramp 速率启动 N 个机器人，等它们全部结束。"""
    tasks = []
    for _ in range(args.clients):
        tasks.append(
            asyncio.create_task(run_bot(args.host, args.port, args.duration))
        )
        if args.ramp > 0:
            await asyncio.sleep(1.0 / args.ramp)
    return await asyncio.gather(*tasks)


def percentile(values: list[float], p: float) -> float:
    """简单的分位数：p=0.5 中位数，p=0.95 是 95% 分位。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * p))
    return ordered[index]


def summarize(
    results: list[BotResult], args: argparse.Namespace, elapsed: float
) -> dict:
    connected = sum(1 for r in results if r.connected)
    snapshots = sum(r.snapshots for r in results)
    total_bytes = sum(r.bytes for r in results)
    intervals = [value for r in results for value in r.intervals]
    errors = [error for r in results for error in r.errors]

    return {
        "host": args.host,
        "port": args.port,
        "clients_requested": args.clients,
        "clients_connected": connected,
        "duration_per_bot_s": args.duration,
        "ramp_per_s": args.ramp,
        "elapsed_s": round(elapsed, 3),
        "snapshots": snapshots,
        "snapshots_per_s": round(snapshots / elapsed, 2) if elapsed else 0,
        "bytes": total_bytes,
        "bytes_per_s": round(total_bytes / elapsed, 2) if elapsed else 0,
        "avg_snapshots_per_bot": round(snapshots / connected, 2) if connected else 0,
        "interval_p50_ms": round(percentile(intervals, 0.50) * 1000, 3),
        "interval_p95_ms": round(percentile(intervals, 0.95) * 1000, 3),
        "errors": len(errors),
        "error_samples": errors[:5],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="阶段 1 观察者机器人")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9527)
    parser.add_argument("--clients", type=int, default=20, help="机器人数量")
    parser.add_argument(
        "--duration", type=float, default=10.0, help="每个机器人的运行秒数"
    )
    parser.add_argument(
        "--ramp", type=float, default=5.0, help="每秒启动几个；0 表示一次性全部启动"
    )
    parser.add_argument("--out", default="", help="把汇总写到 JSON 文件")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    results = await run_farm(args)
    elapsed = time.perf_counter() - started

    summary = summarize(results, args, elapsed)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"[bot] summary written to {path}")


if __name__ == "__main__":
    try:
        asyncio.run(async_main(parse_args()))
    except KeyboardInterrupt:
        print("\n[bot] stopped")
