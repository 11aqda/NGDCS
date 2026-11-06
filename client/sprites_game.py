"""客户端按 `enemy.type` 区分机型的绘制（步骤 11）。

**只新增，不改 `draw_enemy_ship`** —— 那是占位阶段与默认路径在用的形状，
`tests/test_client_ui.py` 有测试依赖它。未知 type 一律回落到它。

颜色语义沿用既有规矩：**冷色 = 我方，暖色 = 敌方**。
三种敌机都用暖色系，靠**轮廓**区分 —— 玩家在弹幕里看一眼形状就知道该躲哪种。

## 2026-11-06 重画（用户反馈问题 4）

第一版把 0x02 画成了**菱形**，被指"不合理" —— 这是对的：
飞机大战里的敌机应该有**机头、机翼、发动机**，菱形读起来像块石头。
现在三种都是真正的飞船轮廓：

    0x01 俯冲   倒三角 + 直翼（沿用占位形状，玩家已习惯）
    0x02 横向   宽幅后掠翼 + 窄机身 + 双发动机（像蝠鲼）
    0x03 追踪   窄箭头 + 两片前伸的叉齿 + 核心（像捕食者的颚）

## 击中反馈

`flash=True` 时整机刷成白色 —— 由调用方在"这一帧 hp 掉了"时传进来。
**不需要协议支持**：客户端自己比较前后两帧的 hp 就能知道挨打了。
"""

import pygame

from protocol.messages import ENEMY_TRACK, ENEMY_WEAVE

from client.sprites import _shade, draw_enemy_ship

# 三种敌机的主体色（都是暖色，与"敌机=红橙"的语义一致）
WEAVE_COLOR = (255, 122, 60)    # 橙红
TRACK_COLOR = (224, 64, 192)    # 洋红：一眼看出"这个会追你"

_EDGE = (52, 10, 10)
_FLASH_COLOR = (255, 250, 245)


def draw_enemy_by_type(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    enemy_type: int,
    color: tuple[int, int, int],
    hp: int = 1,
    flash: bool = False,
) -> None:
    """按类型画敌机。未知类型回落到占位形状（前向兼容）。"""
    if flash:
        # 挨打那一瞬间整机发白：**最强的击中反馈**，不需要额外协议字段
        _draw_solid(surface, cx, cy, size, enemy_type, _FLASH_COLOR)
        return

    if enemy_type == ENEMY_WEAVE:
        _draw_weave(surface, cx, cy, size)
    elif enemy_type == ENEMY_TRACK:
        _draw_track(surface, cx, cy, size)
    else:
        draw_enemy_ship(surface, cx, cy, size, color)

    # hp ≥ 2 说明"还没被打"。用**四角括号**而不是圆圈 ——
    # 圆圈会把敌机裹成一个"蛋"，括号只做"目标锁定"的暗示（用户反馈：看着像椭球）
    if hp >= 2:
        _draw_brackets(surface, cx, cy, size)


def _draw_brackets(surface: pygame.Surface, cx: int, cy: int, size: int) -> None:
    s = size * 0.62
    arm = max(3, int(size * 0.16))
    color = (225, 228, 240)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = int(cx + sx * s)
            y = int(cy + sy * s)
            pygame.draw.line(surface, color, (x, y), (x - sx * arm, y), 1)
            pygame.draw.line(surface, color, (x, y), (x, y - sy * arm), 1)


def _draw_solid(
    surface: pygame.Surface, cx: int, cy: int, size: int,
    enemy_type: int, color: tuple[int, int, int],
) -> None:
    """挨打闪白用：只画实心轮廓，不画细节。"""
    s = float(size)
    if enemy_type == ENEMY_WEAVE:
        points = [
            (cx, cy - s * 0.30), (cx + s * 0.62, cy - s * 0.34),
            (cx + s * 0.34, cy + s * 0.46), (cx - s * 0.34, cy + s * 0.46),
            (cx - s * 0.62, cy - s * 0.34),
        ]
    elif enemy_type == ENEMY_TRACK:
        points = [
            (cx, cy + s * 0.58), (cx + s * 0.30, cy - s * 0.10),
            (cx + s * 0.50, cy - s * 0.46), (cx - s * 0.50, cy - s * 0.46),
            (cx - s * 0.30, cy - s * 0.10),
        ]
    else:
        points = [
            (cx, cy + s * 0.52), (cx + s * 0.46, cy - s * 0.34),
            (cx - s * 0.46, cy - s * 0.34),
        ]
    pygame.draw.polygon(surface, color, points)


def _draw_weave(surface: pygame.Surface, cx: int, cy: int, size: int) -> None:
    """0x02 横向移动：**宽幅后掠翼 + 窄机身 + 双发动机**（像蝠鲼）。

    比俯冲机宽、比它扁 —— 玩家一眼能看出"这家伙横着跑、皮厚"。
    """
    s = float(size)
    dark = _shade(WEAVE_COLOR, 0.65)
    light = _shade(WEAVE_COLOR, 1.30)

    # 后掠翼：两片向外上张的梯形（敌机向下来，所以机翼朝上）
    for sign in (-1, 1):
        wing = [
            (cx + sign * s * 0.12, cy - s * 0.16),
            (cx + sign * s * 0.62, cy - s * 0.38),
            (cx + sign * s * 0.56, cy + s * 0.10),
            (cx + sign * s * 0.14, cy + s * 0.30),
        ]
        pygame.draw.polygon(surface, dark, wing)
        pygame.draw.polygon(surface, _EDGE, wing, 1)

    # 窄机身：尖朝下的六边形
    body = [
        (cx, cy + s * 0.56),
        (cx + s * 0.18, cy + s * 0.14),
        (cx + s * 0.16, cy - s * 0.42),
        (cx - s * 0.16, cy - s * 0.42),
        (cx - s * 0.18, cy + s * 0.14),
    ]
    pygame.draw.polygon(surface, WEAVE_COLOR, body)
    pygame.draw.polygon(surface, _EDGE, body, 2)
    pygame.draw.polygon(surface, light, [
        (cx, cy + s * 0.40), (cx + s * 0.08, cy - s * 0.30),
        (cx - s * 0.08, cy - s * 0.30),
    ])

    # 双发动机（机尾，朝上）
    for sign in (-1, 1):
        pygame.draw.circle(surface, (255, 220, 170),
                           (cx + sign * int(s * 0.34), cy - int(s * 0.30)),
                           max(2, int(s * 0.09)))


def _draw_track(surface: pygame.Surface, cx: int, cy: int, size: int) -> None:
    """0x03 追踪玩家：**窄箭头 + 两片前伸叉齿 + 核心**（像捕食者的颚）。"""
    s = float(size)
    dark = _shade(TRACK_COLOR, 0.62)
    light = _shade(TRACK_COLOR, 1.35)

    # 两片前伸的叉齿（朝下，像要钳住玩家）
    for sign in (-1, 1):
        prong = [
            (cx + sign * s * 0.20, cy - s * 0.20),
            (cx + sign * s * 0.52, cy + s * 0.30),
            (cx + sign * s * 0.34, cy + s * 0.44),
            (cx + sign * s * 0.12, cy + s * 0.02),
        ]
        pygame.draw.polygon(surface, dark, prong)
        pygame.draw.polygon(surface, _EDGE, prong, 1)

    # 主箭头：尖朝下
    body = [
        (cx, cy + s * 0.60),
        (cx + s * 0.24, cy - s * 0.08),
        (cx + s * 0.20, cy - s * 0.46),
        (cx - s * 0.20, cy - s * 0.46),
        (cx - s * 0.24, cy - s * 0.08),
    ]
    pygame.draw.polygon(surface, TRACK_COLOR, body)
    pygame.draw.polygon(surface, _EDGE, body, 2)

    # 核心：会发光的一点，像盯着你的眼睛
    pygame.draw.circle(surface, (255, 240, 255), (cx, cy + int(s * 0.04)),
                       max(2, int(s * 0.13)))
    pygame.draw.circle(surface, light, (cx, cy + int(s * 0.04)),
                       max(1, int(s * 0.07)))