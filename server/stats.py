"""每秒一个统计窗口：tick 耗时的**分段拆解** + 快照体积 + 收发流量。

D-022 说 7b 的目的是「**测输入处理负载**」；第 8 步要的是 E9 需要的那组数。

**2026-10-25 补充：tick 内部拆成四段。** 只报一个总耗时回答不了
「瓶颈在游戏逻辑还是通信层」，而这正是本课题的核心问题：

    sim_ms        玩家按输入移动 + 实体移动 + 出屏剔除 + 补足数量
    collision_ms  朴素 O(子弹×敌机) 碰撞判定
    ser_ms        pack_snapshot：把几百个实体逐个 struct.pack
    net_ms        逐客户端 write + await drain

    逻辑耗时 = sim + collision     通信耗时 = ser + net

四段都取**平均值**（不是 p95），而且**四段恰好把 tick 切成四块**：
`sim + collision + ser + net` 在数学上就等于 `tick_ms_avg`
（五处计时点首尾相接，从 `started` 到 `net_done` 一次不多一次不少），
所以堆叠图能画成 100%，不存在"其它"这一类。
用 p95 反而不可相加，画不了堆叠。

纯逻辑、无 IO，所以能直接单测。
"""

from __future__ import annotations

# 四个可测阶段；顺序就是 tick 里的执行顺序
PHASES = ("sim", "collision", "ser", "net")

# 中文名，给图和日志用
PHASE_LABELS = {
    "sim": "模拟（移动/剔除/补足）",
    "collision": "碰撞判定",
    "ser": "序列化",
    "net": "广播发送",
}

# 逻辑侧 / 通信侧的归并（图里画成两条聚合线）
LOGIC_PHASES = ("sim", "collision")
COMMS_PHASES = ("ser", "net")

# **嵌套**在某个阶段内部的细分计时，不参与四段相加。
#
# `encode` 嵌在 `ser` 里：`ser` 量的是整个 `build_snapshot()`，其中包含
# **实体对象的构造**（100 敌机 + 800 子弹 = 900 个 dataclass 实例），
# 而那一部分是所有编码器共享的。E1 要比"编码方式"的差异，
# 就必须把 `encoder.encode()` 这一步单独拎出来量 ——
# 否则三根柱子会被共享开销压成一样高，什么也证明不了。
#
# 约束：`encode_ms ≤ ser_ms`（嵌套关系），所以它**不能**和四段一起相加。
NESTED_TIMERS = ("encode",)

NESTED_LABELS = {"encode": "编码调用（嵌套在序列化内）"}


def percentile(values: list[float], p: float) -> float:
    """简单分位数：p=0.5 中位数，p=0.95 是 95% 分位。

    和 bot/main.py 里的同名函数算法一致，这里没有共用是为了不让
    server 去 import bot（那是实验工具，不是服务端依赖）。
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[int(round((len(ordered) - 1) * p))]


class TickStats:
    """累计一个窗口的数据，flush() 时取走并清零。

    窗口由调用方控制：服务端每 20 个 tick（约 1 秒）flush 一次，
    所以 flush() 返回的 `packets_in` 就**等于每秒收到的帧数**。
    """

    def __init__(self) -> None:
        self._durations: list[float] = []
        self._phase_totals = {name: 0.0 for name in PHASES}
        self._phase_counts = {name: 0 for name in PHASES}
        self._nested_totals = {name: 0.0 for name in NESTED_TIMERS}
        self._nested_counts = {name: 0 for name in NESTED_TIMERS}
        self._hits = 0
        self._packets_in = 0
        self._bytes_in = 0
        self._packets_out = 0
        self._bytes_out = 0
        self._snapshot_bytes = 0
        self._snapshots = 0

    # --- 记录 ---------------------------------------------------------------

    def record_tick(self, duration_s: float) -> None:
        """记一次 tick 的**总**耗时（秒）。包住四段 + 记账开销，不含 sleep。"""
        self._durations.append(duration_s)

    def record_phase(self, phase: str, duration_s: float) -> None:
        """记某一阶段的耗时（秒）。阶段名必须是 PHASES 里的。"""
        if phase not in self._phase_totals:
            raise ValueError(f"未知阶段 {phase!r}；可选：{PHASES}")
        self._phase_totals[phase] += duration_s
        self._phase_counts[phase] += 1

    def record_nested(self, timer: str, duration_s: float) -> None:
        """记某个阶段的**内部细分**计时（秒）。

        与 `record_phase` 的区别：嵌套计时**不参与四段相加** ——
        它是某一段里的子步骤，量的是"这一段里有多少花在了 X 上"。
        当前只有 `encode`（嵌在 `ser` 里，见 NESTED_TIMERS 的说明）。

        维护约定：`encode_ms ≤ ser_ms` 必须恒成立，所以调用方要保证
        计时窗口真的被包在外层阶段里面。
        """
        if timer not in self._nested_totals:
            raise ValueError(f"未知嵌套计时 {timer!r}；可选：{NESTED_TIMERS}")
        self._nested_totals[timer] += duration_s
        self._nested_counts[timer] += 1

    def record_hits(self, count: int) -> None:
        """记本 tick 碰撞判定命中的对数。

        碰撞**只判定不生效**（不改血量、不删实体），所以 hits 是「这次循环真的在算」
        的证据 —— 没有它，一个写错的空转循环也会报出漂亮的耗时。
        """
        self._hits += count

    def record_in_frame(self, nbytes: int) -> None:
        """收到一帧（不区分类型：心跳和输入都算「还活着」的流量）。"""
        self._packets_in += 1
        self._bytes_in += nbytes

    def record_out_frame(self, nbytes: int) -> None:
        """发出一帧。广播时**每个客户端各算一次** —— 那才是真实下行带宽。"""
        self._packets_out += 1
        self._bytes_out += nbytes

    def record_snapshot(self, nbytes: int) -> None:
        """记一次**快照载荷**的大小（只算一次，不是 × 客户端数）。

        E9 的图 6-18 画的就是它随实体数的变化；和 bytes_out 是两个不同的量：
        快照大小是「一份」，bytes_out 是「一份 × 收件人数量」。
        """
        self._snapshot_bytes += nbytes
        self._snapshots += 1

    # --- 取走 ---------------------------------------------------------------

    def flush(self) -> dict:
        """取走本窗口的数据并清零。"""
        durations = self._durations
        count = len(durations)

        result = {
            "ticks": count,
            "avg_ms": round(sum(durations) / count * 1000, 3) if count else 0.0,
            "p50_ms": round(percentile(durations, 0.50) * 1000, 3),
            "p95_ms": round(percentile(durations, 0.95) * 1000, 3),
            "max_ms": round(max(durations) * 1000, 3) if count else 0.0,
            "hits": self._hits,
            "snapshot_bytes": (
                round(self._snapshot_bytes / self._snapshots) if self._snapshots else 0
            ),
            "packets_in": self._packets_in,
            "bytes_in": self._bytes_in,
            "packets_out": self._packets_out,
            "bytes_out": self._bytes_out,
        }

        for phase in PHASES:
            n = self._phase_counts[phase]
            result[f"{phase}_ms"] = (
                round(self._phase_totals[phase] / n * 1000, 3) if n else 0.0
            )

        # 嵌套计时：**不参与四段相加**，只说明某一段内部的构成（见 NESTED_TIMERS）
        for timer in NESTED_TIMERS:
            n = self._nested_counts[timer]
            result[f"{timer}_ms"] = (
                round(self._nested_totals[timer] / n * 1000, 3) if n else 0.0
            )

        self._durations = []
        self._phase_totals = {name: 0.0 for name in PHASES}
        self._phase_counts = {name: 0 for name in PHASES}
        self._nested_totals = {name: 0.0 for name in NESTED_TIMERS}
        self._nested_counts = {name: 0 for name in NESTED_TIMERS}
        self._hits = 0
        self._packets_in = 0
        self._bytes_in = 0
        self._packets_out = 0
        self._bytes_out = 0
        self._snapshot_bytes = 0
        self._snapshots = 0
        return result