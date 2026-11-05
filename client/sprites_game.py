"""客户端按 `enemy.type` 区分形状的补充绘制（步骤 11）。

**只新增，不改 `draw_enemy_ship`** —— 那是占位阶段与默认路径在用的形状，
`tests/test_client_ui.py` 有测试依赖它。未知 type 一律回落到它。

颜色语义沿用既有规矩：**冷色 = 我方，暖色 = 敌方**。
所以三种敌机都用暖色系，只靠**形状**区分 —— 玩家在弹幕里靠轮廓就能认出来。
"""

import pygame

from protocol.messages import ENEMY_DIVE, ENEMY_TRACK, ENEMY_WEAVE

from client.sprites import _shade, draw_enemy_ship

# 三种敌机的主体色（都是暖色，与"敌机=红橙"的语义一致）
WEAVE_COLOR = (255, 122, 60)    # 橙红
TRACK_COLOR = (224, 64, 192)    # 洋红：一眼看出"这个会追你"

_EDGE = (60, 12, 12)


def draw_enemy_by_type(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    enemy_type: int,
    color: tuple[int, int, int],
    hp: int = 1,
) -> None:
    """按类型画敌机。未知类型回落到占位形状（前向兼容）。"""
    if enemy_type == ENEMY_WEAVE:
        _draw_weave(surface, cx, cy, size)
    elif enemy_type == ENEMY_TRACK:
        _draw_track(surface, cx, cy, size)
    else:
        draw_enemy_ship(surface, cx, cy, size, color)

    # hp ≥ 2 说明"还没被打"：外圈加一道细白边，被打一下就没了
    if hp >= 2:
        pygame.draw.circle(surface, (255, 255, 255), (cx, cy), int(size * 0.62), 1)


def _draw_weave(surface: pygame.Surface, cx: int, cy: int, size: int) -> None:
    """0x02 横向移动：**菱形**，比俯冲机大一圈，暗示"它皮厚"。"""
    s = float(size) * 1.1
    body = [
        (cx, cy - s * 0.52),
        (cx + s * 0.52, cy),
        (cx, cy + s * 0.52),
        (cx - s * 0.52, cy),
    ]
    pygame.draw.polygon(surface, WEAVE_COLOR, body)
    pygame.draw.polygon(surface, _EDGE, body, 2)

    inner = [
        (cx, cy - s * 0.30),
        (cx + s * 0.30, cy),
        (cx, cy + s * 0.30),
        (cx - s * 0.30, cy),
    ]
    pygame.draw.polygon(surface, _shade(WEAVE_COLOR, 1.25), inner)


def _draw_track(surface: pygame.Surface, cx: int, cy: int, size: int) -> None:
    """0x03 追踪玩家：**倒三角 + 中央内核点**，像一只盯着你的眼睛。"""
    s = float(size)
    body = [
        (cx, cy + s * 0.55),
        (cx + s * 0.46, cy - s * 0.34),
        (cx - s * 0.46, cy - s * 0.34),
    ]
    pygame.draw.polygon(surface, TRACK_COLOR, body)
    pygame.draw.polygon(surface, _EDGE, body, 2)
    pygame.draw.circle(surface, (255, 240, 255), (cx, cy + s * 0.06), max(2, int(s * 0.16)))