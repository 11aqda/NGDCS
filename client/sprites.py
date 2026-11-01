"""客户端矢量绘制：把占位方块换成"看得出是飞机"的图形。

## 为什么不用 `legacy_game/` 里现成的 png

那三张素材是 2026 年 5 月旧原型留下的，实测：

| 文件 | 尺寸 | 内容 |
|---|---|---|
| `hero.png` | 40×50 | 白灰单色火箭 |
| `enemy0.png` | 20×15 | 白灰单色小飞机 |
| `bullet.png` | 15×15 | 白灰单色点 |

问题有两个：**① 单色**（白灰，要上色只能整体乘色，出不来层次）；
**② 太小**（放到 720×960 的画布上要放大到 48×60，白灰块会糊成一团）。

所以这里改成**代码绘制**：多边形是矢量的，放大不糊，还能随手加层次
（机身高光、机翼暗面、尾焰、描边）。素材文件保留着，将来要做"真素材版"随时能换。

## 约定

所有函数都接收**已经算好屏幕坐标**的 cx/cy 和像素尺寸 size，
不关心世界坐标与世界尺寸的换算 —— 那部分留在 `client/main.py` 里。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

DARK_EDGE = (12, 16, 26)


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """把颜色按比例变亮/变暗。factor > 1 变亮，< 1 变暗。"""
    return tuple(max(0, min(255, int(c * factor))) for c in color)  # type: ignore[return-value]


def draw_player_ship(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    color: tuple[int, int, int],
    *,
    is_self: bool,
    t: float,
) -> None:
    """画一架朝上的战机：机身 + 后掠翼 + 尾翼 + 座舱 + 尾焰。"""
    s = float(size)
    light = _shade(color, 1.35)
    dark = _shade(color, 0.62)
    edge = (240, 248, 255) if is_self else DARK_EDGE

    # ---- 尾焰（在机身之前画，才会被机身挡住根部）----
    flicker = 0.75 + 0.25 * math.sin(t * 22.0)
    flame_len = s * 0.55 * flicker
    flame = [
        (cx - s * 0.13, cy + s * 0.40),
        (cx + s * 0.13, cy + s * 0.40),
        (cx, cy + s * 0.40 + flame_len),
    ]
    pygame.draw.polygon(surface, (255, 196, 92), flame)
    inner = [
        (cx - s * 0.07, cy + s * 0.40),
        (cx + s * 0.07, cy + s * 0.40),
        (cx, cy + s * 0.40 + flame_len * 0.6),
    ]
    pygame.draw.polygon(surface, (255, 250, 210), inner)

    # ---- 机翼（左右各一，后掠）----
    for sign in (-1, 1):
        wing = [
            (cx + sign * s * 0.14, cy - s * 0.06),
            (cx + sign * s * 0.50, cy + s * 0.30),
            (cx + sign * s * 0.44, cy + s * 0.42),
            (cx + sign * s * 0.13, cy + s * 0.24),
        ]
        pygame.draw.polygon(surface, dark, wing)
        pygame.draw.polygon(surface, edge, wing, 1)

    # ---- 机身（细长六边形）----
    body = [
        (cx, cy - s * 0.52),
        (cx + s * 0.17, cy - s * 0.16),
        (cx + s * 0.13, cy + s * 0.40),
        (cx - s * 0.13, cy + s * 0.40),
        (cx - s * 0.17, cy - s * 0.16),
    ]
    pygame.draw.polygon(surface, color, body)
    pygame.draw.polygon(surface, edge, body, 2)

    # ---- 机身左侧高光：让它有点立体感 ----
    highlight = [
        (cx - s * 0.02, cy - s * 0.44),
        (cx + s * 0.06, cy - s * 0.14),
        (cx + s * 0.05, cy + s * 0.34),
        (cx - s * 0.03, cy + s * 0.34),
    ]
    pygame.draw.polygon(surface, light, highlight)

    # ---- 座舱：靠上的一小块椭圆形亮面 ----
    cockpit = pygame.Rect(0, 0, max(3, int(s * 0.16)), max(4, int(s * 0.24)))
    cockpit.center = (cx, int(cy - s * 0.20))
    pygame.draw.ellipse(surface, (200, 245, 255), cockpit)


def draw_enemy_ship(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    color: tuple[int, int, int],
) -> None:
    """画一架朝下的敌机：倒三角机体 + 两侧翼 + 描边。"""
    s = float(size)
    dark = _shade(color, 0.55)
    light = _shade(color, 1.25)
    edge = (60, 12, 12)

    # 两翼
    for sign in (-1, 1):
        wing = [
            (cx + sign * s * 0.10, cy - s * 0.18),
            (cx + sign * s * 0.50, cy - s * 0.42),
            (cx + sign * s * 0.44, cy - s * 0.20),
            (cx + sign * s * 0.12, cy + s * 0.10),
        ]
        pygame.draw.polygon(surface, dark, wing)
        pygame.draw.polygon(surface, edge, wing, 1)

    # 机体：尖朝下
    body = [
        (cx, cy + s * 0.52),
        (cx + s * 0.20, cy + s * 0.02),
        (cx + s * 0.16, cy - s * 0.44),
        (cx - s * 0.16, cy - s * 0.44),
        (cx - s * 0.20, cy + s * 0.02),
    ]
    pygame.draw.polygon(surface, color, body)
    pygame.draw.polygon(surface, edge, body, 2)

    # 中央高光
    stripe = [
        (cx - s * 0.05, cy - s * 0.34),
        (cx + s * 0.05, cy - s * 0.34),
        (cx + s * 0.03, cy + s * 0.20),
        (cx - s * 0.03, cy + s * 0.20),
    ]
    pygame.draw.polygon(surface, light, stripe)

    # 驾驶舱（红色小点，朝下那端）
    pygame.draw.circle(surface, (255, 210, 120), (cx, int(cy - s * 0.10)),
                       max(2, int(s * 0.09)))


def draw_player_bullet(
    surface: pygame.Surface, x: int, y: int, w: int, h: int
) -> None:
    """我方子弹：青色发光竖条（带柔光，不是硬方块）。"""
    glow = pygame.Rect(x - w * 2, y - h, w * 5, h * 2)
    layer = pygame.Surface((glow.width, glow.height), pygame.SRCALPHA)
    pygame.draw.rect(layer, (90, 210, 255, 70), (0, 0, glow.width, glow.height),
                     border_radius=glow.width // 2)
    surface.blit(layer, glow.topleft)

    pygame.draw.rect(surface, (150, 240, 255), (x - w // 2, y - h, w, h),
                     border_radius=max(1, w // 2))
    pygame.draw.rect(surface, (245, 255, 255),
                     (x - max(1, w // 3) // 2, y - h + 1,
                      max(1, w // 3), max(2, h - 3)))


def draw_enemy_bullet(surface: pygame.Surface, x: int, y: int, r: int) -> None:
    """敌方子弹：橙红圆点 + 深色环 + 上方拖尾，一眼看出朝我飞来。"""
    pygame.draw.circle(surface, (255, 118, 72), (x, y), r)
    pygame.draw.circle(surface, (120, 30, 10), (x, y), r, 1)
    pygame.draw.circle(surface, (255, 226, 160), (x, y - 1), max(1, r // 2))


@dataclass
class Explosion:
    """一次击杀的爆炸：扩散环 + 几片飞散的火星，纯客户端表现。"""

    x: float
    y: float
    age: float = 0.0
    life: float = 0.32
    sparks: list[tuple[float, float]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sparks is None:
            rng = random.Random(int(self.x) * 31 + int(self.y))
            self.sparks = [
                (rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(6)
            ]

    @property
    def done(self) -> bool:
        return self.age >= self.life

    def update(self, dt: float) -> None:
        self.age += dt

    def draw(self, surface: pygame.Surface, radius: int) -> None:
        k = min(1.0, self.age / self.life)
        alpha = int(255 * (1.0 - k))
        r = int(radius * (0.4 + 1.5 * k))
        size = r * 2 + 8
        layer = pygame.Surface((size, size), pygame.SRCALPHA)
        center = (size // 2, size // 2)
        pygame.draw.circle(layer, (255, 220, 140, alpha), center, r, max(2, int(3 * (1 - k))))
        for dx, dy in self.sparks or []:
            px = int(center[0] + dx * r * 1.1)
            py = int(center[1] + dy * r * 1.1)
            pygame.draw.circle(layer, (255, 160, 90, alpha), (px, py), max(1, int(3 * (1 - k))))
        surface.blit(layer, (int(self.x) - size // 2, int(self.y) - size // 2))