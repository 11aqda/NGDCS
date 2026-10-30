"""读指标 CSV 出图 —— E9 的图 6-17 / 6-18 / 6-19 / 6-20。

E9 是「实体数 → 带宽 / CPU」的核心实验（`03-实验清单.md §5`），
这几张图直接支撑「同屏敌机上限 = 30、子弹上限 = 300」这个设计决策（D-011），
构成「设计 → 实测 → 反推约束」的闭环。

**2026-10-25 起，单帧耗时按四个阶段拆开画**（用户要求：碰撞与通信必须分开）：

    sim_ms        模拟（移动 / 剔除 / 补足）
    collision_ms  朴素 O(子弹×敌机) 碰撞判定
    ser_ms        序列化
    net_ms        广播发送

四段**严格相加等于总耗时**（计时点首尾相接），所以图 6-20 能画成 100% 堆叠。
图 6-17 是「总耗时 + 四段」的多线图 —— 关键不是谁高，而是**斜率不同**：
如果碰撞线陡、通信线平，就说明瓶颈在游戏逻辑、通信层是可扩展的。

数据来自 `server/metrics.py` 每秒写一行的 CSV。用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.plot --csv data/server_metrics.csv --out docs/figures --scenario E9-

**多轮实验的命名约定**：同一个档位重复跑时，场景名加 `-rN` 后缀，例如

    --scenario E9-e30-b200-r1     ← 第 1 轮
    --scenario E9-e30-b200-r2     ← 第 2 轮

`03-实验清单 §7` 要求每个实验至少跑 2 次并"取一致的结果"。
本工具会**每一轮单独丢热身**（因为服务端每重启一次 `t_mono` 就从 0 重新开始，
两轮在时间轴上完全重叠，混在一起算会把第二轮的不稳定期当成有效数据），
再按档位取平均画图，最后打印**多轮一致性**供判断。

三个容易踩的坑，这里都处理了：

1. **matplotlib 默认画不了中文** —— 不设字体的话标题全是方块。
2. **每一轮开头的几十秒不能要** —— 进程刚起来、客户端还没连满、缓存没热，
   这一段会把均值拉偏。所以默认丢掉每一轮**开头 10 秒**（`--warmup`）。
3. **没有客户端连接的时段不能要** —— 服务端空转时 tick 快得离谱、快照 0 B，
   混进来会把整档耗时拉低。已按 `client_count > 0` 过滤掉并报告丢弃行数。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from collections import defaultdict
from pathlib import Path

# 帧载荷上限：图 6-3 要标注"这个规模为什么没有数据点"
from protocol.framing import MAX_PAYLOAD

# ⚠️ 必须在 import matplotlib **之前**设好缓存目录。
# matplotlib 默认把字体缓存写到 C:\Users\<用户>\AppData\Local\matplotlib；
# 那个目录在开发机上不可写，它就会退而在**当前工作目录**建一个 matplotlib-xxxx
# 临时目录 —— 等于往仓库根目录拉屎，每次跑还重新建一次、导入慢好几秒。
# 显式指到项目内的 .cache/（已在 .gitignore 里）。
_MPL_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "matplotlib"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))

try:
    import matplotlib

    matplotlib.use("Agg")  # 无窗口后端：没有桌面 / 在后台也能出图
    import matplotlib.pyplot as plt

    HAVE_MPL = True
except ImportError:  # pragma: no cover - 取决于环境
    plt = None
    HAVE_MPL = False

# 不设中文字体，中文标题会画成一个个方块
if HAVE_MPL:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

# CSV 里需要当数字用的列（cpu_percent / mem_mb 可能为空，见 server/metrics.py）
NUMERIC_FIELDS = (
    "t_mono",
    "client_count",
    "enemies",
    "bullets",
    "tick_ms_avg",
    "tick_ms_p95",
    "tick_ms_max",
    "sim_ms",
    "collision_ms",
    "ser_ms",
    "net_ms",
    "encode_ms",
    "hits",
    "snapshot_bytes",
    "cpu_percent",
    "cpu_seconds",
    "mem_mb",
    "packets_out",
    "bytes_out",
    "packets_in",
    "bytes_in",
)

# tick 的四个阶段：CSV 列名 → (图例, 颜色, 点型)。
# 顺序就是 tick 里的执行顺序，堆叠图也按这个顺序往上堆。
PHASE_SERIES = (
    ("collision_ms", "碰撞判定", "tab:red", "o"),
    ("sim_ms", "模拟（移动/剔除/补足）", "tab:orange", "s"),
    ("ser_ms", "序列化", "tab:blue", "^"),
    ("net_ms", "广播发送", "tab:green", "v"),
)

# tick 预算：20 Hz → 50 ms。单帧耗时逼近它就意味着掉帧
TICK_BUDGET_MS = 50.0

# D-011 定的「舒适线」：单核占用超过 50% 就没有余量应对峰值
CPU_COMFORT_PERCENT = 50.0

# 场景名末尾的 `-rN` = 第 N 轮（同一个档位重复跑）
_RUN_SUFFIX = re.compile(r"-r(\d+)$")

# 多轮之间允许的最大相对偏差；超过就提示"要查明原因"（03 §7）
AGREEMENT_TOLERANCE_PERCENT = 10.0

# 低于这个单核占用率时，逐秒 CPU 读数受调度计时粒度量化，偏差大属正常
LOW_LOAD_CPU_PERCENT = 5.0


def load_rows(path: str | Path) -> list[dict]:
    """读 CSV；数字列转 float，空值转 None（psutil 没装时 cpu/mem 是空的）。"""
    rows: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row: dict = {"scenario_id": (raw.get("scenario_id") or "adhoc").strip()}
            for field in NUMERIC_FIELDS:
                text = (raw.get(field) or "").strip()
                row[field] = float(text) if text else None
            rows.append(row)
    return rows


def group_by_scenario(rows: list[dict]) -> dict[str, list[dict]]:
    """按 scenario_id 切分 —— 这就是 §4.3 要求每行都带场景 ID 的原因。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["scenario_id"]].append(row)
    return dict(groups)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_cpu_percent(kept: list[dict]) -> float:
    """**整轮** CPU%：累计 CPU 秒数的首尾差 ÷ 墙钟首尾差。

    为什么不用「逐秒 `cpu_percent` 求平均」：进程 CPU 时间是按调度时钟更新的
    （Windows 上约 15.6 ms 一跳）。服务端每秒只花 ~20 ms CPU 时（例如 30 敌机 + 200 子弹），
    单行会读成 **0% 或 1.56%** —— 实测两轮逐秒均值为 2.6% 与 0.5%，差 66%。

    用累计值的首尾差，只有**两个端点**各带一次量化误差，
    再除以几分钟的整轮时长就基本消失。前提：`cpu_seconds` 单调递增（进程累计 CPU 时间）。

    数据里没有 `cpu_seconds` 列（旧 CSV，或没装 psutil）时返回 0.0，由调用方兜底。
    """
    pairs = [
        (row.get("t_mono"), row.get("cpu_seconds"))
        for row in kept
        if row.get("t_mono") is not None and row.get("cpu_seconds") is not None
    ]
    if len(pairs) < 2:
        return 0.0

    first = min(pairs, key=lambda item: item[0])
    last = max(pairs, key=lambda item: item[0])
    span = last[0] - first[0]
    if span <= 0:
        return 0.0
    return (last[1] - first[1]) / span * 100.0


def summarize(rows: list[dict], warmup_s: float = 10.0) -> dict:
    """丢掉开头 warmup_s 秒，再对剩下的行取平均。

    用 t_mono（单调时钟）算相对时间 —— 这也是 §4.3「时间戳用单调时钟」的兑现。
    """
    timed = [r for r in rows if r["t_mono"] is not None]
    if not timed:
        return {}

    start = min(r["t_mono"] for r in timed)
    kept = [r for r in timed if r["t_mono"] - start >= warmup_s]
    if not kept:  # 实验太短，热身窗口比整个实验还长：退化成全部数据
        kept = timed

    def values(field: str) -> list[float]:
        return [r[field] for r in kept if r[field] is not None]

    players = _mean(values("client_count"))
    enemies = _mean(values("enemies"))
    bullets = _mean(values("bullets"))
    bytes_out = _mean(values("bytes_out"))

    # CPU 优先用「整轮首尾差」算（精确），拿不到才退回逐秒均值（旧数据兜底）
    cpu_percent = run_cpu_percent(kept) or _mean(values("cpu_percent"))

    phases = {field: _mean(values(field)) for field, _, _, _ in PHASE_SERIES}

    summary = {
        "rows": len(kept),
        "players": players,
        "enemies": enemies,
        "bullets": bullets,
        "entities": players + enemies + bullets,
        "tick_ms_avg": _mean(values("tick_ms_avg")),
        "tick_ms_p95": _mean(values("tick_ms_p95")),
        "hits": _mean(values("hits")),
        "snapshot_bytes": _mean(values("snapshot_bytes")),
        "cpu_percent": cpu_percent,
        "cpu_percent_avg_of_rows": _mean(values("cpu_percent")),
        "mem_mb": _mean(values("mem_mb")),
        # 每行是一个约 1 秒的窗口，所以 bytes_out 就是 B/s；再除以客户端数
        "bw_per_client_bps": bytes_out / players if players else 0.0,
    }
    summary.update(phases)
    # **嵌套**计时：`encode_ms` 是 `ser_ms` 内部的细分，不参与四段相加。
    # E1 的图 6-2 用它 —— 因为 ser_ms 里含共享的实体对象构造开销，会把编码差异淹没。
    summary["encode_ms"] = _mean(values("encode_ms"))
    # 逻辑侧 / 通信侧：用户要求「碰撞与通信分开」，所以这两条聚合线也要能直接画
    summary["logic_ms"] = phases["sim_ms"] + phases["collision_ms"]
    summary["comms_ms"] = phases["ser_ms"] + phases["net_ms"]
    # 编码在序列化里的占比：E1 用它说明「ser 里有多少真的花在编码上」
    summary["encode_share"] = (
        summary["encode_ms"] / phases["ser_ms"] if phases["ser_ms"] else 0.0
    )
    return summary


def split_scenario_id(scenario_id: str) -> tuple[str, int]:
    """把 `E9-e30-b200-r2` 拆成 `("E9-e30-b200", 2)`。

    没有 `-rN` 后缀的算作第 1 轮 —— 这样单轮实验不用改命名习惯。

    **为什么两轮必须分开算**：服务端每重启一次，`t_mono` 就从 0 重新开始
    （它是"自本进程启动以来的秒数"）。所以两次运行的数据在时间轴上**完全重叠**，
    如果混在一起丢热身，第二轮开头那段"刚启动、客户端还没连满"的不稳定数据
    会被当成有效数据算进均值 —— 数字会偏低，而且看不出来。
    """
    match = _RUN_SUFFIX.search(scenario_id)
    if match is None:
        return scenario_id, 1
    return scenario_id[: match.start()], int(match.group(1))


def summarize_runs(
    groups: dict[str, list[dict]], warmup_s: float = 10.0
) -> dict[str, list[dict]]:
    """**每一轮单独**汇总，再按档位归类：`{档位: [第1轮汇总, 第2轮汇总, ...]}`。

    03-实验清单 §7 要求「每个实验至少跑 2 次，取一致的结果」，
    所以两轮的汇总都要留着 —— 后面要拿它们做一致性校验，不能一上来就平均掉。
    """
    per_level: dict[str, list[dict]] = defaultdict(list)
    for scenario_id, rows in groups.items():
        summary = summarize(rows, warmup_s)
        if not summary:
            continue
        level, run_index = split_scenario_id(scenario_id)
        summary["scenario_id"] = scenario_id
        summary["level"] = level
        summary["run"] = run_index
        per_level[level].append(summary)

    for runs in per_level.values():
        runs.sort(key=lambda item: item["run"])
    return dict(per_level)


def merge_runs(runs: list[dict]) -> dict:
    """把一个档位的多轮汇总成**一个点**：数值字段取平均。

    非数值字段（名字）保留第一轮的；`runs` 记下这个点由几轮合出来。
    """
    if not runs:
        return {}

    merged: dict = {}
    for key, value in runs[0].items():
        if key in ("scenario_id", "level", "run"):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            merged[key] = _mean([r[key] for r in runs])
        else:
            merged[key] = value

    merged["scenario_id"] = runs[0]["level"]  # 图上用档位名，不带 -rN
    merged["level"] = runs[0]["level"]
    merged["runs"] = len(runs)
    return merged


def series_from_runs(per_level: dict[str, list[dict]]) -> list[dict]:
    """每个档位一个点，按实体总数排序（画图的横轴顺序）。"""
    series = [merge_runs(runs) for runs in per_level.values()]
    series = [item for item in series if item]
    series.sort(key=lambda item: item["entities"])
    return series


def run_agreement(runs: list[dict], field: str = "tick_ms_avg") -> float:
    """多轮之间在某个指标上的**最大相对偏差（%）**。

    `03 §7` 说「每个实验至少跑 2 次，取一致的结果；差异大要查明原因」——
    这个函数就是"一致"的量化。经验阈值：**超过 10% 就要查**，
    超过 20% 基本说明有一轮受了干扰（后台程序、温度墙、内存回收）。
    """
    values = [item[field] for item in runs if item.get(field)]
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    if mean == 0:
        return 0.0
    return max(abs(value - mean) for value in values) / mean * 100.0


def load_series(
    rows: list[dict], warmup_s: float = 10.0
) -> tuple[list[dict], dict[str, list[dict]]]:
    """完整流程：按场景切分 → **每轮单独汇总** → 按档位合并 → 排序。

    返回 `(series, per_level_runs)`：

    - `series`          —— 画图用，每个档位一个点（多轮已取平均）
    - `per_level_runs`  —— 校验用，每轮各自的汇总（一致性检查要它）
    """
    per_level = summarize_runs(group_by_scenario(rows), warmup_s)
    return series_from_runs(per_level), per_level


def _annotate(ax, xs, ys, labels) -> None:
    """给数据点加「敌/弹」标注。

    两条规则，都是为了在**低档位挤在一起**时不糊成一团：

    1. **上下交替** —— 10/50、20/100、30/200 的实体数是 64 / 124 / 234，
       而横轴要到 2254，全标在上方必然重叠
    2. **间距不足就跳过** —— 相邻标注横向间隔小于轴长的 6% 时干脆不标，
       少一个标注比两个糊在一起好读（被跳过的档位在控制台表格与实验记录里都有）
    """
    span = (max(xs) - min(xs)) if len(xs) > 1 else 0
    min_gap = span * 0.06

    last_labeled_x = None
    for index, (x, y, label) in enumerate(zip(xs, ys, labels)):
        if last_labeled_x is not None and (x - last_labeled_x) < min_gap:
            continue
        last_labeled_x = x

        above = index % 2 == 0
        ax.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=(0, 8 if above else -18),
            ha="center",
            va="bottom" if above else "top",
            fontsize=7.5,
        )


# E1 用：从「已剥掉 -rN 的场景名」里解出档位与编码
# `E1-e30-b200-json` → 敌机 30 / 子弹 200 / 编码 json
# `E9-e30-b200`      → 不带编码段，视为 binary（E9 用的就是默认编码）
_E1_LEVEL = re.compile(r"^(?P<exp>\w+?)-e(?P<enemies>\d+)-b(?P<bullets>\d+)(?:-(?P<encoder>[a-z_]+))?$")

# 图上的固定顺序（三张图、所有柱子/折线都用同一套顺序与颜色，便于对照阅读）
ENCODER_ORDER = ("binary", "binary_fast", "json")
ENCODER_LABELS = {
    "binary": "二进制（逐条目 pack）",
    "binary_fast": "二进制（整帧单次 pack）",
    "json": "JSON（短键名）",
}
ENCODER_COLORS = {"binary": "#1f77b4", "binary_fast": "#2ca02c", "json": "#ff7f0e"}


def split_e1_level(level_key: str) -> tuple[int, int, str] | None:
    """`E1-e30-b200-json` → `(30, 200, "json")`；解不出来返回 None。

    没有编码段的（`E9-e30-b200`）按 `binary` 处理 —— E9 跑的就是默认编码。
    """
    match = _E1_LEVEL.match(level_key)
    if match is None:
        return None
    return (
        int(match.group("enemies")),
        int(match.group("bullets")),
        match.group("encoder") or "binary",
    )


# 场景名里**真的有**编码段（用来决定出哪一套图）。
# 不能靠"encoder != binary"判断：`E1-...-binary` 是有编码段的，而 `E9-...` 没有。
_E1_HAS_ENCODER = re.compile(r"-e\d+-b\d+-[a-z_]+$")


def has_encoder_segment(level_key: str) -> bool:
    """场景名里带编码段吗？`E1-e30-b200-json` 是，`E9-e30-b200` 不是。"""
    return bool(_E1_HAS_ENCODER.search(level_key))


def e1_by_encoder(per_level_runs: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """把（已按档位合并的）序列按**编码器**分组，每组内按实体数排序。

    E1 的三张图都是「同一档位下比编码」，或者「同一编码下看趋势」——
    所以分组维度是编码器，而不是档位。
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for level_key, runs in per_level_runs.items():
        parsed = split_e1_level(level_key)
        if parsed is None:
            continue
        _, _, encoder = parsed
        merged = merge_runs(runs)
        if not merged:
            continue
        merged["encoder"] = encoder
        grouped[encoder].append(merged)

    for items in grouped.values():
        items.sort(key=lambda item: item["entities"])
    # 固定顺序：即使某种编码缺席，图例顺序也不乱跳
    return {name: grouped[name] for name in ENCODER_ORDER if name in grouped}


def _reference_point(series: list[dict], enemies: int, bullets: int) -> dict | None:
    """取某个档位的数据点（默认取 30/200 —— D-011 的设计目标规模）。"""
    for item in series:
        if round(item["enemies"]) == enemies and round(item["bullets"]) == bullets:
            return item
    return None


def plot_e1(
    by_encoder: dict[str, list[dict]],
    out_dir: str | Path,
    reference: tuple[int, int] = (30, 200),
) -> list[Path]:
    """出 E1 的三张图（图 6-1 / 6-2 / 6-3）。返回写出的文件路径。"""
    if not HAVE_MPL:
        raise RuntimeError("需要 matplotlib 才能出图：pip install matplotlib")
    if not by_encoder:
        raise ValueError("没有 E1 数据；确认场景名形如 E1-e30-b200-json-r1")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    names = list(by_encoder)
    colors = [ENCODER_COLORS.get(name, "#333333") for name in names]
    tick_labels = [ENCODER_LABELS.get(name, name) for name in names]

    # ---- 图 6-1 / 6-2：同一档位下的柱状对比 ----
    ref_enemies, ref_bullets = reference
    ref_points = [_reference_point(by_encoder[name], ref_enemies, ref_bullets) for name in names]

    if all(point is not None for point in ref_points):
        bars = [
            (
                "snapshot_bytes", "平均快照大小 (字节)", "图 6-1 二进制 vs JSON 包大小",
                "fig6-01-encoder-snapshot-size.png",
                lambda p: f"{p['snapshot_bytes']:.0f} B",
                # 图注要把口径钉死，否则答辩时说不清这根柱子到底量了什么
                # （matplotlib 不认 Markdown，别在图上写 ** 号）
                f"口径：快照载荷（不含 12 B 帧头）；{ref_enemies} 敌机 / {ref_bullets} 子弹、"
                f"无道具；JSON = list[dict] + separators=(',',':') + ensure_ascii=False",
            ),
            (
                # 用 **encode_ms** 而不是 ser_ms：ser_ms 含共享的实体对象构造开销
                #（900 个 dataclass 实例），三种编码都要付，会把差异淹没成三根一样高的柱子
                "encode_ms", "编码耗时 (ms)", "图 6-2 二进制 vs JSON 编码耗时",
                "fig6-02-encoder-ser-time.png",
                lambda p: f"{p['encode_ms']:.3f} ms",
                "口径：encode_ms 只量 encoder.encode() 这一步，不含实体对象构造；\n"
                "ser_ms 是 tick 四段里的「序列化整段」（= 实体构造 + 编码），"
                "三种编码的实体构造开销相同",
            ),
        ]
        for field, ylabel, title, filename, fmt, caption in bars:
            fig, ax = plt.subplots(figsize=(7.4, 5.2))
            values = [point[field] for point in ref_points]
            rects = ax.bar(range(len(names)), values, color=colors, width=0.6)
            for rect, value in zip(rects, values):
                ax.annotate(
                    fmt({"snapshot_bytes": value, "encode_ms": value, "ser_ms": value}),
                    (rect.get_x() + rect.get_width() / 2, value),
                    textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=9,
                )
            # 相对 binary 的倍数直接标在图上 —— 这正是 E1 的结论
            base = values[0]
            if base:
                ratios = "/".join(f"{v / base:.1f}×" for v in values)
                ax.set_title(f"{title}\n（相对 binary：{ratios}）", fontsize=11)
            else:
                ax.set_title(title, fontsize=11)
            ax.set_xticks(range(len(names)))
            ax.set_xticklabels(tick_labels, fontsize=8.5)
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.3, axis="y")
            ax.set_ylim(0, max(values) * 1.30 if max(values) else 1)
            # 图注放在图下方（figure 坐标），不挤压绘图区
            fig.text(0.02, 0.015, caption, fontsize=7.2, va="bottom", ha="left", color="#444444")
            path = out_dir / filename
            fig.tight_layout(rect=(0, 0.075, 1, 1))
            fig.savefig(path, dpi=150)
            plt.close(fig)
            written.append(path)

    # ---- 图 6-3：CPU 占用随实体数变化（每种编码一条线）----
    fig, ax = plt.subplots(figsize=(8.6, 5.6))
    for name in names:
        series = by_encoder[name]
        ax.plot(
            [item["entities"] for item in series],
            [item["cpu_percent"] for item in series],
            marker="o", linewidth=1.8, markersize=6,
            color=ENCODER_COLORS.get(name, "#333333"),
            label=ENCODER_LABELS.get(name, name),
        )
    ax.axhline(
        CPU_COMFORT_PERCENT, color="crimson", linestyle="--", linewidth=1,
        label=f"{CPU_COMFORT_PERCENT:.0f}% 舒适线（D-011）",
    )

    # 有的编码在最高档位**没有数据** —— 那多半不是"漏跑"，而是撞上了协议上限。
    # 必须在图上标出来，否则读者会以为只是没测，看不到"这条路走不通"这个结论。
    all_levels = sorted(
        {
            (round(item["enemies"]), round(item["bullets"]), item["entities"])
            for series in by_encoder.values()
            for item in series
        },
        key=lambda triple: triple[2],
    )
    peak = max(
        (item["cpu_percent"] for series in by_encoder.values() for item in series),
        default=1.0,
    )
    for name in names:
        have = {
            (round(item["enemies"]), round(item["bullets"])) for item in by_encoder[name]
        }
        for enemies, bullets, entities in all_levels:
            if (enemies, bullets) in have:
                continue
            color = ENCODER_COLORS.get(name, "#333333")
            ax.annotate(
                f"{ENCODER_LABELS.get(name, name)}\n此规模无法发送\n"
                f"（载荷超出 {MAX_PAYLOAD // 1024} KiB 帧上限）",
                xy=(entities, 0.5),
                xytext=(entities, peak * 0.45),
                ha="center", fontsize=7.5, color=color,
                arrowprops=dict(
                    arrowstyle="->", color=color, linewidth=1.2, linestyle="--"
                ),
            )

    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("服务端单核占用 (%)")
    ax.set_title("图 6-3 编码方式对 CPU 占用的影响")
    # 留出右边距：最高档位的"无法发送"标注是以该点为中心排版的，贴边会被裁掉
    ax.margins(x=0.14)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8.5, loc="upper left")
    fig.text(
        0.02, 0.015,
        "口径：CPU 用累计 CPU 秒数的首尾差 ÷ 墙钟首尾差算整轮值；"
        "低负载（<5%）时逐秒读数受调度计时粒度量化，以 tick_ms 为准。\n"
        "JSON 在最大规模下没有数据点 = 载荷超出协议帧上限、根本发不出去"
        "（不是漏测，详见 E1 实验记录）。",
        fontsize=7.2, va="bottom", ha="left", color="#444444",
    )
    path = out_dir / "fig6-03-encoder-cpu.png"
    fig.tight_layout(rect=(0, 0.085, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    return written


def plot_e9(series: list[dict], out_dir: str | Path) -> list[Path]:
    """出 E9 的三张图。返回写出的文件路径。"""
    if not HAVE_MPL:
        raise RuntimeError("需要 matplotlib 才能出图：pip install matplotlib")
    if not series:
        raise ValueError("没有任何可用数据；检查 CSV 路径与 scenario_id")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    xs = [s["entities"] for s in series]
    labels = [f"{s['enemies']:.0f}/{s['bullets']:.0f}" for s in series]

    # ---- 图 6-17：实体数 vs 单帧耗时（四段拆开画）----
    #
    # 一条总耗时线回答不了「瓶颈在游戏逻辑还是通信层」。
    # 四段是**严格相加等于总耗时**的（计时点首尾相接），所以这里既画总线上限，
    # 也画每段各自的增长斜率 —— 斜率不同才是重点。
    fig, ax = plt.subplots(figsize=(8, 5))
    ys = [s["tick_ms_avg"] for s in series]
    p95 = [s["tick_ms_p95"] for s in series]
    errors = [max(0.0, hi - lo) for hi, lo in zip(p95, ys)]

    ax.errorbar(
        xs, ys, yerr=errors, marker="D", color="black", linewidth=2,
        capsize=3, label="tick 总耗时（误差棒 = p95）",
    )
    for field, label, color, marker in PHASE_SERIES:
        ax.plot(
            xs, [s[field] for s in series], marker=marker, color=color,
            linewidth=1.4, markersize=5, alpha=0.9, label=label,
        )

    ax.axhline(TICK_BUDGET_MS, color="crimson", linestyle="--", linewidth=1,
               label=f"tick 预算 {TICK_BUDGET_MS:.0f} ms（20 Hz）")
    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("单帧耗时 (ms)")
    ax.set_title("图 6-17 实体数 vs 单帧耗时（按阶段拆解）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    _annotate(ax, xs, ys, [f"敌/弹 {lb}" for lb in labels])
    path = out_dir / "fig6-17-entities-vs-tick.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    # ---- 图 6-18：实体数 vs 带宽 ----
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bw = [s["bw_per_client_bps"] / 1024 for s in series]
    ax.plot(xs, bw, marker="o", color="tab:blue", label="下行带宽 / 客户端 (KB/s)")
    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("下行带宽 (KB/s per 客户端)", color="tab:blue")
    ax.tick_params(axis="y", labelcolor="tab:blue")

    snap_ax = ax.twinx()
    snap = [s["snapshot_bytes"] for s in series]
    snap_ax.plot(xs, snap, marker="s", linestyle="--", color="tab:orange",
                 label="单份快照大小 (B)")
    snap_ax.set_ylabel("快照大小 (B)", color="tab:orange")
    snap_ax.tick_params(axis="y", labelcolor="tab:orange")

    ax.set_title("图 6-18 实体数 vs 带宽")
    ax.grid(alpha=0.3)
    lines = ax.get_lines() + snap_ax.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], loc="upper left")
    path = out_dir / "fig6-18-entities-vs-bandwidth.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    # ---- 图 6-19：实体数 vs 单核占用 ----
    fig, ax = plt.subplots(figsize=(7, 4.5))
    cpu = [s["cpu_percent"] for s in series]
    ax.plot(xs, cpu, marker="o", color="tab:red", label="服务端进程单核占用")
    ax.axhline(CPU_COMFORT_PERCENT, color="gray", linestyle="--", linewidth=1,
               label=f"{CPU_COMFORT_PERCENT:.0f}% 舒适线（D-011）")
    ax.set_xlabel("同屏实体总数（玩家 + 敌机 + 子弹）")
    ax.set_ylabel("单核占用 (%)")
    ax.set_title("图 6-19 实体数 vs 单核占用")
    ax.grid(alpha=0.3)
    ax.legend()
    _annotate(ax, xs, cpu, [f"敌/弹 {lb}" for lb in labels])
    path = out_dir / "fig6-19-entities-vs-cpu.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    # ---- 图 6-20（新增）：耗时构成占比 ----
    #
    # 四段严格相加等于总耗时，所以这里画 100% 堆叠柱，不存在"其它"。
    # 这张图回答的是「随实体数增长，钱花在哪变了没有」——
    # 如果通信占比随实体数**下降**，就说明通信层是可扩展的、瓶颈在逻辑侧。
    fig, ax = plt.subplots(figsize=(11, 5))
    bottoms = [0.0] * len(series)
    for field, label, color, _ in PHASE_SERIES:
        shares = [
            (s[field] / s["tick_ms_avg"] * 100) if s["tick_ms_avg"] else 0.0
            for s in series
        ]
        ax.bar(labels, shares, bottom=bottoms, color=color, label=label)
        bottoms = [b + v for b, v in zip(bottoms, shares)]

    # 在柱子顶上标出「节拍 %」= 单核占用 × 20 Hz 窗口占比，即这 50 ms 里花了多少
    for index, bottom in enumerate(bottoms):
        ax.text(
            index, min(bottom + 1.5, 101.5),
            f"总计 {series[index]['tick_ms_avg']:.2f} ms\n"
            f"碰撞命中 {series[index]['hits']:.0f}/s",
            ha="center", va="bottom", fontsize=7.5,
        )

    ax.set_ylim(0, 112)
    ax.set_xlabel("场景（敌机 / 子弹）")
    ax.set_ylabel("占 tick 总耗时的比例 (%)")
    ax.set_title("图 6-20 单帧耗时构成占比")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=8, loc="lower right")
    path = out_dir / "fig6-20-time-composition.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    return written


E2_LEVEL_PATTERN = re.compile(r"^E2-c(\d+)$")


def parse_e2_clients(level: str) -> int | None:
    """`E2-c200` → 200；不是 E2 的档位返回 None。"""
    match = E2_LEVEL_PATTERN.match(level)
    return int(match.group(1)) if match else None


def e2_actual_clients(item: dict, requested: int) -> float:
    """横轴用**实测在线数**，不是请求的连接数。

    为什么必须这样（2026-10-30 踩到）：机器人全跑在一个 Python 进程里，受 GIL 限制，
    250 个 asyncio 客户端心跳会延迟，超过服务端 15 s 超时就被踢掉 ——
    请求 250 实际只有 238 在线。

    如果用请求值当横轴，图上的点会**站在一个它并没有达到的位置**上，
    和其他档位比较时斜率也是错的。宁可横轴出现 238 这种"不圆整"的数，
    也不能拿没达到的并发数去标定性能。
    """
    actual = item.get("players")
    if actual is None or actual <= 0:
        return float(requested)
    return float(actual)


def load_e2_rtt(run_dir: str | Path, skip_clients: set[int] | None = None) -> dict[int, dict]:
    """从机器人汇总里取 RTT 分位数，按连接数归档并对多轮取平均。

    **RTT 不在服务端 CSV 里** ——它是客户端量出来的（心跳往返），
    所以图 6-6 必须读 `data/runs/E2-c*-r*.json`。

    `skip_clients`：要排除的连接数。**必须传** —— 服务端崩过的档位
    （如 E2-c300）仍有机器人汇总，但它的 RTT 是"服务器已经不广播了"的产物，
    画上去会出现 P99 **反而下降**的假象。
    """
    import json

    skip_clients = skip_clients or set()
    by_clients: dict[int, list[dict]] = defaultdict(list)
    for path in sorted(Path(run_dir).glob("E2-c*-r*.json")):
        match = re.match(r"E2-c(\d+)-r(\d+)$", path.stem)
        if match is None:
            continue
        clients = int(match.group(1))
        if clients in skip_clients:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        sample = {
            "p50": data.get("rtt_p50_ms"),
            "p95": data.get("rtt_p95_ms"),
            "p99": data.get("rtt_p99_ms"),
            "interval_p50": data.get("interval_p50_ms"),
        }
        if sample["p50"] is None:
            continue
        by_clients[clients].append(sample)

    merged: dict[int, dict] = {}
    for clients, samples in by_clients.items():
        merged[clients] = {}
        for key in ("p50", "p95", "p99", "interval_p50"):
            values = [s[key] for s in samples if s.get(key) is not None]
            # ⚠️ 不能直接 `_mean(values)`：它对空列表返回 0.0，
            # 而"缺 p99"（2026-10-30 之前的旧数据）会因此被画成一条贴着 0 的假线
            merged[clients][key] = _mean(values) if values else None
        merged[clients]["runs"] = len(samples)
    return merged


def plot_e2(
    series: list[dict], out_dir: str | Path, run_dir: str | Path = "data/runs",
    skip_levels: tuple[str, ...] = (),
) -> list[Path]:
    """出 E2 的三张图（图 6-4 / 6-5 / 6-6）：横轴是**连接数**。

    与 E9 的关键区别：E9 横轴是实体数，E2 横轴是连接数，而实体是**固定**的
    （D-029：4 玩家 + 30 敌机 + 200 子弹）。所以这三张图回答的是
    「**广播的规模效应**」—— 每个 tick 要往 N 个连接各写一次快照，N 涨了会怎样。
    """
    if not HAVE_MPL:
        raise RuntimeError("需要 matplotlib 才能出图：pip install matplotlib")

    points: list[tuple[float, int, dict]] = []
    for item in series:
        if item["level"] in skip_levels:
            # 服务端崩过的档位，指标行是被截断的样本：平均值反而变小，
            # 画上去会让曲线在末端"突然变轻松"，是**最误导人**的形状
            continue
        requested = parse_e2_clients(item["level"])
        if requested is None:
            continue
        points.append((e2_actual_clients(item, requested), requested, item))
    if not points:
        raise ValueError(
            "没有可识别的 E2 数据（场景名需形如 E2-c10-r1）；"
            "先用 tools/loadtest.py 跑一轮"
        )
    points.sort(key=lambda triple: triple[0])

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    xs = [actual for actual, _, _ in points]
    tick = [p["tick_ms_avg"] for _, _, p in points]
    cpu = [p["cpu_percent"] for _, _, p in points]
    mem = [p["mem_mb"] for _, _, p in points]
    x_label = "并发连接数（实测在线）"

    # ---- 图 6-4：连接数 vs CPU / 内存（双轴）----
    #
    # 两个量放一张图是因为它们回答同一个问题：「连接数涨了，服务端还撑得住吗」。
    # 但量纲不同（% vs MB），所以用左右双轴 —— **不要**为了塞进一张图而把内存换算成百分比，
    # 那是把两个独立的物理量强行混为一谈。
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.plot(xs, cpu, marker="o", color="tab:red", linewidth=1.8, label="CPU 单核占用")
    ax.set_xlabel(x_label)
    ax.set_ylabel("CPU 占用 (% of one core)", color="tab:red")
    ax.tick_params(axis="y", labelcolor="tab:red")
    ax.grid(alpha=0.3)

    ax2 = ax.twinx()
    ax2.plot(xs, mem, marker="s", color="tab:blue", linewidth=1.6,
             linestyle="--", label="进程内存")
    ax2.set_ylabel("进程内存 (MB)", color="tab:blue")
    ax2.tick_params(axis="y", labelcolor="tab:blue")

    ax.set_title("图 6-4 连接数 vs CPU / 内存")
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [ln.get_label() for ln in lines], fontsize=8, loc="upper left")
    _annotate(ax, xs, cpu, [f"{x:.0f}" for x in xs])
    path = out_dir / "fig6-04-clients-vs-cpu-mem.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    # ---- 图 6-5：连接数 vs tick 耗时 ----
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    p95 = [p["tick_ms_p95"] for _, _, p in points]
    ax.plot(xs, tick, marker="o", color="black", linewidth=2, label="tick 均耗时")
    ax.plot(xs, p95, marker="^", color="tab:orange", linewidth=1.4,
            linestyle="--", label="tick p95")
    ax.set_xlabel(x_label)
    ax.set_ylabel("单帧耗时 (ms)")
    ax.set_title("图 6-5 连接数 vs 单帧耗时")
    ax.grid(alpha=0.3)
    budget_in_view = max(max(tick), max(p95)) > TICK_BUDGET_MS * 0.2
    if budget_in_view:
        ax.axhline(TICK_BUDGET_MS, color="crimson", linestyle=":",
                   linewidth=1, label=f"tick 预算 {TICK_BUDGET_MS:.0f} ms（20 Hz）")
    ax.legend(fontsize=8)
    _annotate(ax, xs, tick, [f"{x:.0f}" for x in xs])
    path = out_dir / "fig6-05-clients-vs-tick.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)
    if not budget_in_view:
        print(f"[plot] 图 6-5：实测最大 {max(max(tick), max(p95)):.2f} ms 远低于 "
              f"{TICK_BUDGET_MS:g} ms 预算，预算线未画（会把曲线压成一条平线）")

    # ---- 图 6-6：RTT 分位数 ----
    skip_clients = {int(lv.split("-c")[-1]) for lv in skip_levels
                    if parse_e2_clients(lv) is not None}
    rtt = load_e2_rtt(run_dir, skip_clients=skip_clients)
    if rtt:
        # RTT 汇总按**请求的连接数**归档（文件名里只有请求值），
        # 但横轴必须换成**实测在线数** —— 与图 6-4/6-5 保持一致，
        # 否则同一档在两张图上会站在不同的 x 位置，读者会以为数据打架
        to_actual = {requested: actual for actual, requested, _ in points}
        rx = sorted(rtt)
        rxs = [to_actual.get(c, float(c)) for c in rx]
        fig, ax = plt.subplots(figsize=(7.5, 4.6))
        for key, label, color, marker in (
            ("p50", "RTT P50", "tab:green", "o"),
            ("p95", "RTT P95", "tab:orange", "s"),
            ("p99", "RTT P99", "tab:red", "^"),
        ):
            ys = [rtt[c].get(key) for c in rx]
            if all(v is None for v in ys):
                continue
            ax.plot(rxs, [v if v is not None else float("nan") for v in ys],
                    marker=marker, color=color, linewidth=1.5, label=label)
        ax.set_xlabel(x_label)
        ax.set_ylabel("心跳 RTT (ms)")
        ax.set_title("图 6-6 RTT 分位数随连接数的变化")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        path = out_dir / "fig6-06-clients-vs-rtt.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)
    else:
        print(f"[plot] 图 6-6 跳过：{run_dir} 里没有 E2 的机器人汇总（缺 RTT 数据）")

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="出图：E9 四张（图 6-17~6-20）或 E1 三张（图 6-1~6-3）"
    )
    parser.add_argument("--csv", default="data/server_metrics.csv", help="指标 CSV")
    parser.add_argument("--out", default="docs/figures", help="图片输出目录")
    parser.add_argument(
        "--warmup",
        type=float,
        default=10.0,
        help="**每一轮**开头丢掉多少秒（进程刚起来 / 客户端没连满）",
    )
    parser.add_argument(
        "--scenario",
        default="",
        help="只看 scenario_id 以它开头的场景（如 E9- / E1-）",
    )
    parser.add_argument(
        "--figures",
        default="auto",
        choices=("auto", "e9", "e1", "e2"),
        help="出哪一套图。auto = 数据里带编码段就出 E1 的三张，"
        "场景名是 E2-c* 就出 E2 的三张，否则出 E9 的四张"
        "（E1/E9 数据同时存在时按 --scenario 过滤后再判断）",
    )
    parser.add_argument(
        "--run-dir",
        default="data/runs",
        help="机器人汇总目录（图 6-6 的 RTT 只能从这里取）",
    )
    parser.add_argument(
        "--skip-levels",
        default="",
        help="逗号分隔的档位名，出图时排除（如 E2-c300 —— 服务端崩过的档，"
             "指标行被截断，画上去会让曲线末端假性变低）",
    )
    return parser.parse_args()


def _is_eligible(row: dict, scenario_prefix: str) -> bool:
    """只有**有效数据行**才参与统计。

    判据是 `tick_ms_avg` 有值 **且** 当时真有客户端连着 ——
    否则会把"服务端空转那几十秒"（tick 快得离谱、快照 0 B）算进均值，
    把整档的耗时拉低。这是做实验数据清洗时最容易漏的一步。
    """
    if not scenario_prefix or row["scenario_id"].startswith(scenario_prefix):
        return row["tick_ms_avg"] is not None and bool(row["client_count"])
    return False


def main() -> None:
    args = parse_args()
    all_rows = load_rows(args.csv)
    rows = [row for row in all_rows if _is_eligible(row, args.scenario)]

    if not rows:
        print(f"[plot] {args.csv} 里没有可用数据（场景前缀 {args.scenario!r}）")
        return

    dropped = len(all_rows) - len(rows)
    if dropped:
        print(
            f"[plot] 已丢弃 {dropped} 行无效数据"
            f"（无客户端连接 / 无 tick 记录；场景前缀 {args.scenario!r}）"
        )

    series, per_level_runs = load_series(rows, args.warmup)

    print(
        f"{'档位':<22}{'轮':>3}{'实体':>6}{'总ms':>8}{'碰撞ms':>8}"
        f"{'通信ms':>8}{'快照B':>8}{'KB/s':>8}{'CPU%':>7}{'hits/s':>8}"
    )
    for item in series:
        runs = per_level_runs[item["level"]]
        for run in runs:
            print(
                f"{run['scenario_id']:<22}{run['run']:>3}{run['entities']:>6.0f}"
                f"{run['tick_ms_avg']:>8.3f}{run['collision_ms']:>8.3f}"
                f"{run['comms_ms']:>8.3f}{run['snapshot_bytes']:>8.0f}"
                f"{run['bw_per_client_bps'] / 1024:>8.1f}"
                f"{run['cpu_percent']:>7.1f}{run['hits']:>8.0f}"
            )
        if len(runs) > 1:
            print(
                f"{'  ↑ ' + item['level'] + ' 多轮均值':<22}{item['runs']:>3}"
                f"{item['entities']:>6.0f}{item['tick_ms_avg']:>8.3f}"
                f"{item['collision_ms']:>8.3f}{item['comms_ms']:>8.3f}"
                f"{item['snapshot_bytes']:>8.0f}"
                f"{item['bw_per_client_bps'] / 1024:>8.1f}"
                f"{item['cpu_percent']:>7.1f}{item['hits']:>8.0f}"
            )

    # 03 §7：每个实验至少跑 2 次，取一致的结果；差异大要查明原因
    print("\n=== 多轮一致性（03 §7）===")
    flagged = 0
    for level, runs in sorted(per_level_runs.items(), key=lambda kv: kv[1][0]["entities"]):
        if len(runs) < 2:
            print(f"  {level:<22} 只有 {len(runs)} 轮 —— 未做一致性校验")
            continue
        tick_gap = run_agreement(runs, "tick_ms_avg")
        cpu_gap = run_agreement(runs, "cpu_percent")
        mean_cpu = _mean([r["cpu_percent"] for r in runs])

        if mean_cpu < LOW_LOAD_CPU_PERCENT:
            # 低负载下逐秒 CPU 读数被调度计时粒度量化，偏差大是正常的，
            # 不是数据有问题 —— 此时以 tick_ms 为准（它是进程内高精度计时）
            print(
                f"  {level:<22} 轮数 {len(runs)}  tick 偏差 {tick_gap:5.1f}%"
                f"  CPU 偏差 {cpu_gap:5.1f}%（均值仅 {mean_cpu:.1f}%，"
                f"低负载读数受计时粒度限制，以 tick 为准）"
            )
            continue

        bad = tick_gap > AGREEMENT_TOLERANCE_PERCENT
        flagged += bad
        mark = "  ⚠️ 要查明原因" if bad else ""
        print(
            f"  {level:<22} 轮数 {len(runs)}  tick 偏差 {tick_gap:5.1f}%"
            f"  CPU 偏差 {cpu_gap:5.1f}%{mark}"
        )
    if flagged:
        print(f"  → {flagged} 个档位偏差超过 {AGREEMENT_TOLERANCE_PERCENT:.0f}%，先别急着写进论文")
    else:
        print("  → 全部在容差内，可作正式数据")

    figure_set = args.figures
    if figure_set == "auto":
        if any(has_encoder_segment(k) for k in per_level_runs):
            figure_set = "e1"
        elif any(parse_e2_clients(k) is not None for k in per_level_runs):
            figure_set = "e2"
        else:
            figure_set = "e9"

    if figure_set == "e2":
        skip = tuple(x.strip() for x in args.skip_levels.split(",") if x.strip())
        if skip:
            print(f"[plot] 排除档位：{', '.join(skip)}")
        for path in plot_e2(series, args.out, args.run_dir, skip_levels=skip):
            print(f"[plot] 已写出 {path}")
        return

    if figure_set == "e1":
        by_encoder = e1_by_encoder(per_level_runs)
        if not by_encoder:
            print("[plot] 没有可识别的 E1 数据（场景名需形如 E1-e30-b200-json-r1）")
            return

        # E1 的头号指标是 `encode_ms`，所以它的多轮一致性必须单独报 ——
        # 上面那张表只查了 tick 和 CPU，而"binary_fast 到底有没有更快"
        # 全靠 encode_ms，不报它的噪声就没法判断几 % 的差是不是信号。
        print("\n=== E1 编码耗时的一致性（判断几 % 的差异是不是噪声）===")
        print(f"  {'档位':<26}{'编码':<14}{'轮均值ms':>10}{'轮间偏差':>10}")
        for level, runs in sorted(
            per_level_runs.items(), key=lambda kv: kv[1][0]["entities"]
        ):
            parsed = split_e1_level(level)
            encoder = parsed[2] if parsed else "?"
            values = [r["encode_ms"] for r in runs if r.get("encode_ms")]
            mean = _mean(values)
            gap = run_agreement(runs, "encode_ms")
            note = ""
            if len(runs) < 2:
                note = "（只有 1 轮）"
            elif gap > AGREEMENT_TOLERANCE_PERCENT and mean < 0.2:
                # 0.2 ms 以下绝对值太小，相对偏差被放大；此时以 tick_ms 为准
                note = "（绝对值小，相对偏差被放大）"
            print(
                f"  {level:<26}{encoder:<14}{mean:>10.4f}{gap:>9.1f}%{note}"
            )

        print(f"\n=== 按编码器分组（{len(by_encoder)} 种）===")
        for name, items in by_encoder.items():
            print(f"  {name:<12} 档位 {len(items)} 个：" +
                  ", ".join(f"{i['enemies']:.0f}/{i['bullets']:.0f}" for i in items))
            for item in items:
                print(
                    f"    实体 {item['entities']:>5.0f}  快照 {item['snapshot_bytes']:>7.0f} B"
                    f"  编码 {item['encode_ms']:>6.3f} ms"
                    f"（占序列化 {item['encode_share'] * 100:>4.1f}%）"
                    f"  序列化 {item['ser_ms']:>6.3f} ms  广播 {item['net_ms']:>6.3f} ms"
                    f"  总 {item['tick_ms_avg']:>7.3f} ms  CPU {item['cpu_percent']:>5.1f}%"
                )
        for path in plot_e1(by_encoder, args.out):
            print(f"[plot] 已写出 {path}")
        return

    for path in plot_e9(series, args.out):
        print(f"[plot] 已写出 {path}")


if __name__ == "__main__":
    main()