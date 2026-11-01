"""步骤 10b 的端到端验证：**登录 → TCP 认证 → 打一局 → 结算 → 看榜**。

这一条链路是"长短连接分层"（D-005）落地后的完整证明：
- HTTP 登录拿 token（Django + MySQL）
- TCP 上用 token 认证（`C_AUTH` → `S_AUTH_OK`）
- 打完一局，服务端结算写 MySQL + Redis（写透）
- 排行榜立刻能查到（读 Redis）

脚本自己起服务端（`--enable-kills --persist-scores`），跑完自己收掉。
**前置**：Django 的 `runserver` 不需要开（本脚本只打 HTTP 接口，起的是一套新进程），
但 MySQL / Redis 必须在跑。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.check_persist
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

from protocol.framing import recv_frame, send_frame
from protocol.messages import (
    C_AUTH,
    C_INPUT,
    KEY_LEFT,
    KEY_RIGHT,
    S_AUTH_FAIL,
    S_AUTH_OK,
    S_SNAPSHOT,
    pack_auth,
    pack_keys,
    unpack_auth_fail,
    unpack_auth_ok,
)
from protocol.snapshot import unpack_snapshot

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ok_count = 0
fail_count = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok_count, fail_count
    if condition:
        ok_count += 1
        print(f"  ✅ {label}")
    else:
        fail_count += 1
        print(f"  ❌ {label}  {detail}")


def wait_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9560)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--play-seconds", type=float, default=8.0)
    args = parser.parse_args()

    print("=== 1) HTTP 注册拿 token ===")
    name = f"e2e{int(time.time()) % 100000}"
    response = requests.post(
        f"{args.api}/api/auth/register",
        json={"username": name, "password": "secret123"},
        timeout=5,
    )
    check("注册成功", response.status_code == 201, response.text[:120])
    if response.status_code != 201:
        raise SystemExit(1)
    token = response.json()["token"]

    print("=== 2) 起服务端（击杀生效 + 结算写库）===")
    log_path = PROJECT_ROOT / "data" / "logs" / "check_persist.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [
            sys.executable, "-X", "utf8", "-u", "-m", "server.main",
            str(args.port),
            "--enemies", "10", "--bullets", "40",
            "--enable-kills", "--fixed-entities",
            "--persist-scores",
            "--no-metrics", "--no-stats",
        ],
        cwd=PROJECT_ROOT,
        stdout=log_path.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    try:
        check("服务端已监听", wait_port("127.0.0.1", args.port))

        print("=== 3) TCP 连接 + C_AUTH 认证 ===")
        sock = socket.create_connection(("127.0.0.1", args.port), timeout=5)
        sock.settimeout(3.0)
        send_frame(sock, C_AUTH, 1, pack_auth(token))

        my_id = None
        nickname = ""
        deadline = time.time() + 5
        while time.time() < deadline:
            frame = recv_frame(sock)
            if frame is None:
                break
            if frame.msg_type == S_AUTH_OK:
                my_id, nickname = unpack_auth_ok(frame.payload)
                break
            if frame.msg_type == S_AUTH_FAIL:
                code = unpack_auth_fail(frame.payload)
                check("认证不应失败", False, f"code={code}")
                break
        check("收到 S_AUTH_OK", my_id is not None)
        check("昵称与注册用户名一致", nickname == name, f"{nickname} != {name}")

        print("=== 4) 打一局（左右横移 Sweep，8 秒）===")
        seq = 2
        last_input = 0.0
        snapshots = 0
        max_score = 0
        started = time.time()
        while time.time() - started < args.play_seconds:
            now = time.time()
            if now - last_input >= 0.05:
                key = KEY_RIGHT if int(now) % 2 == 0 else KEY_LEFT
                send_frame(sock, C_INPUT, seq, pack_keys(key))
                seq += 1
                last_input = now
            try:
                frame = recv_frame(sock)
            except (OSError, socket.timeout):
                continue
            if frame is None:
                break
            if frame.msg_type == S_SNAPSHOT:
                snapshots += 1
                try:
                    snap = unpack_snapshot(frame.payload)
                except Exception:  # noqa: BLE001
                    continue
                for player in snap.players:
                    if player.player_id == my_id:
                        max_score = max(max_score, player.score)
        check("收到了快照", snapshots > 0, str(snapshots))
        check("这一局打出了分数", max_score > 0, f"score={max_score}")
        print(f"     快照 {snapshots} 个，本局最高分 {max_score}")

        print("=== 5) 断开连接 → 服务端结算 ===")
        sock.close()
        time.sleep(2.0)  # 给线程池里的写库留点时间
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        check("服务端认证通过日志", "认证通过" in log_text)
        check("服务端结算日志", "结算" in log_text and "已入库" in log_text,
              log_text[-300:])

        print("=== 6) 排行榜能查到这一局 ===")
        board = requests.get(f"{args.api}/api/leaderboard?limit=10", timeout=5).json()
        mine = [e for e in board.get("entries", []) if e["username"] == name]
        check("榜上出现该玩家", bool(mine), str(board)[:200])
        if mine:
            check("分数已写入（> 0）", mine[0]["best_score"] > 0, str(mine[0]))
            check("局数已累计", mine[0]["games"] >= 1, str(mine[0]))
            print(f"     榜上记录：{mine[0]}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    print()
    print(f"  结果：{ok_count} 通过，{fail_count} 失败")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()