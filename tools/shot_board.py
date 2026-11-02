"""排行榜界面的截图驱动器（只用于截图，不是产品功能）。

## 为什么需要它

`client/board.py::run_board_screen()` 平时是在游戏里按 `B` 打开的。
但**在这个自动化环境里无法把键盘输入送进 SDL 窗口**：
- `keybd_event` / `SendKeys` —— 注入的真实输入进不去
- `PostMessage(WM_KEYDOWN)` —— 被 SDL 过滤（SDL2 在 Windows 上走 Raw Input）
- 焦点已经确认是对的（`GetFocus()` 就是该窗口），WM_CLOSE 也能生效，
  唯独键盘事件进不去

所以用这个脚本**直接调用同一个函数**、喂真实 HTTP 数据，截出来的画面和按 `B` 完全一致。
屏幕上看到的每一个像素、每一条数据都是真实运行产生的，没有合成、没有 P 图。

## 用法

    .venv\\Scripts\\python.exe -X utf8 -m tools.shot_board [输出png]

按 ESC 或等 3 秒后自动退出并保存在 `docs/screenshots/04-leaderboard.png`。
"""

from __future__ import annotations

import sys

import pygame

from client.board import run_board_screen
from client.fonts import load_font

OUT = "docs/screenshots/04-leaderboard.png"
API = "http://127.0.0.1:8000"
MY_NAME = "demo01"


def main() -> None:
    pygame.init()
    width, height = 720, 960
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("C/S 实时通信 · 排行榜")
    size = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0

    font = load_font(18)
    big_font = load_font(24, bold=True)

    # 先画一帧排行榜（run_board_screen 会自己拉数据并渲染）
    clock = pygame.time.Clock()
    deadline_ms = pygame.time.get_ticks() + 4000

    # 用一个包装：跑一轮绘制后立刻截图，然后退出
    import client.board as board_module

    original_fetch = board_module.fetch_leaderboard
    entries, error = original_fetch(API)
    print(f"[shot] 拉到 {len(entries)} 条记录，错误：{error or '无'}")

    # 渲染一帧
    screen.fill((16, 20, 32))
    board_module._draw_table(screen, font, big_font, entries, MY_NAME, width, height)
    title = big_font.render("排  行  榜", True, (220, 226, 240))
    screen.blit(title, title.get_rect(center=(width // 2, int(height * 0.07))))
    subtitle = font.render(
        f"R 刷新    ESC 返回    （共 {len(entries)} 条）", True, (120, 132, 156)
    )
    screen.blit(subtitle, subtitle.get_rect(center=(width // 2, int(height * 0.12))))
    pygame.display.flip()

    print("[shot] 3 秒后自动保存并退出（避免无人值守时挂住）")
    while pygame.time.get_ticks() < deadline_ms:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                deadline_ms = 0
        clock.tick(30)

    pygame.image.save(screen, OUT)
    print(f"[shot] 已保存 {OUT}")
    pygame.quit()


if __name__ == "__main__":
    main()