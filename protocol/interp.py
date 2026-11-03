"""插值误差（`err_px`）的核心算法 —— E4 / E5 图 6-8~6-10、6-12 的唯一数据来源。

## 一句话定义

> **`err_px` = 某一时刻"客户端实际显示的位置"与"服务端真实位置"之间的距离（像素）。**

注意这里**不是**"插值曲线偏离直线多少"，而是"玩家眼睛看到的和真实差了多远"。
两种定义在匀速直线运动下完全不同：

| 定义 | 匀速时 | 丢包时 |
|---|---|---|
| 曲线平滑度 | **恒为 0** | 仍可能为 0（直线插值的端点总是准的） |
| **显示误差（本实现）** | 一个 tick 的位移 | **随丢包线性变大** |

选后者，因为它是玩家真正感受到的东西，也才能让 6-8/6-9/6-12 走出有意义的曲线。
如果按"曲线平滑度"来量，机器人只要匀速走，误差永远是 0 —— 图会是一条贴地的线，
看起来像实验失败。

## 为什么误差天然不为零（滞后的来源）

客户端渲染的是 `lerp(上一帧, 当前帧, alpha)`，`alpha = (now - t_当前帧) / 帧间隔`
并钳在 `[0, 1]`。于是：

- 收到第 n 帧时，画面显示的是第 n-1 帧的位置（**落后一帧**）
- 第 n+1 帧到达那一刻，`alpha` 钳到 1，画面显示的是第 n 帧的位置
- 而真实位置已经是第 n+1 帧 → **误差 = 一帧的位移**（滞后是系统性的，不是 bug）

丢包时画面会停在第 n 帧不动，而真实继续走 → 误差按"丢了几个帧"累加。
这正是 E4 要量的东西。

## 与客户端渲染保持一致的约束

`alpha` 的算法必须和 `client/main.py` 里那段**完全一致**，否则量出来的误差
不代表玩家看到的东西。客户端那边将来应该直接调这里的函数，而不是各写一份。

## 不依赖 pygame

这个模块只做数学，不碰显示 —— 机器人（无 GUI）和客户端（有 GUI）都能用，
也才能在单测里构造"已知答案"的用例。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]

# 客户端渲染用的帧间隔基准。真实间隔应当用两帧的时间差算（下面就是这么做的），
# 这个常量只在"拿不到时间戳"时兜底（旧客户端的快照没有时间戳）。
DEFAULT_FRAME_S = 0.05


def clamp_alpha(now: float, t_prev: float, t_curr: float) -> float:
    """算插值系数，**与客户端渲染完全一致**：钳在 [0, 1]，不许外推。

    为什么钳住而不是外推：外推在丢包时会画到墙上（位置越飞越远），
    而"冻住"至少不会瞬移。这是 02 §6 里定的策略，这里只是忠实复现。
    """
    span = t_curr - t_prev
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (now - t_curr) / span))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_point(prev: Point, curr: Point, alpha: float) -> Point:
    return (lerp(prev[0], curr[0], alpha), lerp(prev[1], curr[1], alpha))


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class PlayerInterp:
    """跟踪**一个玩家**的历史位置，并在每帧到达时给出"刚才显示得有多偏"。

    用法（机器人侧）：

        track = PlayerInterp()
        for snapshot in stream:
            for player in snapshot.players:
                err = track.ingest(player.player_id, t, (player.x, player.y))
                if err is not None:
                    samples.append(err)

    `ingest` 返回 `None` 表示"历史帧不够，这一帧量不了"（前两帧必然如此）。
    """

    _prev: tuple[float, Point] | None = None
    _curr: tuple[float, Point] | None = None
    # 累计统计，便于直接上报
    samples: list[float] = field(default_factory=list)

    def displayed(self, now: float) -> Point | None:
        """**这一时刻客户端会显示的位置**。没有历史时返回 None。"""
        if self._curr is None:
            return None
        if self._prev is None:
            return self._curr[1]

        t_prev, p_prev = self._prev
        t_curr, p_curr = self._curr
        alpha = clamp_alpha(now, t_prev, t_curr)
        return lerp_point(p_prev, p_curr, alpha)

    def ingest(self, now: float, actual: Point) -> float | None:
        """喂入 `now` 时刻的**真实位置**，返回此前"显示位置"与它的距离。

        两个必须注意的点：

        1. **先算误差、再记历史** —— 顺序反了就会拿真值和它自己比，误差恒为 0。
        2. **至少要两帧历史才计时**。只有一帧时画面是"冻住"的（没有上一帧可插值），
           拿它和新帧比会得到一个**启动伪影**（玩家刚出现那一下的位移），
           那不是插值误差。E2 的 P99 就因为把"无数据"算成 0 踩过一次坑。
        """
        error: float | None = None
        if self._prev is not None and self._curr is not None:
            shown = self.displayed(now)
            if shown is not None:
                error = distance(shown, actual)
                self.samples.append(error)
        self._prev, self._curr = self._curr, (now, actual)
        return error

    # ------------------------------------------------------------ 统计

    def reset(self) -> None:
        self._prev = None
        self._curr = None
        self.samples.clear()

    @property
    def count(self) -> int:
        return len(self.samples)

    def summary(self) -> dict:
        """直接可以写进机器人汇总 JSON 的一组数。"""
        if not self.samples:
            return {"err_px_mean": None, "err_px_p95": None, "err_px_max": None,
                    "err_px_samples": 0}
        ordered = sorted(self.samples)
        index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "err_px_mean": round(sum(ordered) / len(ordered), 3),
            "err_px_p95": round(ordered[index], 3),
            "err_px_max": round(ordered[-1], 3),
            "err_px_samples": len(ordered),
        }