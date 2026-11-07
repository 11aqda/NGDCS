"""步骤 11 的游戏内容策略：**敌机类型 + 波次 + 玩家射击**。

只在 `--game-mode` 下使用。默认（实验）路径走 `PlaceholderPolicy`，与这里完全隔离。

## 设计文档

数值与行为的依据见 `docs/13-游戏内容设计-敌机与波次.md`。本文件末尾的
`WAVES` / `ENEMY_SPECS` 是**唯一数值来源**，改数值改这里，并同步回设计文档。

## 四条实现边界（用户 2026-11-05 定，写在这里防止跑偏）

### 1. 玩家开火由**服务端**决定射速

客户端按住空格只是"**请求**开火"，服务端用 `player_cd` 自己限速
（默认 0.14 s 一发）。**绝不能**让客户端每帧直接生成子弹 —— 那等于把射速
交给客户端，改个客户端就能一秒百发。

子弹还有硬上限（`MAX_PLAYER_BULLETS` / `MAX_TOTAL_BULLETS`），
防止按住空格把 `bullet_count` 顶满。
（协议里 `bullet_count` 是 **uint16**，不是 255；上限是我们自己定的保守值。）

### 2. 波次数值可调，但必须集中、可复现

全部集中在 `WAVES` / `ENEMY_SPECS`，用 `--game-seed` 固定随机。
调完数值要同步回设计文档 §3，不允许"边跑边改、改完不记录"。

### 3. 0x03 每 0.5 s 重算目标，不每 tick 重算

每 tick 重算会让敌机在左右两个玩家之间**来回抽搐**。用平方距离比较
（不用开方，省算力也避免浮点）。

### 4. 0x02 固守高度后左右移动必须有 x 边界

`x` 钳在 `[SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN]`，撞边反向，
否则它会飞出屏幕边缘再也不回来（`_move` 只按 `y` 剔除，横向飞出不会被删）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from protocol.messages import (
    ANGLE_DOWN,
    ANGLE_UP,
    BULLET_ENEMY_FAN,
    BULLET_ENEMY_HOMING,
    BULLET_ENEMY_SPREAD,
    BULLET_PLAYER_L1,
    ENEMY_DIVE,
    ENEMY_TRACK,
    ENEMY_WEAVE,
)
from protocol.world import WORLD_HEIGHT, WORLD_WIDTH
from server.entities import Bullet, Enemy, PlaceholderPolicy

SPAWN_MARGIN = 40
PLAYER_BULLET_SPAWN_Y = WORLD_HEIGHT - 60

# ---------------------------------------------------------------- 数值表


@dataclass(frozen=True)
class EnemySpec:
    """一种敌机的全部数值。速度单位是 **px/s**（不是 px/tick，理由见 §5.1 设计文档）。"""

    hp: int
    fall_px_s: int        # 竖直下落速度
    drift_px_s: int       # 横向移动速度（0 = 不横移）
    fire_interval_s: float
    bullet_type: int
    bullet_px_s: int
    score: int


ENEMY_SPECS: dict[int, EnemySpec] = {
    ENEMY_DIVE: EnemySpec(
        hp=1, fall_px_s=120, drift_px_s=0, fire_interval_s=1.35,
        bullet_type=BULLET_ENEMY_SPREAD, bullet_px_s=200, score=10,
    ),
    ENEMY_WEAVE: EnemySpec(
        hp=2, fall_px_s=120, drift_px_s=120, fire_interval_s=1.85,
        bullet_type=BULLET_ENEMY_FAN, bullet_px_s=170, score=20,
    ),
    ENEMY_TRACK: EnemySpec(
        hp=2, fall_px_s=120, drift_px_s=60, fire_interval_s=2.2,
        bullet_type=BULLET_ENEMY_HOMING, bullet_px_s=240, score=30,
    ),
}

# 0x02 固守的高度区间（出生时随机取一个）
WEAVE_HOME_Y = (140, 300)

# 0x02 在固守高度上左右来回多久，之后俯冲离场
# ⚠️ 必须会离场：波次推进的条件是"场上没有敌机"，
# 永远留在场上的敌机会把这一波卡死（实测踩过：波次 2 卡了 4 分钟没结束）
WEAVE_HOLD_S = 6.0

# 0x03 重算目标的周期（tick）。20 Hz 下 10 tick = 0.5 s
RETARGET_TICKS = 10

# 同一波内相邻两个敌机的最小 x 间距 —— 否则会重现"一排飞下来"的观感
MIN_SPAWN_GAP_X = 60

# 玩家子弹速度（px/s）与射速上限
PLAYER_BULLET_PX_S = 600
PLAYER_FIRE_INTERVAL_S = 0.14

# 子弹从**机身外缘**打出，而不是从中心穿出来（用户反馈 2026-11-06：问题 2）
ENEMY_MUZZLE_OFFSET = 16   # 敌机中心 → 机头下方
PLAYER_MUZZLE_OFFSET = 18  # 玩家中心 → 机头上方

# 判定半径（像素）。比视觉尺寸略小一点是游戏手感惯例，但**不能像之前 8 px 那样小**：
# 敌机画出来 30 px 宽（视觉半径 ≈15），8 px 的判定会让"明明打中了"不算命中。
# 占位路径不受影响（PlaceholderPolicy.collision_radius 固定返回 8，E9 基线靠它）。
# 2026-11-07 再放大一档：用户仍觉得"打中不算"。
# 子弹在判定里是**一个点**，所以这里的值要额外含子弹本身的半径（约 3 px）。
COLLISION_RADIUS_BY_TYPE: dict[int, int] = {
    ENEMY_DIVE: 16,
    ENEMY_WEAVE: 19,
    ENEMY_TRACK: 17,
}

# 子弹硬上限：防止按住开火把 bullet_count 顶满
MAX_PLAYER_BULLETS = 40
MAX_TOTAL_BULLETS = 300


@dataclass(frozen=True)
class WaveSpec:
    """一波的配置。`composition` 是 ((敌机 type, 数量), ...)，按顺序生成。"""

    wave: int
    composition: tuple[tuple[int, int], ...]
    spawn_interval_s: float

    @property
    def total(self) -> int:
        return sum(count for _, count in self.composition)

    def expanded(self) -> list[int]:
        """展开成"这一波要依次生成的 type 列表"。"""
        sequence: list[int] = []
        for enemy_type, count in self.composition:
            sequence.extend([enemy_type] * count)
        return sequence


# ⚠️ 这是唯一的波次数值来源。改完要同步 docs/13-游戏内容设计-敌机与波次.md §3。
WAVES: tuple[WaveSpec, ...] = (
    # 2026-11-07：波次改成**按时间推进**（不再等清场），所以数量要按"刷多久"来配。
    # 目标仍是单局 ~80 秒（BOSS 之后再加）。
    WaveSpec(1, ((ENEMY_DIVE, 32),), 0.85),
    WaveSpec(2, ((ENEMY_DIVE, 20), (ENEMY_WEAVE, 14)), 0.65),
    WaveSpec(3, ((ENEMY_DIVE, 16), (ENEMY_WEAVE, 14), (ENEMY_TRACK, 10)), 0.55),
)

WAVE_PAUSE_S = 3.0


class GamePolicy(PlaceholderPolicy):
    """游戏模式：按波次生成、按类型运动与射击、玩家按射速开火。"""

    manages_spawning = True

    def __init__(
        self,
        tick_hz: int = 20,
        seed: int | None = None,
        player_fire_interval_s: float = PLAYER_FIRE_INTERVAL_S,
        max_player_bullets: int = MAX_PLAYER_BULLETS,
        max_total_bullets: int = MAX_TOTAL_BULLETS,
    ) -> None:
        self.tick_hz = max(1, int(tick_hz))
        self._rng = random.Random(seed)

        # 波次状态：**开局即进入第 1 波**（_queue 预填好，第一只立刻出）
        self.tick_index = 0
        self.wave_index = 0
        self._queue: list[int] = WAVES[0].expanded() if WAVES else []
        self._spawn_cd = 0.0
        self._pause_cd = 0.0
        self._last_spawn_x: int | None = None
        self.finished = False

        # 玩家射速
        self.fire_cd_ticks = max(1, round(player_fire_interval_s * self.tick_hz))
        self.max_player_bullets = max_player_bullets
        self.max_total_bullets = max_total_bullets
        self._player_cd: dict[int, int] = {}

        # 击落统计（调试与验收用）
        self.spawned_total = 0

    # ------------------------------------------------------------ 单位换算

    def _to_ticks(self, px_per_s: int) -> int:
        """**速度**换算：px/s → 每 tick 位移。至少 1，否则慢速实体在低 tick 率下卡住不动。"""
        return max(1, round(px_per_s / self.tick_hz))

    def _duration_ticks(self, seconds: float) -> int:
        """**时长**换算：秒 → tick 数。至少 1。

        ⚠️ 别和 `_to_ticks` 混用 —— 踩过：把 1.2 s 当成 1.2 px/s 去做除法，
        得到 0，`max(1, 0)` 变成"每 2 tick 开一枪"，6 秒打出 200 多发子弹。
        时长是**乘** tick_hz，速度是**除** tick_hz，两者方向相反。
        """
        return max(1, round(seconds * self.tick_hz))

    @staticmethod
    def _speed_jitter(enemy_id: int) -> int:
        """每个敌机的速度倍率（88%~112%），**由 id 确定性推导**。

        不用 rng：这样可以省一个运行时字段，也不会因为重放而漂移。
        """
        return 88 + (enemy_id * 37) % 25

    def _enemy_fall_step(self, enemy: Enemy) -> int:
        spec = ENEMY_SPECS.get(enemy.type)
        if spec is None:
            return self._to_ticks(90)
        base = self._to_ticks(spec.fall_px_s)
        return max(1, base * self._speed_jitter(enemy.enemy_id) // 100)

    # ------------------------------------------------------------ 策略接口

    def enemy_spawn(self, rng: random.Random) -> tuple[int, int]:
        """GamePolicy 自己构造敌机（见 `_spawn_enemy`），这个方法只作兜底。

        ⚠️ 出生 y **必须是 0**，不能用负值当"屏幕外待命区"：
        `World._move` 的剔除条件是 `0 <= y <= WORLD_HEIGHT`，负 y 的敌机会在
        下一 tick 被当成"已离场"直接删掉（踩过这个坑，场上永远是空的）。
        "一排飞下来"靠**生成间隔错开 + 速度抖动**解决，不靠负 y。
        """
        return rng.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN), 0

    def enemy_move(self, enemy: Enemy) -> tuple[int, int]:
        spec = ENEMY_SPECS.get(enemy.type)
        if spec is None:
            return 0, self._to_ticks(90)

        dy = self._enemy_fall_step(enemy)

        if enemy.type == ENEMY_DIVE:
            return 0, dy

        if enemy.type == ENEMY_WEAVE:
            if enemy.phase == 3:
                return 0, dy          # 横向来回结束，俯冲离场
            return 0, self._move_weave(enemy, dy)

        if enemy.type == ENEMY_TRACK:
            return self._move_track(enemy, spec), dy

        return 0, dy

    def _move_weave(self, enemy: Enemy, fall_step: int) -> int:
        """0x02：先下落到 home_y，然后在左右边界之间来回。

        ⚠️ 必须钳 x：`_move` 只按 y 剔除，横向飞出屏幕的敌机会永远留在场上
        （既打不到也看不到），把 `enemy_count` 撑住、波次永远推进不了。
        """
        if enemy.phase == 0:
            if enemy.y < enemy.home_y:
                return fall_step
            enemy.phase = 1                          # 到位，开始向右
            # target_x 对 0x02 不用作目标，这里借它当"还能横move多久"的倒计时
            enemy.target_x = self._duration_ticks(WEAVE_HOLD_S)

        # 倒计时归零 → 结束横move，转俯冲离场（否则这一波永远结束不了）
        enemy.target_x -= 1
        if enemy.target_x <= 0:
            enemy.phase = 3
            return 0

        drift = self._to_ticks(ENEMY_SPECS[ENEMY_WEAVE].drift_px_s)
        if enemy.phase == 2:
            drift = -drift

        next_x = enemy.x + drift
        low = SPAWN_MARGIN
        high = WORLD_WIDTH - SPAWN_MARGIN
        if next_x <= low:
            enemy.phase = 1      # 撞左边界，改向右
            drift = abs(drift)
        elif next_x >= high:
            enemy.phase = 2      # 撞右边界，改向左
            drift = -abs(drift)

        enemy.x += drift
        enemy.x = max(low, min(high, enemy.x))
        return 0  # 到位后不再下落

    def _move_track(self, enemy: Enemy, spec: EnemySpec) -> int:
        """0x03：朝 target_x 缓慢横移，靠近了就停（不来回抖）。"""
        drift = self._to_ticks(spec.drift_px_s)
        delta = enemy.target_x - enemy.x
        if abs(delta) <= drift:
            return 0
        return drift if delta > 0 else -drift

    def bullet_move(self, bullet: Bullet) -> tuple[int, int]:
        from server.entities import angle_to_delta

        return angle_to_delta(bullet.angle, bullet.speed)

    def collision_radius(self, enemy: Enemy) -> int:
        """按类型给判定半径。占位路径仍是 8（E9 的计数路径用的是那个值）。"""
        return COLLISION_RADIUS_BY_TYPE.get(enemy.type, 12)

    def score_for(self, enemy: Enemy) -> int | None:
        spec = ENEMY_SPECS.get(enemy.type)
        return None if spec is None else spec.score

    # ------------------------------------------------------------ 每 tick

    def tick_spawn(
        self,
        world,
        players: list[tuple[int, int]],
        firing: set[int],
    ) -> None:
        self.tick_index += 1
        self._advance_wave(world)
        self._retarget(world, players)
        self._enemy_fire(world)
        self._player_fire(world, players, firing)

    # ------------------------------------------------------------ 波次

    def _advance_wave(self, world) -> None:
        if self.finished:
            return

        dt = 1.0 / self.tick_hz

        # 波间停顿
        if self._pause_cd > 0:
            self._pause_cd -= dt
            if self._pause_cd <= 0:
                self._start_wave(world)
            return

        if self.wave_index >= len(WAVES):
            # 配置的波次全部打完（BOSS 在下一个 commit 接上）
            self.finished = True
            return

        if not self._queue:
            # 本波已全部刷出 → **不再等清场**，直接进波间倒计时。
            # 2026-11-07 用户要求"每波持续刷新"，残余敌机会带进下一波（压力累积，更紧张）。
            # 倒计时期间 `wave_state = 1`，客户端据此播"第 N 波"大字；开刷时置回 0。
            if self.wave_index + 1 >= len(WAVES):
                self.finished = True
                world.wave_state = 0
                return
            self.wave_index += 1
            self._pause_cd = WAVE_PAUSE_S
            world.wave = WAVES[self.wave_index].wave
            world.wave_state = 1
            return

        self._spawn_cd -= dt
        if self._spawn_cd > 0:
            return
        self._spawn_enemy(world, self._queue.pop(0), WAVES[self.wave_index])
        self._spawn_cd = WAVES[self.wave_index].spawn_interval_s

    def _start_wave(self, world) -> None:
        """开始 `wave_index` 指向的那一波（把 composition 展开成生成队列）。"""
        if self.wave_index >= len(WAVES):
            self.finished = True
            self._queue = []
            return
        spec = WAVES[self.wave_index]
        self._queue = spec.expanded()
        self._spawn_cd = 0.0            # 第一只立刻出
        self._last_spawn_x = None       # 新一波重新计算间距
        world.wave = spec.wave
        world.wave_state = 0            # 开刷 → 撤掉"下一波"提示

    def _spawn_enemy(self, world, enemy_type: int, spec: WaveSpec) -> None:
        spec_enemy = ENEMY_SPECS[enemy_type]

        x = self._pick_spawn_x()
        # y 固定 0（屏幕顶边）。错开靠"生成间隔 0.6~0.9 s + 速度抖动 ±12%"：
        # 同一波内相邻两只的纵向间距自然就有 40~90 px，不会再排成一条线。
        y = 0

        enemy = Enemy(
            enemy_id=world.new_enemy_id(),
            x=x,
            y=y,
            type=enemy_type,
            hp=spec_enemy.hp,
        )
        enemy.fire_cd = self._duration_ticks(spec_enemy.fire_interval_s * 0.5)
        if enemy_type == ENEMY_WEAVE:
            enemy.home_y = self._rng.randrange(*WEAVE_HOME_Y)
        elif enemy_type == ENEMY_TRACK:
            enemy.target_x = x

        world.enemies.append(enemy)
        self.spawned_total += 1
        self._last_spawn_x = x

    def _pick_spawn_x(self) -> int:
        """取一个与上一个出生点至少差 MIN_SPAWN_GAP_X 的 x。"""
        low = SPAWN_MARGIN
        high = WORLD_WIDTH - SPAWN_MARGIN
        if self._last_spawn_x is None:
            return self._rng.randrange(low, high)

        for _ in range(8):
            x = self._rng.randrange(low, high)
            if abs(x - self._last_spawn_x) >= MIN_SPAWN_GAP_X:
                return x
        # 试不出来就强制错开（保证不出现刚性横排）
        shifted = self._last_spawn_x + MIN_SPAWN_GAP_X
        return shifted if shifted < high else low

    # ------------------------------------------------------------ 射击

    def _retarget(self, world, players) -> None:
        """`0x03` 每 `RETARGET_TICKS`（0.5 s）重算一次目标，用**平方距离**。

        每 tick 重算会让它在两个玩家之间来回抽搐；平方距离省掉开方。

        ⚠️ `players` 的元素可能是 **(player_id, x)** 也可能带 y，即 (player_id, x, y)。
        这里**只按 x 比**（玩家 y 固定在屏幕底部），所以一律取 `[1]`。

        2026-11-07 事故：上一版写成 `_first_id, first_x = players[0]`，
        服务端改成传三元组后当场 `ValueError`，**tick 循环静默死掉**，
        玩家看到的现象是"打到第 3 波就卡住"。这个 bug 逃过了测试，
        因为测试只传两元组 —— 现在测试对两种元组形态都覆盖。
        """
        if not players or self.tick_index % RETARGET_TICKS:
            return

        first_x = players[0][1]
        best_x = first_x
        for enemy in world.enemies:
            if enemy.type != ENEMY_TRACK:
                continue
            best_dx = (enemy.x - first_x) ** 2
            best_x = first_x
            for player in players[1:]:
                other_x = player[1]
                dx2 = (enemy.x - other_x) ** 2
                if dx2 < best_dx:
                    best_dx = dx2
                    best_x = other_x
            enemy.target_x = best_x

    def _enemy_fire(self, world) -> None:
        for enemy in world.enemies:
            if enemy.fire_cd > 0:
                enemy.fire_cd -= 1
                continue
            spec = ENEMY_SPECS.get(enemy.type)
            if spec is None or enemy.y < 0:
                continue  # 还没进场，别在屏幕外开火
            if len(world.bullets) >= self.max_total_bullets:
                continue

            self._fire_bullets(world, enemy, spec)
            # 间隔加 ±25% 随机：不然所有敌机同一节奏，弹幕一看就是机械的
            enemy.fire_cd = self._duration_ticks(
                spec.fire_interval_s * self._rng.uniform(0.75, 1.25)
            )

    def _fire_bullets(self, world, enemy: Enemy, spec: EnemySpec) -> None:
        speed = self._to_ticks(spec.bullet_px_s)

        # 从**机头下方**射出，不从中心穿出来（视觉上像从机体里长出来一样）
        muzzle_y = enemy.y + ENEMY_MUZZLE_OFFSET

        def jitter_angle(base: int, spread: int = 8) -> int:
            """角度加一点随机，避免弹幕呆板地一条线（用户反馈：问题 5）。"""
            return (base + self._rng.choice((-spread, 0, spread))) & 0xFF

        if spec.bullet_type == BULLET_ENEMY_FAN:
            # 扇形 3 发：112 / 128 / 144（128 = 正下），每发再各自抖一点角度
            for base in (112, 128, 144):
                world.bullets.append(
                    Bullet(owner_id=0, x=enemy.x, y=muzzle_y,
                           type=BULLET_ENEMY_FAN, angle=jitter_angle(base),
                           speed=speed)
                )
            return

        if spec.bullet_type == BULLET_ENEMY_HOMING:
            angle = ANGLE_DOWN
            if enemy.target_x > enemy.x + 8:
                angle = 160   # 左下
            elif enemy.target_x < enemy.x - 8:
                angle = 96    # 右下
            world.bullets.append(
                Bullet(owner_id=0, x=enemy.x, y=muzzle_y,
                       type=BULLET_ENEMY_HOMING, angle=jitter_angle(angle),
                       speed=speed)
            )
            return

        world.bullets.append(
            Bullet(owner_id=0, x=enemy.x, y=muzzle_y,
                   type=BULLET_ENEMY_SPREAD, angle=jitter_angle(ANGLE_DOWN),
                   speed=speed)
        )

    def _player_fire(self, world, players: list[tuple[int, int]], firing: set[int]) -> None:
        """**服务端**按射速开火。客户端只发"请求"，这里才是决定能不能打的地方。"""
        # 清理已离场玩家的冷却，避免 dict 无限增长
        if len(self._player_cd) > len(players):
            alive = {pid for pid, _ in players}
            for pid in list(self._player_cd):
                if pid not in alive:
                    self._player_cd.pop(pid, None)

        player_bullets = sum(1 for b in world.bullets if b.owner_id != 0)
        speed = self._to_ticks(PLAYER_BULLET_PX_S)

        for player in players:
            player_id, x = player[0], player[1]
            # 服务端现在传 (id, x, y)；y 缺省时才退回屏幕底部的固定值
            player_y = player[2] if len(player) > 2 else PLAYER_BULLET_SPAWN_Y
            fire_y = player_y - PLAYER_MUZZLE_OFFSET

            cd = self._player_cd.get(player_id, 0)
            if cd > 0:
                self._player_cd[player_id] = cd - 1
                continue
            if player_id not in firing:
                continue
            if player_bullets >= self.max_player_bullets:
                continue
            if len(world.bullets) >= self.max_total_bullets:
                continue

            world.bullets.append(
                Bullet(owner_id=player_id, x=x, y=fire_y,
                       type=BULLET_PLAYER_L1, angle=ANGLE_UP, speed=speed)
            )
            player_bullets += 1
            self._player_cd[player_id] = self.fire_cd_ticks

    # ------------------------------------------------------------ 调试

    def status(self) -> dict:
        return {
            "wave": WAVES[self.wave_index].wave if self.wave_index < len(WAVES) else None,
            "spawned": self.spawned_total,
            "finished": self.finished,
            "tick": self.tick_index,
        }