"""每秒一个统计窗口：tick 耗时分布 + 收到的输入帧数。

D-022 说 7b 的目的是「**测输入处理负载**」。但机器人只能看到自己这边的收发 ——
服务端每 tick 到底花了多少毫秒，只有服务端自己知道。
（D-011 的「4 人 + 30 敌机 + 200 子弹 = 0.45 ms/tick」就是这么测出来的。）

这个类就是那个数据源，纯逻辑、无 IO，所以能直接单测 ——
和 protocol/snapshot.py 的分层思路一致：把可测的算法和不可测的 IO 分开。
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
    所以 flush() 返回的 inputs 就**等于每秒收到的输入帧数**。
    """

    def __init__(self) -> None:
        self._durations: list[float] = []
        self._inputs = 0

    def record_tick(self, duration_s: float) -> None:
        """记一次 tick 的耗时（秒）。包住 update + broadcast，不含 sleep。"""
        self._durations.append(duration_s)

    def record_input(self) -> None:
        """收到一条 C_INPUT。"""
        self._inputs += 1

    def flush(self) -> dict:
        """取走本窗口的数据并清零。"""
        durations = self._durations
        count = len(durations)
        result = {
            "ticks": count,
            "inputs": self._inputs,
            "avg_ms": round(sum(durations) / count * 1000, 3) if count else 0.0,
            "p50_ms": round(percentile(durations, 0.50) * 1000, 3),
            "p95_ms": round(percentile(durations, 0.95) * 1000, 3),
            "max_ms": round(max(durations) * 1000, 3) if count else 0.0,
        }
        self._durations = []
        self._inputs = 0
        return result