"""占位实体：**没有 AI** 的敌机与子弹。

8a 的目的不是「把游戏做出来」，而是让 E9 的**自变量**（同屏敌机数 / 子弹数）存在。
按 `01-系统架构.md §3.4` 的三阶段解耦：

> 占位阶段不是白做：它的**实体结构、同步机制、渲染管线与最终版本一致**，只是实体类型少。
> 替换游戏内容时**通信层不用改**。

所以这里走的是**真实的协议条目、真实的序列化、真实的广播**，只是行为退化成一件事：
**匀速直线飞**。第 11 步把「匀速直线」换成「追踪玩家的 AI + 弹幕」时，
`protocol/snapshot.py`、`server/metrics.py`、`tools/plot.py` **一行都不用改**。

明确不做（都留给第 11 步）：AI、碰撞、伤害、掉落、波次、BOSS。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from protocol.messages import (
    ANGLE_DOWN,
    ANGLE_UP,
    BULLET_ENEMY_SPREAD,
    BULLET_PLAYER_L1,
    ENEMY_DIVE,
)
from protocol.snapshot import BulletSnapshot, EnemySnapshot
from protocol.world import WORLD_HEIGHT, WORLD_WIDTH

# 3 px/tick × 20 Hz = 60 px/s → 16 秒穿过 960 px 屏幕
ENEMY_SPEED_PER_TICK = 3

# 12 px/tick × 20 Hz = 240 px/s → 4 秒穿屏
BULLET_SPEED_PER_TICK = 12

# 生成位置左右留边，别贴着屏幕边缘刷出来
SPAWN_MARGIN = 40

# 玩家子弹从屏幕下方往上打
PLAYER_BULLET_SPAWN_Y = WORLD_HEIGHT - 60

# 碰撞判定半径（像素）：子弹约 4 px、敌机约 14 px，取半个身位做粗略 AABB。
# 占位阶段不追求判定精度，只追求**算法复杂度与真实版本一致**（01 §7.1 的朴素 O(子弹×敌机)）
COLLISION_RADIUS = 8

# 八方向整数表（0° = 正上，顺时针，02 §4.5）
_OCTANTS = (
    (0, -1),  # 0    正上
    (1, -1),  # 32   右上
    (1, 0),  # 64   正右
    (1, 1),  # 96   右下
    (0, 1),  # 128  正下
    (-1, 1),  # 160  左下
    (-1, 0),  # 192  正左
    (-1, -1),  # 224  左上
)


def angle_to_delta(angle: int, speed: int) -> tuple[int, int]:
    """把 uint8 角度换成整数位移 (dx, dy)。

    0~255 量化到 **8 个方向**（每档 32），**全整数、无三角函数**：
    一来 `02 §4.3` 禁用浮点，二来避免 `math.cos` 的末位差异影响复现。

    代价：斜向的位移是 1.41 倍（没做归一化）。占位阶段不需要；
    真实弹幕阶段要么把表细化到 256 档，要么用定点数做归一化。
    """
    dx, dy = _OCTANTS[(angle >> 5) & 0x07]
    return dx * speed, dy * speed


@dataclass(slots=True)
class Enemy:
    enemy_id: int
    x: int
    y: int
    type: int = ENEMY_DIVE
    hp: int = 1


@dataclass(slots=True)
class Bullet:
    owner_id: int  # 0 = 敌方子弹
    x: int
    y: int
    type: int
    angle: int
    speed: int = BULLET_SPEED_PER_TICK


class World:
    """一张只有「匀速直线飞」的场地。

    每 tick 做三件事：**移动 → 出屏剔除 → 补足到目标数量**。

    为什么一定要「补足」：E9 的自变量是**同屏实体数**，如果实体只出不进，
    数量会随时间衰减，自变量就不稳定了。补足之后数量恒定，才是可比的实验条件。
    """

    def __init__(
        self, enemy_target: int = 0, bullet_target: int = 0, seed: int = 1
    ) -> None:
        # 上限来自协议本身：enemy_count 是 uint8、bullet_count 是 uint16
        if not 0 <= enemy_target <= 0xFF:
            raise ValueError(f"敌机数超出快照头的 uint8：{enemy_target} > 255")
        if not 0 <= bullet_target <= 0xFFFF:
            raise ValueError(f"子弹数超出快照头的 uint16：{bullet_target} > 65535")

        self.enemy_target = enemy_target
        self.bullet_target = bullet_target
        self.rng = random.Random(seed)

        self.enemies: list[Enemy] = []
        self.bullets: list[Bullet] = []
        self.next_enemy_id = 1
        self._player_bullet_turn = True

    # ------------------------------------------------------------ 每个 tick

    def step(self, players: list[tuple[int, int]]) -> None:
        """players 是 [(player_id, x)]，玩家子弹从玩家的横向位置打出去。"""
        self._move()
        self._respawn(players)

    def _move(self) -> None:
        # 敌机条目里**没有 angle 字段**（02 §6.2）—— 竖版飞机大战的敌机都是向下，
        # 方向由 type 隐含，所以占位敌机统一向下飞。
        for enemy in self.enemies:
            enemy.y += ENEMY_SPEED_PER_TICK

        # 出屏即剔除（D-012）：不写进快照 = 客户端删掉它。
        # 顺带保证坐标永远落在 uint16 值域内，不会像 D-012 记录的那样 struct.error。
        self.enemies = [e for e in self.enemies if 0 <= e.y <= WORLD_HEIGHT]

        alive: list[Bullet] = []
        for bullet in self.bullets:
            dx, dy = angle_to_delta(bullet.angle, bullet.speed)
            bullet.x += dx
            bullet.y += dy
            if 0 <= bullet.x <= WORLD_WIDTH and 0 <= bullet.y <= WORLD_HEIGHT:
                alive.append(bullet)
        self.bullets = alive

    def _respawn(self, players: list[tuple[int, int]]) -> None:
        while len(self.enemies) < self.enemy_target:
            self.enemies.append(self._spawn_enemy())
        while len(self.bullets) < self.bullet_target:
            self.bullets.append(self._spawn_bullet(players))

    def _spawn_enemy(self) -> Enemy:
        enemy = Enemy(
            enemy_id=self.next_enemy_id,
            x=self.rng.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN),
            y=0,  # 从屏幕顶边进场
        )
        self.next_enemy_id += 1
        if self.next_enemy_id > 0xFFFF:  # enemy_id 是 uint16，绕回来
            self.next_enemy_id = 1
        return enemy

    def _spawn_bullet(self, players: list[tuple[int, int]]) -> Bullet:
        """一半玩家子弹（向上）、一半敌方子弹（向下），轮流出。"""
        want_player = self._player_bullet_turn
        self._player_bullet_turn = not want_player

        if want_player and players:
            player_id, x = players[self.rng.randrange(len(players))]
            return Bullet(
                owner_id=player_id,
                x=x,
                y=PLAYER_BULLET_SPAWN_Y,
                type=BULLET_PLAYER_L1,
                angle=ANGLE_UP,
            )

        return Bullet(
            owner_id=0,  # 敌方子弹的 owner_id 固定为 0（02 §6.2）
            x=self.rng.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN),
            y=0,
            type=BULLET_ENEMY_SPREAD,
            angle=ANGLE_DOWN,
        )

    # ------------------------------------------------------------ 导出快照

    def snapshot_enemies(self) -> list[EnemySnapshot]:
        return [
            EnemySnapshot(e.enemy_id, e.x, e.y, e.type, e.hp) for e in self.enemies
        ]

    def snapshot_bullets(self) -> list[BulletSnapshot]:
        return [
            BulletSnapshot(b.owner_id, b.x, b.y, b.type, b.angle) for b in self.bullets
        ]

    def counts(self) -> tuple[int, int]:
        return len(self.enemies), len(self.bullets)


def detect_collisions(bullets: list[Bullet], enemies: list[Enemy]) -> int:
    """朴素 O(子弹 × 敌机) 碰撞判定，**只数命中对数，不产生任何效果**，返回命中数。

    为什么用朴素双重循环：`01 §7.1` 那份基准（100 敌机 + 800 子弹 = 4.37 ms/tick）
    算的就是 **每 tick 8 万次**的朴素判定，我们要复现的是这个**算法复杂度**，
    而不是它的常数因子（那个原型是一次性的，代码没留下来）。
    空间划分 / 网格加速属于第 11 步之后的优化，届时正好可以做对比实验。

    > ⚠️ 那份基准的 CPU 列（原写 87.3%）是**量纲错误**，正确值 8.74%（见 D-027）。
    > 但 `ms/tick` 列是对的（4.37 vs E9 实测 5.738），所以"朴素判定确实贵"这个判断成立。

    为什么**只判定不生效**：
      1. E9 的自变量是「同屏实体数」。只算不改，数量就**由构造保证**恒定，
         不必依赖「删掉再补足」来维持 —— 自变量最干净
      2. 伤害结算 / 掉落 / 计分是第 11 步的游戏内容，现在做等于白做

    为什么还要返回 hits：它是「这个循环真的在算」的证据。
    没有它，一个写错方向、实际空转的循环同样会报出很漂亮的耗时曲线。

    实现上的两点讲究（都会明显影响常数因子，所以写清楚）：
      - 先把 `bullet.x / bullet.y` 取到局部变量，避免内层循环反复做属性查找
      - **先判 x 再判 y**：绝大多数配对在 x 上就不重叠，可以短路掉 y 的两次比较
    """
    radius = COLLISION_RADIUS
    hits = 0
    for bullet in bullets:
        bx = bullet.x
        by = bullet.y
        for enemy in enemies:
            dx = bx - enemy.x
            if -radius <= dx <= radius:
                dy = by - enemy.y
                if -radius <= dy <= radius:
                    hits += 1
    return hits