"""阶段 1 · 第 8 步（8a）：pygame 客户端 + 实体渲染。

做六件事：
    1. 非阻塞网络：每帧 poll 一次，绝不卡住渲染（D-007）
    2. **键盘输入**：每 50 ms 发一次 C_INPUT，只发「按了什么键」，不发坐标（D-006）
    3. **心跳**：每 5 s 发一次 C_HEARTBEAT，HUD 上显示 RTT —— 让「心跳在工作」肉眼可见
    4. 插值：保存前后两帧快照，在 50 ms 内从旧位置线性过渡到新位置
    5. **实体渲染**：把快照里的敌机与子弹画出来（占位实体，见 server/entities.py）
    6. 绘制：720×960 竖版窗口，占位方块 + 网格 + HUD

    ⚠️ 注意方向键现在是**输入**，不再是移动本地方块 ——
    你按左，是告诉服务端“我要往左”，服务端算完坐标再广播回来。
    所以屏幕上看到的是「一次往返之后」的结果。

本步不做：
    - **子弹的实体插值**：子弹条目没有唯一 ID（只有 owner_id），客户端没法把
      这一帧的子弹和上一帧对应起来 —— 这是协议设计的结果，不是漏做
      （见 protocol/snapshot.py 的说明）
    - 客户端预测（按下去要等一个 RTT + 一帧才看到动，第三梯队 F12）
    - 房间、碰撞、伤害、道具
    - 断线自动重连

用法：
    .venv\\Scripts\\python.exe -X utf8 -m client.main
    .venv\\Scripts\\python.exe -X utf8 -m client.main 127.0.0.1 9527
"""

import os
import sys
import time

import pygame

from client.net import NetworkClient
from client.sprites import (
    Explosion,
    draw_enemy_bullet,
    draw_enemy_ship,
    draw_player_bullet,
    draw_player_ship,
)
from protocol.framing import ProtocolError
from protocol.messages import (
    C_HEARTBEAT,
    C_INPUT,
    KEY_LEFT,
    KEY_RIGHT,
    S_HEARTBEAT_ACK,
    S_SNAPSHOT,
    S_WELCOME,
    WELCOME,
    now_ms,
    pack_heartbeat,
    pack_keys,
    rtt_ms,
    unpack_heartbeat_ack,
)
from protocol.snapshot import unpack_snapshot
from protocol.world import WORLD_HEIGHT, WORLD_WIDTH

FPS = 60
TICK_INTERVAL = 0.05  # 20 Hz 快照间隔
INPUT_INTERVAL = 0.05  # 20 Hz，与 tick 同频（定频发送，天然冗余）
HEARTBEAT_INTERVAL = 5.0  # 02 §7

BG = (16, 20, 32)
GRID = (30, 36, 52)
TEXT = (220, 226, 240)
WHITE = (255, 255, 255)
RED = (255, 120, 120)

# ---------------------------------------------------------------- 颜色语义
# **整屏乱不乱，就靠这一条规则**：
#     冷色（青 / 蓝 / 绿） = 我方
#     暖色（红 / 橙）      = 敌方
#     金色                 = 分数（全屏唯一的中性强调色）
#
# 2026-11-01 之前是反着来的：我方子弹浅青、敌方子弹橙黄，而分数也是暖金色，
# 屏幕上到处是亮点，**分不清谁打谁**。定下这条规则后，颜色本身就带语义，
# 不需要看清形状也知道该躲什么。
ENEMY_BODY = (255, 88, 88)       # 敌机主体：正红
ENEMY_EDGE = (150, 40, 40)       # 敌机描边：让三角从背景里立起来
ENEMY_BULLET_COLOR = (255, 110, 70)   # 敌方子弹：橙红，朝我飞
PLAYER_BULLET_COLOR = (120, 235, 255)  # 我方子弹：亮青，向上
SCORE_COLOR = (255, 214, 102)    # 分数：金
SELF_RING = (255, 255, 255)      # 本机描边

# 8 个玩家颜色**全部取冷色/中性色** —— 玩家绝不能出现红橙，
# 否则和敌机撞色（协议里 color 是 3 bit，但"用哪 8 种"是显示层自由）
PALETTE = [
    (54, 162, 235),    # 蓝
    (75, 192, 192),    # 青绿
    (83, 255, 150),    # 绿
    (153, 102, 255),   # 紫
    (0, 200, 255),     # 亮青
    (100, 220, 255),   # 浅蓝
    (140, 255, 200),   # 薄荷
    (199, 199, 199),   # 中性灰
]


def lerp(a: float, b: float, t: float) -> float:
    """线性插值：t=0 返回 a，t=1 返回 b。"""
    return a + (b - a) * t


def draw_grid(screen: pygame.Surface, width: int, height: int) -> None:
    for x in range(0, width + 1, 80):
        pygame.draw.line(screen, GRID, (x, 0), (x, height))
    for y in range(0, height + 1, 80):
        pygame.draw.line(screen, GRID, (0, y), (width, y))


def read_keys() -> int:
    """把键盘状态翻译成协议里的输入位掩码（02 §4.5）。

    读的是「当前按住什么」而不是「刚刚按了哪个键」——
    定频发送要的就是状态，不是事件（丢一帧下一帧自动补上）。
    """
    pressed = pygame.key.get_pressed()
    keys = 0
    if pressed[pygame.K_LEFT] or pressed[pygame.K_a]:
        keys |= KEY_LEFT
    if pressed[pygame.K_RIGHT] or pressed[pygame.K_d]:
        keys |= KEY_RIGHT
    return keys


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9527

    # 让窗口**居中**：不设这个，Windows 会把 720×960 的窗口甩到屏幕右下角，
    # 高 DPI 缩放下右下两边都会被裁掉（实测玩家方块和 SCORE 都看不见了）
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")

    # 先声明 DPI 感知：Windows 在 125%/150% 缩放下，**不声明的话**
    # pygame 报告的屏幕尺寸与实际可用的像素不是一个坐标体系，
    # 按它算出来的窗口会超出屏幕（实测右侧 SCORE 被裁掉）。
    # 声明之后逻辑像素 == 物理像素，下面的比例计算才准。
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:  # noqa: BLE001 - 非 Windows 或旧系统上忽略
        pass

    pygame.init()
    info = pygame.display.Info()

    # 按屏幕的 85% 等比缩放，保证标题栏 + 窗口完整放得下。
    # ⚠️ pygame 的 current_w/h 是**逻辑像素**，150% 缩放下实际占屏会是 1.5 倍，
    # 所以不能只判"高度够不够 1000"，得按比例算。
    avail_w = int(info.current_w * 0.85)
    avail_h = int(info.current_h * 0.85)
    scale = min(1.0, avail_h / WORLD_HEIGHT, avail_w / WORLD_WIDTH)
    width = max(320, int(WORLD_WIDTH * scale))
    height = max(426, int(WORLD_HEIGHT * scale))
    scale_x = width / WORLD_WIDTH
    scale_y = height / WORLD_HEIGHT

    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("C/S 实时通信 · 输入 + 心跳 + 实体")
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
    print("[client] ←/→ 或 A/D 移动；ESC 退出")

    my_id = 0
    tick = 0
    prev: dict = {}
    curr: dict = {}
    curr_time = 0.0
    enemies: tuple = ()
    bullets: tuple = ()
    prev_enemies: tuple = ()   # 上一帧敌机，用来推断"哪一架被打掉了"
    curr_enemy_ids: set[int] = set()
    explosions: list[Explosion] = []   # 纯客户端的击杀特效
    keys = 0
    last_rtt = 0.0
    inputs_sent = 0
    heartbeats_sent = 0
    heartbeats_acked = 0
    running = True

    now = time.perf_counter()
    next_input_at = now
    next_heartbeat_at = now

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
                    # 实体直接取最近一帧，不参与插值（原因见模块开头）
                    prev_enemies = enemies
                    enemies = snapshot.enemies
                    curr_enemy_ids = {e.enemy_id for e in enemies}
                    bullets = snapshot.bullets
                    curr_time = time.perf_counter()
                    tick = snapshot.tick
                elif frame.msg_type == S_HEARTBEAT_ACK:
                    client_time, _server_time = unpack_heartbeat_ack(frame.payload)
                    # 回显的 client_time 是我们自己写的，所以 RTT 不需要两端对表
                    last_rtt = rtt_ms(client_time) / 1000.0
                    heartbeats_acked += 1

            # 2) 计算插值系数：新快照到达后的 50 ms 内 0 → 1
            now = time.perf_counter()
            alpha = min(1.0, (now - curr_time) / TICK_INTERVAL) if curr else 0.0

            # 3) 定频上报输入 + 定时心跳（都是「排进队列」，真正的发送在下一帧 poll）
            #
            # 用「deadline 累加」（next += 间隔）而不是「now + 间隔」：
            # 后者会把上报频率量化到帧率上（60 fps 下 50 ms 不是 16.7 ms 的整数倍，
            # 实测只有约 17 次/秒），前者平均频率准，而且每个渲染帧最多补发一帧，
            # 不会因为卡顿而突发。服务端的 tick_loop 用的是同一个模式。
            keys = read_keys()
            if net.connected and now >= next_input_at:
                net.send(C_INPUT, pack_keys(keys))
                inputs_sent += 1
                next_input_at += INPUT_INTERVAL

            if net.connected and now >= next_heartbeat_at:
                net.send(C_HEARTBEAT, pack_heartbeat(now_ms()))
                heartbeats_sent += 1
                next_heartbeat_at += HEARTBEAT_INTERVAL

            # 4) 绘制
            screen.fill(BG)
            draw_grid(screen, width, height)

            # 子弹：**两种子弹用不同形状**，不只靠颜色 ——
            # 我方子弹是发光竖条（一眼看出"往上打"），敌方子弹是圆点（一眼看出"朝我来"）。
            #
            # ⚠️ 子弹**不做插值**：子弹条目没有唯一 ID（只有 owner_id），
            # 客户端无法把这一帧的子弹和上一帧的对应起来（见 protocol/snapshot.py）。
            # 这是协议设计的结果，不是漏做 —— 要平滑只能靠外推或延迟快照缓冲。
            bar_w = max(2, int(3 * min(scale_x, scale_y)))
            bar_h = max(7, int(12 * min(scale_x, scale_y)))
            dot_r = max(2, int(3 * min(scale_x, scale_y)))
            for bullet in bullets:
                bx = int(bullet.x * scale_x)
                by = int(bullet.y * scale_y)
                if bullet.owner_id:
                    draw_player_bullet(screen, bx, by, bar_w, bar_h)
                else:
                    draw_enemy_bullet(screen, bx, by, dot_r)

            # 敌机：矢量的"倒飞小飞机"（机体 + 两翼 + 描边 + 座舱点）。
            # 占位阶段敌机统一向下飞（协议里没有 angle 字段，方向由 type 隐含），
            # 所以形状固定朝下是对的；按 type 分形状/配色属于步骤 11 的游戏内容。
            enemy_size = max(16, int(26 * min(scale_x, scale_y)))
            for enemy in enemies:
                draw_enemy_ship(
                    screen,
                    int(enemy.x * scale_x),
                    int(enemy.y * scale_y),
                    enemy_size,
                    ENEMY_BODY,
                )

            # 击杀爆炸：**纯客户端表现**。靠"上一帧有、这一帧没了、且消失位置在屏幕中部"
            # 推断是被打掉了 —— 飞出屏幕底部的不算（那是正常移出画面）。
            for enemy in prev_enemies:
                if enemy.enemy_id in curr_enemy_ids:
                    continue
                if enemy.y < WORLD_HEIGHT - 60:  # 不是在底边正常出屏
                    explosions.append(
                        Explosion(enemy.x * scale_x, enemy.y * scale_y)
                    )
            for boom in explosions:
                boom.update(1.0 / FPS)
                boom.draw(screen, max(8, int(18 * min(scale_x, scale_y))))
            explosions[:] = [b for b in explosions if not b.done]

            for player_id, player in curr.items():
                old = prev.get(player_id, player)
                x = lerp(old.x, player.x, alpha) * scale_x
                y = lerp(old.y, player.y, alpha) * scale_y

                color = PALETTE[player.color % len(PALETTE)]
                size = max(26, int(40 * min(scale_x, scale_y)))
                draw_player_ship(
                    screen, int(x), int(y), size, color,
                    is_self=(player_id == my_id), t=pygame.time.get_ticks() / 1000.0,
                )

                label = font.render(f"P{player_id}", True, TEXT)
                # 标签挂在机头上方（玩家绘制不再有 rect，直接按中心点算）
                screen.blit(
                    label,
                    (int(x) - label.get_width() // 2, int(y) - size // 2 - 24),
                )

            # 5) HUD：keys 显示你现在按住了什么，rtt 显示心跳往返耗时
            # 分数由**服务端**算好放在快照里（击杀生效后，见 D-030），客户端只读不算 ——
            # 客户端没有任何分数上报接口，这是防作弊的设计约束
            my_score = curr[my_id].score if my_id in curr else 0
            hud_line1 = (
                f"tick={tick}  players={len(curr)}  you=P{my_id}  "
                f"score={my_score}  "
                f"e/b={len(enemies)}/{len(bullets)}  fps={clock.get_fps():.0f}"
            )
            hud_line2 = (
                f"keys={keys:02b}  rtt={last_rtt * 1000:.2f}ms  "
                f"in={inputs_sent}  hb={heartbeats_acked}/{heartbeats_sent}"
            )
            screen.blit(font.render(hud_line1, True, TEXT), (12, 10))
            screen.blit(font.render(hud_line2, True, TEXT), (12, 34))

            # 分数单独放大显示：这是唯一"玩起来有反馈"的数字
            if my_id in curr:
                score_text = big_font.render(f"SCORE {curr[my_id].score}", True, SCORE_COLOR)
                screen.blit(score_text, (width - score_text.get_width() - 12, 8))

            state = "connected" if net.connected else f"disconnected: {net.last_error}"
            screen.blit(font.render(state, True, TEXT), (12, 58))

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