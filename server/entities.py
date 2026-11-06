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
    # ---------------- 以下全是**运行时字段**，步骤 11 的 GamePolicy 才用 ----------------
    #
    # ⚠️ 它们**不参与快照编码**：`snapshot_enemies()` 只取前 5 个字段
    #    （enemy_id / x / y / type / hp），所以快照字节不变。
    # ⚠️ `PlaceholderPolicy` **完全不读不写**这些字段，默认路径因此零影响。
    #
    # 为什么挂在实体上而不是放进 GamePolicy 的 dict：敌机被移除时要同步清理 dict，
    # 漏了就是内存泄漏；挂在实体上随实体一起消失，省心。
    phase: int = 0      # 0x02 的阶段：0=下落到 home_y，1=向右，2=向左
    fire_cd: int = 0    # 距离下次开火还有几 tick（0 = 可开火）
    home_y: int = 0     # 0x02 固守的高度（出生时随机定，之后不再变）
    target_x: int = 0   # 0x03 当前的横向目标（每 0.5 s 重算一次，不每 tick 算）


@dataclass(slots=True)
class Bullet:
    owner_id: int  # 0 = 敌方子弹
    x: int
    y: int
    type: int
    angle: int
    speed: int = BULLET_SPEED_PER_TICK


class PlaceholderPolicy:
    """**占位阶段的实体行为**：出生点固定、速度恒定、弹道直线。

    步骤 11 要加"敌机类型 / 波次 / 射击间隔 / BOSS"，如果把这些 if-else 直接塞进
    `World`，默认路径和游戏路径就会缠在一起，实验基线迟早被误伤。所以先在这里
    把"怎么出生、怎么飞"抽成策略：

        World(..., policy=PlaceholderPolicy())   # 默认，一切照旧
        World(..., policy=GamePolicy())          # 步骤 11 的 --game-mode

    ## ⚠️ 本次是**零改动重构**，硬约束如下

    1. **不增加、不减少、不重排任何 `rng` 调用**。
       每个实体出生恰好一次 `randrange` —— 多一次或少一次，随机数序列就整体错位，
       200 帧的 SHA 会立刻变，而代码看上去"完全正确"。这是本文件最危险的地方。
    2. **不改任何常量、不改变运算顺序**。
    3. 验收标准：黄金基线 SHA = `7860bdb912d92c1f22f29aafc895e1e5db9cb3aec078bd8f8b5780190ab45e4a`。

    SHA 变了就说明行为真的变了 —— **先回退定位，不许调参数让它对上**。

    ## 接口

    - `enemy_spawn(rng)` → `(x, y)`：出生位置
    - `enemy_move(enemy)` → `(dx, dy)`：每 tick 位移
    - `bullet_spawn(rng, players, want_player)` → `(owner_id, x, y, type, angle, speed)`
    - `bullet_move(bullet)` → `(dx, dy)`：每 tick 位移

    为什么让策略只返回**数值**、由 `World` 去构造实体：`enemy_id` 的分配与 uint16
    回绕是世界的状态，不该让策略碰；这样策略替换也不会影响 ID 序列。
    """

    # 出生与补弹**仍由 World 自己负责**（补到恒定数量 = E9 的自变量）。
    # GamePolicy 会把它设成 True，改成"按波次生成 + 敌机按冷却射击 + 玩家按射速开火"。
    # 这是 World.step 里唯一的分派点，默认路径只多读一个类属性，行为一字未改。
    manages_spawning = False

    def enemy_spawn(self, rng: random.Random) -> tuple[int, int]:
        """敌机从屏幕顶边进场，横向随机。**恰好一次 rng 调用。**"""
        return rng.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN), 0

    def enemy_move(self, enemy: Enemy) -> tuple[int, int]:
        """占位敌机统一向下匀速飞（协议里敌机没有 angle 字段，方向由 type 隐含）。"""
        return 0, ENEMY_SPEED_PER_TICK

    def bullet_spawn(
        self,
        rng: random.Random,
        players: list[tuple[int, int]],
        want_player: bool,
    ) -> tuple[int, int, int, int, int, int]:
        """一半玩家子弹（向上）、一半敌方子弹（向下），轮流出。

        **两条分支各自恰好一次 rng 调用** —— 分支不同但调用次数相同，
        所以轮换的奇偶不影响随机数序列的长度。
        """
        if want_player and players:
            # 只取前两个元素：服务端现在会传 (id, x, y)，占位路径只用 x
            player_id, x = players[rng.randrange(len(players))][:2]
            return player_id, x, PLAYER_BULLET_SPAWN_Y, BULLET_PLAYER_L1, ANGLE_UP, BULLET_SPEED_PER_TICK

        return (
            0,  # 敌方子弹的 owner_id 固定为 0（02 §6.2）
            rng.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN),
            0,
            BULLET_ENEMY_SPREAD,
            ANGLE_DOWN,
            BULLET_SPEED_PER_TICK,
        )

    def bullet_move(self, bullet: Bullet) -> tuple[int, int]:
        return angle_to_delta(bullet.angle, bullet.speed)

    def collision_radius(self, enemy: Enemy) -> int:
        """判定半径。占位路径就是模块常量（8），与 E9 基线一致。"""
        return COLLISION_RADIUS

    def score_for(self, enemy: Enemy) -> int | None:
        """击杀这个敌机该给多少分。**返回 None 表示"用世界的默认值"**。

        占位阶段一律返回 None → `World._award` 退回 `score_per_kill`（10 分），
        与步骤 11 之前完全一致。GamePolicy 会按敌机类型给 10/20/30。
        """
        return None


class World:
    """一张只有「匀速直线飞」的场地。

    每 tick 做三件事：**移动 → 出屏剔除 → 补足到目标数量**。

    为什么一定要「补足」：E9 的自变量是**同屏实体数**，如果实体只出不进，
    数量会随时间衰减，自变量就不稳定了。补足之后数量恒定，才是可比的实验条件。
    """

    def __init__(
        self,
        enemy_target: int = 0,
        bullet_target: int = 0,
        seed: int = 1,
        enable_kills: bool = False,
        fixed_entities: bool = False,
        policy: "PlaceholderPolicy | None" = None,
    ) -> None:
        # 上限来自协议本身：enemy_count 是 uint8、bullet_count 是 uint16
        if not 0 <= enemy_target <= 0xFF:
            raise ValueError(f"敌机数超出快照头的 uint8：{enemy_target} > 255")
        if not 0 <= bullet_target <= 0xFFFF:
            raise ValueError(f"子弹数超出快照头的 uint16：{bullet_target} > 65535")

        self.enemy_target = enemy_target
        self.bullet_target = bullet_target
        self.rng = random.Random(seed)

        # 击杀是否**真的生效**（扣血 / 死亡 / 计分）。
        # 默认关：E9/E1/E2 的全部基线都是在「只判定不生效」下测的，
        # 打开会改变 collision 阶段的实际工作量，必须显式开启才不污染复现。
        self.enable_kills = enable_kills
        # 击杀后是否**立刻补满**（实验期需要数量恒定，见 D-029）
        self.fixed_entities = fixed_entities
        # 关卡/波次：默认值刻意与快照编码器的默认值（level=1, wave=1）一致，
        # 所以默认路径传与不传，字节完全相同（黄金基线会证明）。
        # GamePolicy 会按实际波次更新 it。
        self.level = 1
        self.wave = 1
        self.scores: dict[int, int] = {}
        self.kills = 0
        self.score_per_kill = 10
        # 非固定模式下每 tick 最多补几个 —— 否则击杀刚清掉的敌机下一 tick 就满了，
        # 玩家看不到"打掉了"的反馈
        self.respawn_per_tick = 2

        # 实体行为策略（步骤 11 的扩展点）。默认 = 占位行为，与重构前逐字节相同。
        self.policy = policy if policy is not None else PlaceholderPolicy()

        self.enemies: list[Enemy] = []
        self.bullets: list[Bullet] = []
        self.next_enemy_id = 1
        self._player_bullet_turn = True

    # ------------------------------------------------------------ 每个 tick

    def step(
        self,
        players: list[tuple[int, int]],
        firing: set[int] | None = None,
    ) -> None:
        """players 是 [(player_id, x)]，玩家子弹从玩家的横向位置打出去。

        `firing` 是**本 tick 按住开火的玩家 id 集合**，只有 `GamePolicy` 会用它
        （服务端按自己的射速决定能不能真打出来，见 server/game_policy.py）。
        默认路径完全忽略它，所以 `step(players)` 的旧调用一字不用改。
        """
        self._move()
        if self.policy.manages_spawning:
            self.policy.tick_spawn(self, players, firing or set())
        else:
            self._respawn(players)

    def _move(self) -> None:
        # 敌机条目里**没有 angle 字段**（02 §6.2）—— 竖版飞机大战的敌机都是向下，
        # 方向由 type 隐含，所以占位敌机统一向下飞。
        # 位移交给策略算（步骤 11 的敌机类型轨迹不同），World 只负责累加与剔除。
        for enemy in self.enemies:
            dx, dy = self.policy.enemy_move(enemy)
            enemy.x += dx
            enemy.y += dy

        # 出屏即剔除（D-012）：不写进快照 = 客户端删掉它。
        # 顺带保证坐标永远落在 uint16 值域内，不会像 D-012 记录的那样 struct.error。
        self.enemies = [e for e in self.enemies if 0 <= e.y <= WORLD_HEIGHT]

        alive: list[Bullet] = []
        for bullet in self.bullets:
            dx, dy = self.policy.bullet_move(bullet)
            bullet.x += dx
            bullet.y += dy
            if 0 <= bullet.x <= WORLD_WIDTH and 0 <= bullet.y <= WORLD_HEIGHT:
                alive.append(bullet)
        self.bullets = alive

    def _respawn(self, players: list[tuple[int, int]]) -> None:
        # 击杀生效且**不要求**实体恒定时，按速率补生：一次杀光会让场上空掉，
        # 这正是"打掉了"的反馈；而实验期（fixed_entities）必须立刻补满，
        # 因为自变量是同屏实体数（D-029）。
        capped = self.enable_kills and not self.fixed_entities
        spawned = 0
        while len(self.enemies) < self.enemy_target:
            if capped and spawned >= self.respawn_per_tick:
                break
            self.enemies.append(self._spawn_enemy())
            spawned += 1
        # 子弹不设上限：它是"发射物"，不是关卡难度，补慢了反而让弹幕变稀
        while len(self.bullets) < self.bullet_target:
            self.bullets.append(self._spawn_bullet(players))

    def new_enemy_id(self) -> int:
        """分配一个敌机 ID（uint16，用完绕回 1）。

        抽出来是为了 GamePolicy：它自己构造不同 type 的敌机，但仍要用**同一个**
        ID 序列，否则客户端会看到重复 / 跳号的 id。纯提取，行为与之前一致。
        """
        enemy_id = self.next_enemy_id
        self.next_enemy_id += 1
        if self.next_enemy_id > 0xFFFF:  # enemy_id 是 uint16，绕回来
            self.next_enemy_id = 1
        return enemy_id

    def _spawn_enemy(self) -> Enemy:
        x, y = self.policy.enemy_spawn(self.rng)
        return Enemy(enemy_id=self.new_enemy_id(), x=x, y=y)

    def _spawn_bullet(self, players: list[tuple[int, int]]) -> Bullet:
        """一半玩家子弹（向上）、一半敌方子弹（向下），轮流出。

        轮换状态留在 World（它是世界的状态，不是行为策略的一部分）；
        具体的出生位置/类型/弹道由 policy 决定。
        """
        want_player = self._player_bullet_turn
        self._player_bullet_turn = not want_player

        owner_id, x, y, bullet_type, angle, speed = self.policy.bullet_spawn(
            self.rng, players, want_player
        )
        return Bullet(
            owner_id=owner_id,
            x=x,
            y=y,
            type=bullet_type,
            angle=angle,
            speed=speed,
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

    # ------------------------------------------------------------ 击杀结算

    def resolve_kills(self, players: list[tuple[int, int]] | None = None) -> tuple[int, int]:
        """让碰撞**真的生效**：扣血 → 死亡 → 计分 → 消耗子弹。返回 (命中数, 击杀数)。

        **为什么单独写一份，不复用 `detect_collisions`**：
        `detect_collisions` 是为 E9 基线量过常数因子的**只计数**循环，
        它跑出来的 `collision_ms` 是所有 E9/E1/E2 数据的一部分。往它里面塞伤害结算，
        等于偷偷改了历史数据的实验条件 —— 而这批数据的价值恰恰在于"同一条代码路径"。

        所以两条路径分开：**计数路径保持一字不动**，结算路径只在 `--enable-kills` 时走。
        代价是两份相似的循环（约 25 行重复），换来的是基线可比。

        与计数版的差异（也都会体现在 `collision_ms` 上，需在实验记录里注明）：
          - 命中后要改 `hp`、判死亡、写 `scores`、标记子弹消耗 —— 有写操作
          - 需要**反向下标删除**，所以先收集索引再统一删，避免边遍历边删

        计分口径：一次击杀 `score_per_kill` 分，归**子弹的主人**（`owner_id`）。
        敌方子弹 `owner_id == 0`，不会命中敌机（它朝下飞），即使命中也不给分。
        """
        # 半径交给策略：占位路径返回 8（与 E9 的计数路径一致），
        # 游戏模式返回更大的值，让"视觉上打中了"真的算打中。
        # ⚠️ `detect_collisions()`（E9 计数路径）**必须继续用模块常量 8**，
        # 那是历史数据的一部分，一改 E9 的 hits 就没法比了。
        hits = 0
        killed = 0
        dead_enemies: set[int] = set()
        used_bullets: set[int] = set()

        for bi, bullet in enumerate(self.bullets):
            if bullet.owner_id == 0:
                continue  # 敌方子弹不参与"打敌机"
            bx = bullet.x
            by = bullet.y
            for ei, enemy in enumerate(self.enemies):
                if ei in dead_enemies:
                    continue
                # 每只敌机各自取半径（0x02 / 0x03 比 0x01 大一圈）。
                # 只在**结算路径**这么做；`detect_collisions()`（E9 计数）
                # 继续用模块常量 8，否则 E9 的 hits 历史数据就没法比了。
                radius = self.policy.collision_radius(enemy)
                dx = bx - enemy.x
                if -radius <= dx <= radius:
                    dy = by - enemy.y
                    if -radius <= dy <= radius:
                        hits += 1
                        used_bullets.add(bi)
                        enemy.hp -= 1
                        if enemy.hp <= 0:
                            dead_enemies.add(ei)
                            killed += 1
                            self._award(
                                bullet.owner_id,
                                self.policy.score_for(enemy),
                            )
                        break  # 一颗子弹只命中一个目标

        if dead_enemies:
            self.enemies = [e for i, e in enumerate(self.enemies) if i not in dead_enemies]
        if used_bullets:
            self.bullets = [b for i, b in enumerate(self.bullets) if i not in used_bullets]
        self.kills += killed

        # ⚠️ 实验期必须**当场**补回目标数，不能等下一个 tick 的 `_respawn()`。
        # 2026-10-31 实测踩到：`--fixed-entities` 的守卫在 `step()` 之后检查，
        # 那时已经补满了，所以守卫通过；而击杀发生在它**之后**，
        # 于是快照里的敌机数变成 27~30 —— **守卫形同虚设，数据已经不符契约**。
        # 快照字节数是 E9 那套「逐字节等于公式」校验的基础，一旦浮动就全废。
        if self.fixed_entities and killed:
            self._respawn(players or [])
        return hits, killed

    def _award(self, player_id: int, points: int | None = None) -> None:
        """加分。**必须夹到 uint16 上限**：`score` 是协议里的 uint16 字段，
        越界会让 `struct.pack` 抛错 —— 那会像 E2 的 257 玩家一样直接搞死 tick 循环。

        `points` 为 None 时用 `score_per_kill`（占位路径）；GamePolicy 会按敌机类型
        传 10/20/30。默认路径传的一定是 None，所以行为与步骤 11 之前完全一致。
        """
        gained = self.score_per_kill if points is None else points
        self.scores[player_id] = min(0xFFFF, self.scores.get(player_id, 0) + gained)


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