"""阶段 1 · 第 6 步：pygame 占位客户端 + 插值。

做三件事：
    1. 非阻塞网络：每帧 poll 一次，绝不卡住渲染（D-007）
    2. 插值：保存前后两帧快照，在 50 ms 内从旧位置线性过渡到新位置
    3. 绘制：720×960 竖版窗口，占位方块 + 网格 + HUD

本步不做：
    - 键盘输入（服务端还不处理 C_INPUT）
    - 房间、敌机、子弹、道具
    - 真正的快照延迟缓冲（现在是“上一帧 → 当前帧”的一帧插值）

用法：
    .venv\\Scripts\\python.exe -X utf8 -m client.main
    .venv\\Scripts\\python.exe -X utf8 -m client.main 127.0.0.1 9527
"""

import sys
import time

import pygame

from client.net import NetworkClient
from protocol.framing import ProtocolError
from protocol.messages import S_SNAPSHOT, S_WELCOME, WELCOME
from protocol.snapshot import unpack_snapshot

WORLD_WIDTH = 720
WORLD_HEIGHT = 960
FPS = 60
TICK_INTERVAL = 0.05  # 20 Hz 快照间隔

BG = (16, 20, 32)
GRID = (30, 36, 52)
TEXT = (220, 226, 240)
WHITE = (255, 255, 255)
RED = (255, 120, 120)

PALETTE = [
    (255, 99, 132),
    (54, 162, 235),
    (255, 206, 86),
    (75, 192, 192),
    (153, 102, 255),
    (255, 159, 64),
    (199, 199, 199),
    (83, 255, 150),
]


def lerp(a: float, b: float, t: float) -> float:
    """线性插值：t=0 返回 a，t=1 返回 b。"""
    return a + (b - a) * t


def draw_grid(screen: pygame.Surface, width: int, height: int) -> None:
    for x in range(0, width + 1, 80):
        pygame.draw.line(screen, GRID, (x, 0), (x, height))
    for y in range(0, height + 1, 80):
        pygame.draw.line(screen, GRID, (0, y), (width, y))


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9527

    pygame.init()
    info = pygame.display.Info()

    # 720×960 需要屏幕高度 ≥ 1000；放不下就缩到 600×800
    if info.current_h < 1000:
        width, height = 600, 800
    else:
        width, height = WORLD_WIDTH, WORLD_HEIGHT
    scale_x = width / WORLD_WIDTH
    scale_y = height / WORLD_HEIGHT

    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("C/S 实时通信 · 占位方块")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 18)
    big_font = pygame.font.SysFont("consolas", 24, bold=True)

    try:
        net = NetworkClient(host, port)
    except OSError as exc:
        print(f"[client] connect failed: {exc}")
        pygame.quit()
        return

    print(f"[client] connected to {host}:{port}; window {width}x{height}")

    my_id = 0
    tick = 0
    prev: dict = {}
    curr: dict = {}
    curr_time = 0.0
    running = True

    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False

            # 1) 非阻塞收包：这一帧能收多少收多少
            for frame in net.poll():
                if frame.msg_type == S_WELCOME and len(frame.payload) == WELCOME.size:
                    my_id, _color = WELCOME.unpack(frame.payload)
                elif frame.msg_type == S_SNAPSHOT:
                    try:
                        snapshot = unpack_snapshot(frame.payload)
                    except ProtocolError as exc:
                        print(f"[client] protocol error: {exc}")
                        running = False
                        break

                    prev = dict(curr)
                    curr = {p.player_id: p for p in snapshot.players}
                    curr_time = time.perf_counter()
                    tick = snapshot.tick

            # 2) 计算插值系数：新快照到达后的 50 ms 内 0 → 1
            now = time.perf_counter()
            alpha = min(1.0, (now - curr_time) / TICK_INTERVAL) if curr else 0.0

            # 3) 绘制
            screen.fill(BG)
            draw_grid(screen, width, height)

            for player_id, player in curr.items():
                old = prev.get(player_id, player)
                x = lerp(old.x, player.x, alpha) * scale_x
                y = lerp(old.y, player.y, alpha) * scale_y

                color = PALETTE[player.color % len(PALETTE)]
                size = max(18, int(26 * min(scale_x, scale_y)))
                rect = pygame.Rect(0, 0, size, size)
                rect.center = (int(x), int(y))

                pygame.draw.rect(screen, color, rect, border_radius=5)
                if player_id == my_id:
                    pygame.draw.rect(screen, WHITE, rect, 2, border_radius=5)

                label = font.render(f"P{player_id}", True, TEXT)
                screen.blit(label, (rect.centerx - label.get_width() // 2, rect.top - 20))

            # 4) HUD
            state = "connected" if net.connected else f"disconnected: {net.last_error}"
            hud = (
                f"tick={tick}  players={len(curr)}  fps={clock.get_fps():.0f}  "
                f"you=P{my_id}  {state}"
            )
            screen.blit(font.render(hud, True, TEXT), (12, 10))

            if not curr:
                waiting = big_font.render("waiting for snapshot...", True, TEXT)
                screen.blit(waiting, waiting.get_rect(center=(width // 2, height // 2)))

            if not net.connected:
                text = big_font.render("disconnected - ESC to quit", True, RED)
                screen.blit(text, text.get_rect(center=(width // 2, height // 2 + 40)))

            pygame.display.flip()
            clock.tick(FPS)
    finally:
        net.close()
        pygame.quit()


if __name__ == "__main__":
    main()
