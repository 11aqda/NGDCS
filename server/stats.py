"""每秒一个统计窗口：tick 耗时、快照体积、收发流量。

D-022 说 7b 的目的是「**测输入处理负载**」；第 8 步要的是 E9 需要的那组数：
**tick 耗时 + 快照体积 + 带宽**。这些只有服务端自己知道
（D-011 的「4 人 + 30 敌机 + 200 子弹 = 0.45 ms/tick」就是这么测出来的）。

纯逻辑、无 IO，所以能直接单测 —— 和 `protocol/snapshot.py` 的分层思路一致：
把可测的算法和不可测的 IO 分开。落盘在 `server/metrics.py`。
"""

from __future__ import annotations


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
        self._packets_in = 0
        self._bytes_in = 0
        self._packets_out = 0
        self._bytes_out = 0
        self._snapshot_bytes = 0
        self._snapshots = 0

    # --- 记录 ---------------------------------------------------------------

    def record_tick(self, duration_s: float) -> None:
        """记一次 tick 的耗时（秒）。包住 update + broadcast，不含 sleep。"""
        self._durations.append(duration_s)

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
            "snapshot_bytes": (
                round(self._snapshot_bytes / self._snapshots) if self._snapshots else 0
            ),
            "packets_in": self._packets_in,
            "bytes_in": self._bytes_in,
            "packets_out": self._packets_out,
            "bytes_out": self._bytes_out,
        }
        self._durations = []
        self._packets_in = 0
        self._bytes_in = 0
        self._packets_out = 0
        self._bytes_out = 0
        self._snapshot_bytes = 0
        self._snapshots = 0
        return result