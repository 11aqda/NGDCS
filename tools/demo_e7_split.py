"""E7 演示脚本：强制制造「粘包」与「半包」，供抓包验证（图 6-16）。

## 为什么要专门写脚本

**TCP 是字节流，拆合边界不固定。** 同一份应用层数据，内核可能合成一段发出，
也可能拆成几段；取决于发送缓冲、Nagle 算法、MTU、调度时机等因素。
所以**靠正常游戏流量抓不到稳定的粘包/半包形态** —— 跑十次可能十个样子，
没法作为论文里一张可复现的图。

因此这里用脚本**强制制造**两种极端形态，把"我们解析器要处理什么"变成可观察的事实。

## 但「强制制造」也不保证一定成

- **`sendall(a + b)` 不保证落进同一个 TCP 段**：内核完全可以在中间切开。
  所以脚本只负责"尽量这样发"，**是否真的粘成一个段，以抓包结果为准**。
- **半包靠 `TCP_NODELAY` + `sleep` 才稳**：不关 Nagle，两个小包会被合并成一个段发出去，
  就看不到"一个帧被拆成两段"了。

所以流程是：**发 → 抓 → 用 TShark 核实 → 按实际结果的段数出图**。
如果没成，脚本会明确报出来，重跑或调整参数，而不是硬画成想要的形状。

## 用法

    # 先起抓包（另开一个终端）
    D:\\Tools\\Wireshark\\dumpcap.exe -i \\Device\\NPF_Loopback -f "tcp port 9601" -w data/E7-split.pcapng

    # 再跑本脚本
    .venv\\Scripts\\python.exe -X utf8 -m tools.demo_e7_split
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from pathlib import Path

from protocol.framing import pack_frame
from protocol.messages import C_INPUT, KEY_LEFT, KEY_RIGHT, S_SNAPSHOT, pack_keys
from protocol.snapshot import (
    BulletSnapshot,
    EnemySnapshot,
    PlayerSnapshot,
    pack_snapshot,
)

PORT = 9601
HOST = "127.0.0.1"


def build_two_input_frames() -> tuple[bytes, bytes]:
    """两帧 C_INPUT（各 13 B = 12 B 帧头 + 1 B 按键位图）—— 用于"粘包"。"""
    return (
        pack_frame(C_INPUT, 1, pack_keys(KEY_LEFT)),
        pack_frame(C_INPUT, 2, pack_keys(KEY_RIGHT)),
    )


def build_snapshot_frame() -> tuple[bytes, int]:
    """一帧 S_SNAPSHOT（12 + 1927 = 1939 B）—— 用于"半包"。

    故意用 1927 B 的载荷：这样和图 6-15 里那个真实快照帧**同样大小**，
    读者可以把两张图对照着看。
    """
    players = [
        PlayerSnapshot(player_id=i, x=100 + i * 50, y=700, color=i % 8)
        for i in range(1, 5)
    ]
    enemies = [
        EnemySnapshot(enemy_id=i, x=40 + i * 6, y=100 + i * 3, hp=3)
        for i in range(1, 31)
    ]
    bullets = [
        BulletSnapshot(owner_id=1, x=10 + i * 3, y=20 + i * 2, angle=(i * 8) % 256)
        for i in range(200)
    ]
    payload = pack_snapshot(1, players, enemies, bullets)
    return pack_frame(S_SNAPSHOT, 3, payload), len(payload)


def run_demo(port: int, half_gap: float, start_delay: float = 0.0) -> dict:
    """起一个监听 + 一个客户端，然后按两阶段强制发送。

    `start_delay`：绑定端口后先等这么多秒再发数据。
    **这是为了配合抓包**：dumpcap 必须在数据发出之前就开始抓，
    而 dumpcap 在前台跑更稳（`Start-Process` 起它时实测写不出文件）。
    所以实际流程是：本脚本后台起（带 4 秒延迟）→ 前台跑 dumpcap → 数据正好落在抓包窗口里。
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen(1)
    print(f"[demo] 监听 {HOST}:{port}", flush=True)
    if start_delay > 0:
        print(f"[demo] 等 {start_delay:.0f} s 开始发送（留给抓包端启动）", flush=True)
        time.sleep(start_delay)

    result = {"sticky_bytes": 0, "half_header": 0, "half_body": 0}

    def client() -> None:
        time.sleep(0.15)
        sock = socket.create_connection((HOST, port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # 一直读到对端关闭，保证连接不会因为我们没读而被压住窗口
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
        sock.close()

    thread = threading.Thread(target=client, daemon=True)
    thread.start()

    conn, addr = server.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[demo] 客户端已连接 {addr}")
    time.sleep(0.3)  # 让抓包端先看到握手，两阶段边界更清楚

    # ---- 阶段一：粘包（两帧拼成一次 sendall）----
    frame_a, frame_b = build_two_input_frames()
    blob = frame_a + frame_b
    t0 = time.time()
    conn.sendall(blob)
    result["sticky_bytes"] = len(blob)
    print(f"[demo] 粘包阶段：一次 sendall 发出 {len(blob)} B"
          f"（帧A {len(frame_a)} B + 帧B {len(frame_b)} B）")
    time.sleep(0.5)

    # ---- 阶段二：半包（帧头 / 载荷 分两次发，中间 sleep）----
    frame_c, payload_len = build_snapshot_frame()
    header, body = frame_c[:12], frame_c[12:]
    result["half_header"], result["half_body"] = len(header), len(body)

    conn.sendall(header)
    print(f"[demo] 半包阶段：先发帧头 {len(header)} B，等 {half_gap:.2f} s ...")
    time.sleep(half_gap)
    conn.sendall(body)
    print(f"[demo] 半包阶段：再发载荷 {len(body)} B（整帧 {len(frame_c)} B）")

    time.sleep(0.4)
    conn.close()
    server.close()
    thread.join(timeout=1.0)
    print(f"[demo] 完成，用时 {time.time() - t0:.2f} s")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="制造粘包/半包供 E7 抓包（图 6-16）")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--half-gap", type=float, default=0.35,
                        help="半包两段之间的间隔秒数；太小可能仍被合并")
    parser.add_argument("--start-delay", type=float, default=0.0,
                        help="绑定端口后等几秒再发数据（配合前台抓包）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not Path("protocol").is_dir():
        raise SystemExit("请在项目根目录运行（python -m tools.demo_e7_split）")
    run_demo(args.port, args.half_gap, args.start_delay)


if __name__ == "__main__":
    main()