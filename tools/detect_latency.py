"""E8 断线检测时效：心跳超时 3 / 5 / 10 s 各 3 轮 + kill 对照 1 轮。

## 测什么

**从"客户端不再发心跳"到"服务端把它踢掉"之间隔了多久。**

这个延迟决定了玩家掉线后，别人眼里的"幽灵"会飘多久 ——
太短会误判（网络抖动一下就踢人），太长则队友看着一个不动的人在开枪。

## 两种断线方式必须分开测

| 方式 | 做法 | 服务端怎么感知 | 期望延迟 |
|---|---|---|---|
| **freeze**（主测） | 挂起客户端进程（`psutil.suspend()`） | **只能靠心跳超时** | ≈ 超时值 + 收割周期 |
| **kill**（对照） | 直接杀进程 | 内核发 FIN/RST，`recv` 立刻返回 EOF | ≈ 0 |

**为什么 freeze 才是主测**：真实掉线里最常见的不是"程序崩了"（那会正常关连接），
而是**断网 / 卡死 / 进程被挂起** —— 连接还占着、但一个字节都不来。
这种情况服务端**只能靠超时兜底**，而 kill 那种由内核通知的路径快得没有测量意义。

## 为什么每档要跑 3 轮

`reap_timeouts()` **每秒才检查一次**（`server/main.py:271`，注释写明"不是每 tick"）。
所以检测时刻落在哪个 1 秒窗口里是随机的 —— **单轮测出来的数会带着 0~1 s 的量化误差**，
3 轮才能看出这个抖动的范围。

## 用法

    .venv\\Scripts\\python.exe -X utf8 -m tools.detect_latency
    .venv\\Scripts\\python.exe -X utf8 -m tools.detect_latency --timeouts 3 --reps 1
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEFT_MARKER = "[server] player 1 left"


def log(message: str) -> None:
    print(f"[e8] {message}", flush=True)


def build_server_cmd(args, timeout: float) -> list[str]:
    return [
        sys.executable, "-X", "utf8", "-u", "-m", "server.main",
        str(args.port),
        "--timeout", str(timeout),
        # 实体置零：E8 只关心断线检测，不需要快照负载，跑起来也更快
        "--enemies", "0",
        "--bullets", "0",
        "--seed", "1",
        "--no-metrics",
        "--no-stats",
        "--fixed-entities",
    ]


def build_bot_cmd(args, duration: float, out_path: Path) -> list[str]:
    return [
        sys.executable, "-X", "utf8", "-u", "-m", "bot.main",
        "--port", str(args.port),
        "--clients", "1",
        "--duration", str(int(duration)),
        "--ramp", "1",
        "--heartbeat", "1",   # 1 Hz 心跳：超时 3 s = 3 个心跳周期，与 02 §7 一致
        "--input-hz", "0",
        "--seed", str(args.bot_seed),
        "--out", str(out_path),
    ]


def wait_for_marker(path: Path, marker: str, deadline_s: float) -> float | None:
    """轮询日志直到出现 marker，返回首次看到的时刻（perf_counter）。"""
    end = time.perf_counter() + deadline_s
    while time.perf_counter() < end:
        try:
            if marker in path.read_text(encoding="utf-8", errors="replace"):
                return time.perf_counter()
        except OSError:
            pass
        time.sleep(0.01)  # 10 ms 轮询：检测时刻的分辨率就是它，比 1 s 收割周期小得多
    return None


def suspend(pid: int) -> bool:
    try:
        import psutil

        psutil.Process(pid).suspend()
        return True
    except Exception:  # noqa: BLE001 - 挂不起来就不是 freeze，本轮作废但要记录
        return False


def run_one(args, timeout: float, mode: str) -> dict:
    """mode: freeze（挂起，靠超时检测）/ kill（杀进程，内核通知）。"""
    log_path = args.log_dir / f"E8-t{timeout:g}-{mode}.log"
    bot_json = args.run_dir / f"E8-t{timeout:g}-{mode}.json"
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    result: dict = {"timeout_s": timeout, "mode": mode, "ok": False}
    duration = timeout + 30

    with log_path.open("w", encoding="utf-8") as srvlog:
        server = subprocess.Popen(build_server_cmd(args, timeout), cwd=PROJECT_ROOT,
                                  stdout=srvlog, stderr=subprocess.STDOUT)
        bot = None
        try:
            # ① 先等服务端真的在监听，再去连 —— 顺序搞反会白等 10 秒
            if wait_for_marker(log_path, "listening on", 10) is None:
                result["error"] = "服务端没起来"
                return result

            # ② 起客户端，等它连上
            bot = subprocess.Popen(build_bot_cmd(args, duration, bot_json),
                                   cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            if wait_for_marker(log_path, "player 1 joined", 15) is None:
                result["error"] = "客户端没连上"
                return result

            # ③ 先让它正常发几个心跳，确认是"活的"，再动手
            time.sleep(args.settle)

            started = time.perf_counter()
            if mode == "freeze":
                result["suspended"] = suspend(bot.pid)
                if not result["suspended"]:
                    result["error"] = "挂起客户端失败（不是 root/权限问题？）"
                    return result
            else:
                bot.kill()

            found = wait_for_marker(log_path, LEFT_MARKER, timeout + 15)
            if found is None:
                result["error"] = f"等了 {timeout + 15:.0f}s 仍未检测到断开"
                return result
            result["latency_ms"] = round((found - started) * 1000, 1)
            result["ok"] = True
            return result
        finally:
            if bot is not None:
                try:
                    import psutil

                    psutil.Process(bot.pid).resume()  # 挂起的进程要先解挂才能杀干净
                except Exception:  # noqa: BLE001
                    pass
                try:
                    bot.kill()
                except Exception:  # noqa: BLE001
                    pass
                bot.wait(timeout=10)
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                server.kill()
                server.wait(timeout=10)


def summarize(rows: list[dict]) -> list[dict]:
    """按超时值分组统计（freeze 模式），kill 单独列。"""
    groups: dict[tuple[float, str], list[float]] = {}
    for row in rows:
        if not row.get("ok"):
            continue
        groups.setdefault((row["timeout_s"], row["mode"]), []).append(row["latency_ms"])

    out = []
    for (timeout, mode), values in sorted(groups.items()):
        out.append({
            "timeout_s": timeout,
            "mode": mode,
            "runs": len(values),
            "mean_ms": round(statistics.mean(values), 1),
            "min_ms": round(min(values), 1),
            "max_ms": round(max(values), 1),
            "overhead_ms": round(statistics.mean(values) - timeout * 1000, 1),
        })
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E8 断线检测时效（freeze 为主，kill 作对照）")
    parser.add_argument("--port", type=int, default=9540)
    parser.add_argument("--timeouts", default="3,5,10", help="心跳超时秒数，逗号分隔")
    parser.add_argument("--reps", type=int, default=3, help="freeze 每档轮数")
    parser.add_argument("--kill-reps", type=int, default=1, help="kill 对照轮数")
    parser.add_argument("--settle", type=float, default=2.5, help="连上后先等几秒再动手")
    parser.add_argument("--bot-seed", type=int, default=99)
    parser.add_argument("--run-dir", type=Path, default=PROJECT_ROOT / "data" / "runs")
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "data" / "logs")
    return parser.parse_args()


def main() -> None:
    global args
    args = parse_args()
    timeouts = [float(t) for t in args.timeouts.split(",") if t.strip()]
    log(f"freeze 主测：超时 {timeouts} 各 {args.reps} 轮；kill 对照 {args.kill_reps} 轮")

    rows: list[dict] = []
    for timeout in timeouts:
        for rep in range(1, args.reps + 1):
            log(f"--- freeze 超时 {timeout:g}s 第 {rep} 轮 ---")
            row = run_one(args, timeout, "freeze")
            rows.append(row)
            if row.get("ok"):
                log(f"    ✅ 检测延迟 {row['latency_ms']} ms"
                    f"（超时 {timeout * 1000:.0f} ms，超出 {row['latency_ms'] - timeout * 1000:+.0f} ms）")
            else:
                log(f"    ❌ {row.get('error')}")

    for timeout in timeouts[:1]:  # 对照只做最小超时那一档即可
        for rep in range(1, args.kill_reps + 1):
            log(f"--- kill 对照 超时 {timeout:g}s 第 {rep} 轮 ---")
            row = run_one(args, timeout, "kill")
            rows.append(row)
            log(f"    {'✅ ' + str(row['latency_ms']) + ' ms' if row.get('ok') else '❌ ' + str(row.get('error'))}")

    stats = summarize(rows)
    print()
    log("=== 结果 ===")
    log(f"{'超时(s)':>8}{'方式':>8}{'轮数':>5}{'均值(ms)':>10}{'最小':>8}{'最大':>8}{'超出超时':>10}")
    for s in stats:
        log(f"{s['timeout_s']:>8.0f}{s['mode']:>8}{s['runs']:>5}"
            f"{s['mean_ms']:>10.1f}{s['min_ms']:>8.1f}{s['max_ms']:>8.1f}"
            f"{s['overhead_ms']:>+10.1f}")

    manifest = {
        "experiment": "E8",
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "heartbeat_hz": 1,
        "runs": rows,
        "summary": stats,
    }
    path = args.run_dir / "E8-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"清单 -> {path}")


if __name__ == "__main__":
    main()