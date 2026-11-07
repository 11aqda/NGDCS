"""滚动星空背景（步骤 11，用户反馈"背景太单调"）。

纯客户端表现，**不碰协议**：星星只是几条会往下滚的短线段。

## 为什么用"线段"而不是"圆点"

竖版弹射游戏的背景要能表达**速度感**。圆点静止不动，看久了像贴片；
拉成短线段（越近的越长）就有了"我正在往上飞"的暗示，成本几乎为零。

## 三层视差

    远层  120 颗  细、暗、慢（20 px/s）   —— 背景星
    中层   50 颗  中、中、中（60 px/s）   —— 主体
    近层   18 颗  粗、亮、快（140 px/s）  —— 速度感来源

三层速度不同 = 视差，眼睛会觉得有纵深。**固定 seed**，每局星空分布一致（可复现）。
"""

from __future__ import annotations

import random

import pygame


class Starfield:
    """三层视差星空。`update(dt)` 推进，`draw(surface)` 绘制。"""

    def __init__(self, width: int, height: int, seed: int = 7) -> None:
        self.width = width
        self.height = height
        self._rng = random.Random(seed)

        # (数量, 速度 px/s, 长度 px, 亮度, 宽度)
        self._layers = [
            (120, 20.0, 2, (70, 78, 100), 1),
            (50, 60.0, 5, (120, 132, 165), 1),
            (18, 140.0, 12, (185, 198, 225), 2),
        ]
        self._stars: list[list[list[float]]] = []
        for count, speed, length, color, thickness in self._layers:
            layer = []
            for _ in range(count):
                layer.append([
                    float(self._rng.randrange(0, width)),
                    float(self._rng.randrange(0, height)),
                ])
            self._stars.append(layer)

    def update(self, dt: float) -> None:
        for index, (count, speed, length, color, thickness) in enumerate(self._layers):
            layer = self._stars[index]
            for star in layer:
                star[1] += speed * dt
                if star[1] > self.height:
                    # 回到顶部，x 重新随机 —— 否则会看到整齐的竖线
                    star[0] = float(self._rng.randrange(0, self.width))
                    star[1] = 0.0

    def draw(self, surface: pygame.Surface) -> None:
        for index, (count, speed, length, color, thickness) in enumerate(self._layers):
            for x, y in self._stars[index]:
                pygame.draw.line(
                    surface, color,
                    (int(x), int(y)), (int(x), int(y) + length), thickness,
                )


def draw_nebula(surface: pygame.Surface, width: int, height: int) -> None:
    """两团很淡的星云，压在星星**下面**，让深空不至于纯黑一片。

    ⚠️ 第一版用 4 层实心圆叠，每层边界都是硬边，画出来是**明显的同心圆环**
    （用户一眼看出"像靶子"）。现在改成：在 24x24 的小画布上画同心圆，
    再 smoothscale 放大 —— 插值把硬边磨成柔和渐变，成本几乎为零。
    """
    for cx, cy, radius, tint, peak_alpha in (
        (int(width * 0.28), int(height * 0.30), int(width * 0.30), (46, 36, 92), 70),
        (int(width * 0.74), int(height * 0.66), int(width * 0.26), (26, 52, 82), 55),
    ):
        if radius <= 0:
            continue
        small = pygame.Surface((24, 24), pygame.SRCALPHA)
        for step in range(12, 0, -1):
            alpha = int(peak_alpha * (step / 12.0) ** 2)
            pygame.draw.circle(small, (*tint, alpha), (12, 12), step)
        blob = pygame.transform.smoothscale(small, (radius * 2, radius * 2))
        surface.blit(blob, (cx - radius, cy - radius))
