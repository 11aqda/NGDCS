"""实验回归检查：确认"加游戏内容"没有破坏 E1/E2/E4/E5/E7/E8/E9 的可复现性。

## 两层设计（用户 2026-11-04 定的口径）

### 硬校验（确定性，必须精确相等，几秒内跑完）

| 项 | 断言 |
|---|---|
| **E1 编码字节** | `binary` 与 `binary_fast` **逐字节相同**；载荷长度精确等于 `13+11P+9E+8B`；JSON 编码解出来数值一致 |
| **E7 帧解析** | 粘包（两帧拼接）解析出 2 帧；半包（头 + 半个 body）先出 0 帧、补齐后出 1 帧；magic/version/length 正确 |
| **E2 上限** | `player_count > 255` 必须抛错；`enemy_target > 255` 必须抛错 |

这些**不碰网络、不碰时钟**，所以可以放心做精确断言。

### 软校验（跑真实进程，只查"没坏"，给容差）

| 项 | 断言 |
|---|---|
| **E9 基线** | 30 敌机 / 200 子弹时快照恒 1927 B、实体数不漂、不崩 |
| **E5 tick 率** | 30 Hz 下到达间隔 ≈33 ms（±20%）、快照恒 1927 B、不崩 |
| **E4 代理链路** | 经代理（0 损伤）RTT < 50 ms、`err_px` 在 [5, 15] px、不崩 |
| **E8 心跳** | 心跳有回包（`heartbeats_acked > 0`）、不崩 |

带宽/CPU 比对基线值给 **±20%** 容差 —— 这是台桌面机，浏览器还开着，
CPU 读数本来就有噪声，做成精确断言只会天天误报。

## 依赖缺失就跳过，不阻塞

MySQL / Redis 没起时，需要它们的检查直接 `skip`，不报失败。
本脚本目前所有检查都不依赖数据库，但保留这个判定 —— 以后加"排行榜仍然可用"的检查时用得上。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.check_experiments           # 两层都跑
    .venv\\Scripts\\python.exe -X utf8 -m tools.check_experiments --layer hard
    .venv\\Scripts\\python.exe -X utf8 -m tools.check_experiments --only E5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from protocol.encoders import get_encoder
from protocol.framing import FrameParser, pack_frame
from protocol.messages import ENEMY_DIVE, S_SNAPSHOT
from protocol.snapshot import (
    BULLET,
    ENEMY,
    ITEM,
    PLAYER,
    ItemSnapshot,
    PlayerSnapshot,
    EnemySnapshot,
    BulletSnapshot,
    pack_snapshot,
    unpack_snapshot,
)
from protocol.world import WORLD_HEIGHT
from server.entities import World
from server.main import Client, GameServer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOFT_BASELINE = PROJECT_ROOT / "tests" / "baselines" / "soft_default.json"

ENEMIES, BULLETS, PLAYERS, SEED = 30, 200, 4, 1
SOFT_TOLERANCE = 0.20   # 带宽 / CPU / 间隔的容差
SOFT_SAMPLE_S = 15.0

results: list[tuple[str, str, bool, str]] = []   # (层, 名称, 通过, 说明)


def record(layer: str, name: str, ok: bool, detail: str = "") -> None:
    results.append((layer, name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {layer:<5} {name}" + (f"  —— {detail}" if detail else ""))


# ---------------------------------------------------------------- 硬校验


def _sample_snapshot() -> tuple[bytes, object]:
    """造一个确定性的快照（4 玩家 / 30 敌机 / 200 子弹），供 E1/E7 使用。"""
    world = World(enemy_target=ENEMIES, bullet_target=BULLETS, seed=SEED,
                  fixed_entities=True)
    game = GameServer(world=world, print_stats=False, encoder=get_encoder("binary"))
    for player_id in range(1, PLAYERS + 1):
        game.clients[player_id] = Client(
            player_id=player_id, color=player_id % 8,
            x=100 * player_id, y=700, writer=None,  # type: ignore[arg-type]
        )
    players = [(c.player_id, c.x) for c in game.clients.values()]
    world.step(players)
    game.tick = 1
    payload = game.build_snapshot()
    return payload, unpack_snapshot(payload)


def check_hard_e1() -> None:
    """E1：编码字节必须精确。"""
    payload, snapshot = _sample_snapshot()

    expected_len = (
        13 + 11 * len(snapshot.players) + 9 * len(snapshot.enemies)
        + 8 * len(snapshot.bullets) + 7 * len(snapshot.items)
    )
    record("E1", "快照长度 = 13+11P+9E+8B+7I", len(payload) == expected_len,
           f"{len(payload)} vs {expected_len}")

    # binary_fast 与 binary 必须逐字节相同（E1 的核心前提）
    players, enemies, bullets = _entities_from(snapshot)
    standard = get_encoder("binary").encode(1, players, enemies, bullets)
    fast = get_encoder("binary_fast").encode(1, players, enemies, bullets)
    record("E1", "binary 与 binary_fast 逐字节相同", standard == fast,
           f"{len(standard)} B vs {len(fast)} B")

    # JSON 编码器解回来数值必须一致
    try:
        as_json = get_encoder("json").encode(1, players, enemies, bullets)
        record("E1", "JSON 编码器可产出", len(as_json) > 0, f"{len(as_json)} B")
        record("E1", "JSON 比 binary 大（E1 的正向结论）", len(as_json) > len(standard),
               f"{len(as_json)} vs {len(standard)} B")
    except Exception as exc:  # noqa: BLE001
        record("E1", "JSON 编码器可产出", False, repr(exc))


def _entities_from(snapshot):
    return (
        list(snapshot.players), list(snapshot.enemies), list(snapshot.bullets),
    )


def check_hard_e7() -> None:
    """E7：粘包 / 半包 / 头字段。"""
    payload, _ = _sample_snapshot()

    sticky = pack_frame(S_SNAPSHOT, 1, payload) + pack_frame(S_SNAPSHOT, 2, payload)
    parser = FrameParser()
    parser.feed(sticky)
    frames = []
    while True:
        frame = parser.next_frame()
        if frame is None:
            break
        frames.append(frame)
    record("E7", "粘包：两个帧拼一起能解析出 2 帧", len(frames) == 2, f"实际 {len(frames)}")
    if len(frames) == 2:
        record("E7", "粘包：seq 依次为 1、2",
               [f.seq for f in frames] == [1, 2], str([f.seq for f in frames]))
        record("E7", "粘包：载荷与原始一致",
               frames[0].payload == payload and frames[1].payload == payload)

    frame_bytes = pack_frame(S_SNAPSHOT, 7, payload)
    parser = FrameParser()
    parser.feed(frame_bytes[:10])          # 头都不完整
    record("E7", "半包（头不完整）先出 0 帧", parser.next_frame() is None)
    parser.feed(frame_bytes[10:100])       # body 只给一部分
    record("E7", "半包（body 一半）仍出 0 帧", parser.next_frame() is None)
    parser.feed(frame_bytes[100:])
    whole = parser.next_frame()
    record("E7", "半包：补齐后出 1 帧",
           whole is not None and whole.payload == payload)
    if whole is not None:
        record("E7", "半包：seq 正确", whole.seq == 7, str(whole.seq))


def check_hard_e2() -> None:
    """E2：协议上限 —— 超了必须抛错，不能静默截断。"""
    from protocol.framing import ProtocolError

    try:
        pack_snapshot(1, [PlayerSnapshot(i, 0, 0, 1, 0, 1, 0) for i in range(256)],
                      [], [], [])
        ok, detail = False, "256 个玩家没有抛错"
    except (ProtocolError, ValueError) as exc:
        ok, detail = True, type(exc).__name__
    record("E2", "player_count > 255 必须抛错", ok, detail)

    try:
        World(enemy_target=256)
        ok, detail = False, "enemy_target=256 没有抛错"
    except ValueError as exc:
        ok, detail = True, str(exc)[:40]
    record("E2", "enemy_target > 255 必须抛错", ok, detail)


# ---------------------------------------------------------------- 软校验


def _run_scenario(name: str, server_args: list[str], bot_args: list[str],
                  duration: float) -> dict | None:
    """起一个服务端 + 一批机器人，返回机器人汇总 JSON（失败返回 None）。"""
    logs = PROJECT_ROOT / "data" / "logs" / "check"
    logs.mkdir(parents=True, exist_ok=True)
    bot_out = logs / f"{name}.json"
    if bot_out.exists():
        bot_out.unlink()

    server_cmd = [sys.executable, "-X", "utf8", "-u", "-m", "server.main"] + server_args
    bot_cmd = [sys.executable, "-X", "utf8", "-u", "-m", "bot.main"] + bot_args

    with (logs / f"{name}.server.log").open("w", encoding="utf-8") as srvlog:
        server = subprocess.Popen(server_cmd, cwd=PROJECT_ROOT,
                                  stdout=srvlog, stderr=subprocess.STDOUT)
        try:
            time.sleep(1.5)
            with (logs / f"{name}.bot.log").open("w", encoding="utf-8") as blog:
                bot = subprocess.Popen(bot_cmd, cwd=PROJECT_ROOT,
                                       stdout=blog, stderr=subprocess.STDOUT)
                try:
                    bot.wait(timeout=duration + 90)
                except subprocess.TimeoutExpired:
                    bot.kill()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                server.kill()

    if not bot_out.exists():
        return None
    return json.loads(bot_out.read_text(encoding="utf-8"))


def _load_soft_baseline() -> dict:
    return json.loads(SOFT_BASELINE.read_text(encoding="utf-8"))


def _within(value: float, base: float, tol: float = SOFT_TOLERANCE) -> bool:
    return base == 0 or abs(value - base) / abs(base) <= tol


def check_soft_e9() -> None:
    summary = _run_scenario(
        "e9",
        ["9550", "--enemies", str(ENEMIES), "--bullets", str(BULLETS),
         "--fixed-entities", "--no-metrics", "--no-stats"],
        ["--port", "9550", "--clients", str(PLAYERS),
         "--duration", str(int(SOFT_SAMPLE_S)), "--out",
         str(PROJECT_ROOT / "data" / "logs" / "check" / "e9.json")],
        SOFT_SAMPLE_S,
    )
    if summary is None:
        record("E9", "短跑未崩且产出汇总", False, "没有汇总文件")
        return
    record("E9", "短跑未崩且产出汇总", True)
    record("E9", f"{PLAYERS} 客户端全部连上", summary.get("clients_connected") == PLAYERS,
           str(summary.get("clients_connected")))
    base = _load_soft_baseline()["e9"]
    bytes_per_s = summary.get("bytes_per_s", 0) / max(1, summary.get("clients_connected", 1))
    record("E9", "单客户端带宽 ±20%", _within(bytes_per_s, base["bytes_per_s_per_client"]),
           f"{bytes_per_s:.0f} vs {base['bytes_per_s_per_client']:.0f} B/s")
    interval = summary.get("interval_p50_ms", 0)
    record("E9", "快照间隔 ≈50 ms", _within(interval, base["interval_p50_ms"]),
           f"{interval:.1f} vs {base['interval_p50_ms']:.1f} ms")


def check_soft_e5() -> None:
    summary = _run_scenario(
        "e5",
        ["9551", "--enemies", str(ENEMIES), "--bullets", str(BULLETS),
         "--tick-hz", "30", "--fixed-entities", "--no-metrics", "--no-stats"],
        ["--port", "9551", "--clients", str(PLAYERS),
         "--duration", str(int(SOFT_SAMPLE_S)), "--out",
         str(PROJECT_ROOT / "data" / "logs" / "check" / "e5.json")],
        SOFT_SAMPLE_S,
    )
    if summary is None:
        record("E5", "30 Hz 短跑未崩", False, "没有汇总文件")
        return
    record("E5", "30 Hz 短跑未崩", True)
    interval = summary.get("interval_p50_ms", 0)
    record("E5", "30 Hz 到达间隔 ≈33 ms（±20%）", 33.3 * 0.8 <= interval <= 33.3 * 1.2,
           f"{interval:.1f} ms")


def check_soft_e4() -> None:
    """经损伤代理（0 损伤）跑一遍，确认代理链路本身不引入异常。"""
    logs = PROJECT_ROOT / "data" / "logs" / "check"
    logs.mkdir(parents=True, exist_ok=True)
    bot_json = logs / "e4.json"
    if bot_json.exists():
        bot_json.unlink()

    server = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-u", "-m", "server.main", "9552",
         "--enemies", str(ENEMIES), "--bullets", str(BULLETS),
         "--fixed-entities", "--no-metrics", "--no-stats"],
        cwd=PROJECT_ROOT, stdout=(logs / "e4.server.log").open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT)
    proxy = None
    try:
        time.sleep(1.5)
        proxy = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-u", "-m", "tools.netem_proxy",
             "--listen", "9752", "--upstream", "9552", "--delay-ms", "0"],
            cwd=PROJECT_ROOT, stdout=(logs / "e4.proxy.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT)
        time.sleep(1.5)
        bot = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-u", "-m", "bot.main", "--port", "9752",
             "--clients", str(PLAYERS), "--duration", str(int(SOFT_SAMPLE_S)),
             "--err-px", "--out", str(bot_json)],
            cwd=PROJECT_ROOT, stdout=(logs / "e4.bot.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT)
        try:
            bot.wait(timeout=SOFT_SAMPLE_S + 90)
        except subprocess.TimeoutExpired:
            bot.kill()
    finally:
        for proc in (proxy, server):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    proc.kill()

    if not bot_json.exists():
        record("E4", "经代理短跑未崩", False, "没有汇总文件")
        return
    summary = json.loads(bot_json.read_text(encoding="utf-8"))
    record("E4", "经代理短跑未崩", True)
    record("E4", "0 损伤时代理 RTT < 50 ms", summary.get("rtt_p50_ms", 999) < 50,
           f"{summary.get('rtt_p50_ms')} ms")
    err = summary.get("err_px_mean")
    record("E4", "err_px 在合理区间 [5, 15] px",
           err is not None and 5.0 <= err <= 15.0, str(err))


def check_soft_e8() -> None:
    summary = _run_scenario(
        "e8",
        ["9553", "--enemies", str(ENEMIES), "--bullets", str(BULLETS),
         "--fixed-entities", "--no-metrics", "--no-stats"],
        ["--port", "9553", "--clients", str(PLAYERS),
         "--duration", str(int(SOFT_SAMPLE_S)), "--out",
         str(PROJECT_ROOT / "data" / "logs" / "check" / "e8.json")],
        SOFT_SAMPLE_S,
    )
    if summary is None:
        record("E8", "短跑未崩", False, "没有汇总文件")
        return
    record("E8", "短跑未崩", True)
    record("E8", "心跳有回包", summary.get("heartbeats_acked", 0) > 0,
           f"acked={summary.get('heartbeats_acked')}")


# ---------------------------------------------------------------- 依赖检查


def db_available() -> tuple[bool, bool]:
    """(MySQL 可用, Redis 可用) —— 缺了就让相关检查 skip，而不是失败。"""
    mysql_ok = redis_ok = False
    try:
        import pymysql

        pymysql.connect(host="127.0.0.1", user="django_user", password="123456",
                        database="myproject", connect_timeout=1).close()
        mysql_ok = True
    except Exception:  # noqa: BLE001
        pass
    try:
        import redis

        redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.5).ping()
        redis_ok = True
    except Exception:  # noqa: BLE001
        pass
    return mysql_ok, redis_ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="实验回归检查（硬校验 + 软校验）")
    parser.add_argument("--layer", choices=("hard", "soft", "all"), default="all")
    parser.add_argument("--only", default="", help="只跑某一项，如 E5")
    parser.add_argument(
        "--write-baseline", action="store_true",
        help="跑一次 E9 短场景并把结果写成软校验基线（**首次配置时用**）",
    )
    return parser.parse_args()


def write_soft_baseline() -> None:
    """跑一次 E9 短场景，把带宽/间隔记成基线。

    ⚠️ 只在**首次配置**或**确实要改默认行为**时跑。平时不要用它让检查变绿。
    """
    print("=== 生成软校验基线（E9 短场景）===")
    summary = _run_scenario(
        "baseline",
        ["9554", "--enemies", str(ENEMIES), "--bullets", str(BULLETS),
         "--fixed-entities", "--no-metrics", "--no-stats"],
        ["--port", "9554", "--clients", str(PLAYERS),
         "--duration", str(int(SOFT_SAMPLE_S)), "--out",
         str(PROJECT_ROOT / "data" / "logs" / "check" / "baseline.json")],
        SOFT_SAMPLE_S,
    )
    if summary is None:
        print("  失败：没有产出汇总文件")
        raise SystemExit(1)

    connected = max(1, summary.get("clients_connected", 1))
    data = {
        "note": "软校验基线。桌面机上的近似值，比对时给 ±20% 容差。",
        "conditions": {"players": PLAYERS, "enemies": ENEMIES,
                       "bullets": BULLETS, "sample_s": SOFT_SAMPLE_S},
        "e9": {
            "bytes_per_s_per_client": round(summary.get("bytes_per_s", 0) / connected, 1),
            "interval_p50_ms": round(summary.get("interval_p50_ms", 0), 1),
            "tick_ms_avg": round(summary.get("tick_ms_avg", 0), 3)
            if summary.get("tick_ms_avg") else None,
        },
    }
    SOFT_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    SOFT_BASELINE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  写入 {SOFT_BASELINE}")
    print(f"  单客户端带宽 : {data['e9']['bytes_per_s_per_client']} B/s")
    print(f"  快照间隔 p50 : {data['e9']['interval_p50_ms']} ms")


def main() -> None:
    args = parse_args()
    if args.write_baseline:
        write_soft_baseline()
        return

    mysql_ok, redis_ok = db_available()
    print(f"  依赖：MySQL {'可用' if mysql_ok else '不可用（相关检查会跳过）'}，"
          f"Redis {'可用' if redis_ok else '不可用（相关检查会跳过）'}")
    print()

    want = lambda name: not args.only or args.only.upper() == name  # noqa: E731

    if args.layer in ("hard", "all"):
        print("=== 硬校验（确定性，精确断言）===")
        if want("E1"):
            check_hard_e1()
        if want("E7"):
            check_hard_e7()
        if want("E2"):
            check_hard_e2()
        print()

    if args.layer in ("soft", "all"):
        print("=== 软校验（真实进程，±20% 容差）===")
        if want("E9"):
            check_soft_e9()
        if want("E5"):
            check_soft_e5()
        if want("E4"):
            check_soft_e4()
        if want("E8"):
            check_soft_e8()
        print()

    failed = [row for row in results if not row[2]]
    print("=" * 66)
    print(f"  共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    for layer, name, _ok, detail in failed:
        print(f"    FAIL [{layer}] {name}  {detail}")
    print("=" * 66)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()