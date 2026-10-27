"""出 E7 的「快照报文逐字段标注」图（图 6-15）。

为什么不直接在 Wireshark 截图上画标注：
1. 字号、框线、对齐都得靠手调，改一次要重来
2. **不可复现** —— 抓包重跑一次，标注坐标就全废了
3. 截图里夹着桌面、书签栏，得靠人裁剪

所以这里改成：**字节从抓包文件里读**（TShark），标注用 matplotlib 画。
产物既是「真实抓包数据」又是「干净的矢量图」，而且随时能重出。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.plot_e7 --pcap data/E7-capture.pcapng

默认挑第一个 1939 字节的满快照帧（4 人 + 30 敌机 + 200 子弹）。
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

# 先导入 tools.plot 把 matplotlib 的缓存目录与中文字体配好，再 import matplotlib
from tools.plot import HAVE_MPL  # noqa: F401  （导入即完成环境准备）

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TSHARK = Path(r"D:\Tools\Wireshark\tshark.exe")

# 三段结构各自的底色（与论文正文里的配色保持一致）
COLOR_FRAME = "#dbeafe"      # 帧头 12 B
COLOR_SNAP = "#dcfce7"       # 快照头 13 B
COLOR_ENTITY = "#fed7aa"     # 实体条目
COLOR_OTHER = "#f3f4f6"


def read_payload(pcap: Path, tshark: Path, tcp_len: int) -> tuple[int, bytes]:
    """从抓包里取第一个指定长度的下行载荷，返回 (帧号, 载荷字节)。"""
    cmd = [
        str(tshark), "-r", str(pcap),
        "-Y", f"tcp.srcport==9527 && tcp.len=={tcp_len}",
        "-T", "fields", "-e", "frame.number", "-e", "tcp.payload",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    line = next((ln for ln in out.splitlines() if "\t" in ln), None)
    if line is None:
        raise SystemExit(f"抓包里没有 tcp.len=={tcp_len} 的帧")
    number, hexstr = line.split("\t", 1)
    return int(number), bytes.fromhex(hexstr.strip())


def verify(payload: bytes) -> dict:
    """把帧头与快照头解出来 —— 图上标的每个值都从这里来，不手写。"""
    import struct

    if len(payload) < 25:
        raise SystemExit("载荷太短，连帧头 + 快照头都不够")
    magic, version, mtype, seq, length = struct.unpack("!HBBII", payload[:12])
    tick, level, wave, state, pc, ec, bc, ic, boss = struct.unpack(
        "!IBBBBBHBB", payload[12:25]
    )
    return {
        "magic": magic, "version": version, "type": mtype, "seq": seq,
        "length": length, "tick": tick, "level": level, "wave": wave,
        "wave_state": state, "players": pc, "enemies": ec, "bullets": bc,
        "items": ic, "boss": boss,
    }


def player_fields(payload: bytes, index: int) -> dict:
    """解第 index 个玩家条目（11 字节，从偏移 25 开始）。"""
    import struct

    base = 25 + index * 11
    pid, x, y, power, color, flags, score = struct.unpack(
        "!HHHBBBH", payload[base:base + 11]
    )
    return {
        "id": pid, "x": x, "y": y, "power": power,
        "color": color, "flags": flags, "score": score,
    }


# 表里的行：(区域, 偏移文本, 字段名, 字节数, 解码值生成函数)
def build_rows(payload: bytes, info: dict) -> list[tuple[str, str, str, int, str]]:
    p1 = player_fields(payload, 0)
    rows = [
        ("帧头", "[0:2]", "magic", 2, f"0x{info['magic']:04X} \"JY\""),
        ("帧头", "[2]", "version", 1, str(info["version"])),
        ("帧头", "[3]", "type", 1, f"0x{info['type']:02X} = S_SNAPSHOT"),
        ("帧头", "[4:8]", "seq", 4, str(info["seq"])),
        ("帧头", "[8:12]", "length", 4, f"{info['length']} B"),
        ("快照头", "[12:16]", "tick", 4, str(info["tick"])),
        ("快照头", "[16]", "level", 1, str(info["level"])),
        ("快照头", "[17]", "wave", 1, str(info["wave"])),
        ("快照头", "[18]", "wave_state", 1, str(info["wave_state"])),
        ("快照头", "[19]", "player_count", 1, str(info["players"])),
        ("快照头", "[20]", "enemy_count", 1, str(info["enemies"])),
        ("快照头", "[21:23]", "bullet_count", 2, str(info["bullets"])),
        ("快照头", "[23]", "item_count", 1, str(info["items"])),
        ("快照头", "[24]", "boss_present", 1, str(info["boss"])),
        ("玩家 1", "[25:27]", "player_id", 2, str(p1["id"])),
        ("玩家 1", "[27:29]", "x", 2, str(p1["x"])),
        ("玩家 1", "[29:31]", "y", 2, str(p1["y"])),
        ("玩家 1", "[31]", "power", 1, str(p1["power"])),
        ("玩家 1", "[32]", "color", 1, str(p1["color"])),
        ("玩家 1", "[33]", "flags", 1, str(p1["flags"])),
        ("玩家 1", "[34:36]", "score", 2, str(p1["score"])),
    ]
    return rows


def plot_layout(payload: bytes, info: dict, frame_no: int, out_path: Path,
                shown_bytes: int = 64) -> None:
    """上：十六进制区（按结构着色）；下：逐字段表。

    布局上的两条经验（第一版踩过）：
    1. **别用箭头指到字节上** —— 三段结构的标签必然互相撞车。改用彩色图例，
       颜色和底色一一对应，既无碰撞又不用算坐标
    2. **表格行高用数据坐标算**，不要用 axes 比例 —— 行数一变就重叠
    """
    data = payload[:shown_bytes]
    rows = build_rows(payload, info)

    fig = plt.figure(figsize=(11.6, 9.2))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 2.05], hspace=0.10)

    # ---------------- 上半：十六进制 ----------------
    ax = fig.add_subplot(gs[0])
    ax.set_xlim(-2.4, 17.4)
    ax.set_ylim(-0.8, 6.4)
    ax.axis("off")

    per_row = 16
    dx, dy = 1.0, 1.0
    x0, y0 = 0.0, 3.6

    def region_color(i: int) -> str:
        if i < 12:
            return COLOR_FRAME
        if i < 25:
            return COLOR_SNAP
        return COLOR_ENTITY if i < 25 + 4 * 11 else COLOR_OTHER

    # 底色块：按行把相邻同色的字节合并成一块
    for r in range(0, len(data), per_row):
        row = data[r:r + per_row]
        c = 0
        while c < len(row):
            color = region_color(r + c)
            end = c
            while end + 1 < len(row) and region_color(r + end + 1) == color:
                end += 1
            ax.add_patch(
                FancyBboxPatch(
                    (x0 + c * dx - 0.42, y0 - r // per_row * dy - 0.34),
                    (end - c + 1) * dx - 0.16, 0.68,
                    boxstyle="round,pad=0.02,rounding_size=0.06",
                    facecolor=color, edgecolor="none", zorder=1,
                )
            )
            c = end + 1

    for i, byte in enumerate(data):
        r, c = divmod(i, per_row)
        ax.text(x0 + c * dx, y0 - r * dy, f"{byte:02x}", ha="center", va="center",
                family="monospace", fontsize=11.5, zorder=2)

    for r in range(0, len(data), per_row):
        ax.text(x0 - 1.0, y0 - r // per_row * dy, f"{r:04x}", ha="right", va="center",
                family="monospace", fontsize=9.5, color="#6b7280")

    # 图例（不用箭头，避免标签互相碰撞）
    legend_items = [
        (COLOR_FRAME, "#1d4ed8", f"帧头 {12} B"),
        (COLOR_SNAP, "#15803d", f"快照头 {13} B"),
        (COLOR_ENTITY, "#c2410c", f"玩家条目 {11} B × {info['players']}"),
    ]
    lx = x0
    for face, edge, label in legend_items:
        ax.add_patch(
            FancyBboxPatch((lx, 5.35), 0.52, 0.42,
                           boxstyle="round,pad=0.02,rounding_size=0.05",
                           facecolor=face, edgecolor=edge, linewidth=1.0)
        )
        ax.text(lx + 0.72, 5.56, label, fontsize=10, va="center", color=edge,
                fontweight="bold")
        lx += 0.85 + len(label) * 0.235

    ax.set_title(
        f"图 6-15 快照报文逐字段标注（抓包第 {frame_no} 帧，载荷 {len(payload)} B，"
        f"此处显示前 {len(data)} B）",
        fontsize=13.5, pad=30,
    )

    # ---------------- 下半：逐字段表 ----------------
    ax2 = fig.add_subplot(gs[1])
    n = len(rows)
    ax2.set_xlim(0, 1)
    # 下方留出 5 个单位给注释，否则注释会压住最后几行
    ax2.set_ylim(-5.0, n + 2.6)
    ax2.axis("off")

    region_color_map = {"帧头": COLOR_FRAME, "快照头": COLOR_SNAP, "玩家 1": COLOR_ENTITY}
    colx = {"region": 0.005, "offset": 0.10, "field": 0.27, "size": 0.50, "value": 0.57}

    head_y = n + 1.7
    for key, head in (("region", "区域"), ("offset", "偏移"), ("field", "字段"),
                      ("size", "字节"), ("value", "解码值")):
        ax2.text(colx[key], head_y, head, fontsize=10.5, fontweight="bold", va="center")

    ax2.plot([0.0, 0.99], [head_y - 0.55, head_y - 0.55], color="#9ca3af", linewidth=1.0)

    for idx, (region, offset, field, size, value) in enumerate(rows):
        y = n - idx
        ax2.add_patch(
            plt.Rectangle((colx["region"] - 0.002, y - 0.40), 0.082, 0.80,
                          facecolor=region_color_map.get(region, COLOR_OTHER),
                          edgecolor="none", clip_on=False)
        )
        ax2.text(colx["region"] + 0.006, y, region, fontsize=9.2, va="center")
        ax2.text(colx["offset"], y, offset, fontsize=9.2, va="center", family="monospace")
        ax2.text(colx["field"], y, field, fontsize=9.6, va="center", family="monospace")
        ax2.text(colx["size"], y, str(size), fontsize=9.2, va="center")
        ax2.text(colx["value"], y, value, fontsize=9.4, va="center",
                 family="monospace", color="#111827")

    ax2.text(
        0.005, -4.7,
        "注：快照载荷从帧内偏移 0x2C 开始（4 B Loopback 头 + 20 B IPv4 头 + 20 B TCP 头 = 44 B）；"
        "上表偏移均相对载荷起点。\n"
        f"玩家 2~{info['players']} 结构相同（各 11 B，紧接其后）；此后是 {info['enemies']} 个敌机条目"
        f"（各 9 B）与 {info['bullets']} 个子弹条目（各 8 B）。\n"
        f"校验：帧头 12 + length {info['length']} = {12 + info['length']}，与实际载荷长度完全一致。",
        fontsize=8.6, va="bottom", color="#4b5563",
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_timeline(pcap: Path, tshark: Path, out_path: Path) -> dict:
    """出「抓包总览」时间线图（图 6-14）。

    为什么不用 Wireshark 的包列表截图：那个界面能看到的只是某一屏，
    **20 Hz 的规律节奏要滚动才能感受到**。改成按事件类型分行的时间线，
    一眼就能看出「每 50 ms 一格」以及各类报文的占比。
    """
    cmd = [
        str(tshark), "-r", str(pcap), "-T", "fields",
        "-e", "frame.time_relative", "-e", "tcp.srcport", "-e", "tcp.dstport",
        "-e", "tcp.len", "-e", "tcp.flags.syn", "-e", "tcp.flags.fin",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    # (时间, 类别) 分类：按方向和 tcp.len 判定报文种类。
    #
    # ⚠️ `tcp.len` 是 **TCP 载荷长度 = 12 B 帧头 + 应用层载荷**，不是应用层载荷本身：
    #     快照 1939 / 1906 / 1917 / 1928（4/1/2/3 人）
    #     欢迎 S_WELCOME 15（3 B）、心跳应答 20（8 B）
    #     输入 C_INPUT 13（1 B）、心跳 C_HEARTBEAT 16（4 B）
    #
    # ⚠️ `tcp.flags.syn` 的值是 `True` / `False` 字符串，不是 `1` / `0`。
    rows: list[tuple[float, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 6 or not parts[0]:
            continue
        try:
            t = float(parts[0])
        except ValueError:
            continue
        _src, _dst, length, syn, fin = parts[1], parts[2], parts[3], parts[4], parts[5]
        try:
            n = int(length) if length else 0
        except ValueError:
            n = 0

        if syn == "True":
            rows.append((t, "TCP 握手"))
        elif fin == "True":
            rows.append((t, "TCP 断开"))
        elif n == 0:
            rows.append((t, "纯 ACK"))
        elif n >= 1000:
            rows.append((t, "快照 S_SNAPSHOT"))
        elif n in (15, 20):
            rows.append((t, "心跳/欢迎"))
        elif n == 13:
            rows.append((t, "输入 C_INPUT"))
        elif n == 16:
            rows.append((t, "心跳 C_HEARTBEAT"))
        else:
            rows.append((t, "其它"))

    order = ["快照 S_SNAPSHOT", "输入 C_INPUT", "心跳 C_HEARTBEAT",
             "心跳/欢迎", "纯 ACK", "TCP 握手", "TCP 断开", "其它"]
    colors = {
        "快照 S_SNAPSHOT": "#1f77b4", "输入 C_INPUT": "#2ca02c",
        "心跳 C_HEARTBEAT": "#ff7f0e", "心跳/欢迎": "#9467bd",
        "纯 ACK": "#bdbdbd", "TCP 握手": "#d62728", "TCP 断开": "#8c564b",
        "其它": "#000000",
    }
    present = [name for name in order if any(kind == name for _, kind in rows)]

    fig, ax = plt.subplots(figsize=(11.6, 5.4))
    for yi, name in enumerate(present):
        xs = [t for t, kind in rows if kind == name]
        ax.plot(xs, [yi] * len(xs), linestyle="none", marker="|", markersize=11,
                markeredgewidth=1.0, color=colors.get(name, "#333333"), label=name)

    # 20 Hz 网格线：每 50 ms 一条，用来"量"出节奏
    t_max = max((t for t, _ in rows), default=1.0)
    step = 0.05
    first = 0.0
    grid = []
    while first <= t_max:
        grid.append(first)
        first += step
    if len(grid) < 200:  # 太多就不画了，会糊成一片
        for gx in grid:
            ax.axvline(gx, color="#e5e7eb", linewidth=0.6, zorder=0)

    totals = {name: sum(1 for _, kind in rows if kind == name) for name in present}
    legend_labels = [f"{name}（{totals[name]}）" for name in present]
    ax.set_yticks(range(len(present)))
    ax.set_yticklabels(legend_labels, fontsize=9)
    ax.set_xlabel("相对时间 (s)")
    ax.set_title(f"图 6-14 抓包总览：{len(rows)} 个 TCP 报文的事件时间线", fontsize=12.5)
    ax.grid(alpha=0.25, axis="x")
    ax.set_ylim(-0.8, len(present) - 0.2)

    # 20 Hz 节奏用一个小型放大插图来证明，而不是给整张图铺 360 条网格线
    # （整张图铺满会糊成一片，什么也看不出来）
    zoom = ax.inset_axes([0.60, 0.06, 0.37, 0.30])
    lo, hi = 2.0, 2.5
    for yi2, name in enumerate(present):
        xs = [t for t, kind in rows if kind == name and lo <= t <= hi]
        zoom.plot(xs, [yi2] * len(xs), linestyle="none", marker="|", markersize=9,
                  markeredgewidth=1.0, color=colors.get(name, "#333333"))
    g = lo
    while g <= hi:
        zoom.axvline(g, color="#cbd5e1", linewidth=0.7, zorder=0)
        g += step
    zoom.set_xlim(lo, hi)
    zoom.set_ylim(-0.8, len(present) - 0.2)
    zoom.set_yticks([])
    zoom.tick_params(labelsize=7)
    zoom.set_title("放大 0.5 s：竖线间隔 50 ms（20 Hz）", fontsize=8.2)
    # 插图必须不透明：否则底下那两条密集的带子会透上来，看不清
    zoom.set_facecolor("white")
    zoom.patch.set_alpha(1.0)
    zoom.patch.set_zorder(10)
    for spine in zoom.spines.values():
        spine.set_color("#94a3b8")
        spine.set_linewidth(1.0)

    fig.text(
        0.01, 0.015,
        "口径：快照 = S_SNAPSHOT（tcp.len ≥ 1000，即 12 B 协议帧头 + 快照载荷）；"
        "输入 = 客户端 20 Hz 定频上报的 C_INPUT（tcp.len 13 = 12 B 帧头 + 1 B 按键位图）。\n"
        "纯 ACK = TCP 层确认，无应用载荷；tcp.len 已含协议帧头。"
        "输入 1200 个 ÷ 15 s ÷ 4 客户端 = 20 Hz，与定频设计一致。",
        fontsize=8.0, color="#4b5563",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(out_path, dpi=170, facecolor="white")
    plt.close(fig)
    return totals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="出 E7 的两张图（图 6-14 总览 / 图 6-15 字段标注）")
    parser.add_argument("--pcap", type=Path, default=PROJECT_ROOT / "data" / "E7-capture.pcapng")
    parser.add_argument("--tshark", type=Path, default=DEFAULT_TSHARK)
    parser.add_argument("--out", type=Path,
                        default=PROJECT_ROOT / "docs" / "figures" / "fig6-15-frame-header.png")
    parser.add_argument("--tcp-len", type=int, default=1939,
                        help="挑哪个长度的帧：1939 = 4 人 + 30 敌机 + 200 子弹的满快照")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.pcap.exists():
        raise SystemExit(f"抓包文件不存在：{args.pcap}")
    if not args.tshark.exists():
        raise SystemExit(f"找不到 tshark：{args.tshark}")

    frame_no, payload = read_payload(args.pcap, args.tshark, args.tcp_len)
    info = verify(payload)
    print(f"[e7] 第 {frame_no} 帧，载荷 {len(payload)} B")
    print(f"[e7] magic=0x{info['magic']:04X} type=0x{info['type']:02X} "
          f"seq={info['seq']} length={info['length']}")
    print(f"[e7] tick={info['tick']} 玩家 {info['players']} 敌机 {info['enemies']} "
          f"子弹 {info['bullets']} 道具 {info['items']} boss={info['boss']}")

    if 12 + info["length"] != len(payload):
        raise SystemExit(
            f"校验失败：12 + length({info['length']}) != 载荷长度({len(payload)})"
        )
    plot_layout(payload, info, frame_no, args.out)
    print(f"[e7] 已写出 {args.out}")

    timeline_out = args.out.with_name("fig6-14-capture-overview.png")
    totals = plot_timeline(args.pcap, args.tshark, timeline_out)
    print(f"[e7] 已写出 {timeline_out}")
    for name, n in totals.items():
        print(f"[e7]   {name}: {n} 个")


if __name__ == "__main__":
    main()