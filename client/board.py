"""排行榜界面（步骤 10c）。

## 数据来自哪

`GET /api/leaderboard?limit=20` —— Django 先查 Redis ZSET（O(log N + k)），
未命中再回落 MySQL 聚合重建（见 `accounts/views.py`）。

**客户端不做任何计算**：名次、最高分、关卡、局数全部由服务端算好。
这是防作弊的一部分 —— 客户端连"自己多少分"都不该说了算。

## 为什么单独一个界面而不是 HUD 覆盖层

排行榜是**低频、请求-响应**的数据（D-005 的分层理由），
点开一次拉一次就够了；挂在游戏循环里逐帧刷新纯属浪费请求。
"""

from __future__ import annotations

import pygame
import requests

BG = (16, 20, 32)
TEXT = (220, 226, 240)
DIM = (120, 132, 156)
ACCENT = (90, 200, 255)
GOLD = (255, 214, 102)
ERROR = (255, 120, 120)
ROW_BG = (26, 32, 46)
ROW_SELF = (40, 62, 92)


def fetch_leaderboard(api_base: str, limit: int = 20) -> tuple[list[dict], str]:
    """返回 (entries, 错误信息)。**失败也要能返回空榜**，不能把界面卡死。"""
    try:
        response = requests.get(
            f"{api_base.rstrip('/')}/api/leaderboard",
            params={"limit": limit},
            timeout=5,
        )
        data = response.json()
    except requests.RequestException as exc:
        return [], f"连不上服务器：{type(exc).__name__}"
    except ValueError:
        return [], "服务器返回的不是 JSON"

    if response.status_code >= 400:
        return [], data.get("error", f"HTTP {response.status_code}")
    return data.get("entries", []), ""


def run_board_screen(
    screen: pygame.Surface,
    font,
    big_font,
    api_base: str,
    my_name: str = "",
) -> str:
    """画出排行榜，返回 `"back"` 或 `"quit"`。

    `my_name` 用来高亮自己那一行 —— 没有高亮的话，一屏名字里找不到自己。
    """
    entries, error = fetch_leaderboard(api_base)
    clock = pygame.time.Clock()
    width, height = screen.get_size()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "back"
                if event.key == pygame.K_r:
                    entries, error = fetch_leaderboard(api_base)  # 手动刷新

        screen.fill(BG)
        title = big_font.render("排  行  榜", True, TEXT)
        screen.blit(title, title.get_rect(center=(width // 2, int(height * 0.07))))

        subtitle = font.render(
            "R 刷新    ESC 返回"
            + (f"    （共 {len(entries)} 条）" if entries else ""),
            True,
            DIM,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(width // 2, int(height * 0.12))))

        if error:
            surface = font.render(error, True, ERROR)
            screen.blit(surface, surface.get_rect(center=(width // 2, height // 2)))
        elif not entries:
            surface = font.render("还没有人上榜 —— 先打一局吧", True, DIM)
            screen.blit(surface, surface.get_rect(center=(width // 2, height // 2)))
        else:
            _draw_table(screen, font, big_font, entries, my_name, width, height)

        pygame.display.flip()
        clock.tick(30)


def _draw_table(screen, font, big_font, entries, my_name, width, height) -> None:
    left = int(width * 0.08)
    right = int(width * 0.92)
    top = int(height * 0.18)
    row_h = max(26, int(height * 0.048))

    columns = [
        ("名次", 0.00, "left"),
        ("玩家", 0.14, "left"),
        ("最高分", 0.60, "right"),
        ("关卡", 0.76, "right"),
        ("局数", 0.92, "right"),
    ]
    span = right - left

    for label, fraction, align in columns:
        x = left + int(span * fraction)
        surface = font.render(label, True, DIM)
        if align == "right":
            x -= surface.get_width()
        screen.blit(surface, (x, top))

    pygame.draw.line(screen, (48, 58, 78), (left, top + row_h * 0.9),
                     (right, top + row_h * 0.9), 1)

    visible = entries[: int((height * 0.72 - top) / row_h)]
    for index, entry in enumerate(visible):
        y = top + row_h * (index + 1)
        is_me = entry.get("username") == my_name
        if is_me:
            pygame.draw.rect(
                screen, ROW_SELF,
                (left - 6, y - 4, right - left + 12, row_h - 2),
                border_radius=4,
            )
        color = ACCENT if is_me else TEXT
        if entry.get("rank") == 1:
            color = GOLD

        values = [
            (str(entry.get("rank", "")), 0.00, "left"),
            (entry.get("username", "?"), 0.14, "left"),
            (str(entry.get("best_score", 0)), 0.60, "right"),
            (str(entry.get("max_level", 1)), 0.76, "right"),
            (str(entry.get("games", 0)), 0.92, "right"),
        ]
        for text, fraction, align in values:
            x = left + int(span * fraction)
            surface = font.render(text, True, color)
            if align == "right":
                x -= surface.get_width()
            screen.blit(surface, (x, y))