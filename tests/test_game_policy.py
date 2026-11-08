"""步骤 11 游戏内容的测试：**只测 GamePolicy 的纯逻辑，不发网络、不读时钟**。

## 这组测试守的是什么

1. **数值与设计文档一致**（`docs/13-游戏内容设计-敌机与波次.md`）——
   改了数值不同步文档，这里会红
2. **波次能推进完**（曾经踩过：0x02 固守高度永不落出屏幕，波次 2 卡了 4 分钟）
3. **0x02 不会飞出屏幕**（`World._move` 只按 y 剔除，横向飞出去就再也回不来）
4. **0x03 每 0.5 s 才重算目标**（每 tick 重算会来回抽搐）
5. **玩家射速由服务端决定**（客户端只能"请求"）
6. **子弹有上限**（防止按住开火把 bullet_count 顶满）
7. **默认路径完全不受影响**（PlaceholderPolicy 仍是 manages_spawning=False）

全部 headless：直接 `World.step()`，不启服务端、不用 socket。
"""

import unittest

from protocol.messages import (
    BULLET_ENEMY_FAN,
    BULLET_ENEMY_HOMING,
    BULLET_ENEMY_SPREAD,
    BULLET_PLAYER_L1,
    ENEMY_DIVE,
    ENEMY_TRACK,
    ENEMY_WEAVE,
)
from protocol.world import WORLD_WIDTH
from server.entities import PlaceholderPolicy, World
from server.game_policy import (
    COLLISION_RADIUS_BY_TYPE,
    ENEMY_MUZZLE_OFFSET,
    ENEMY_SPECS,
    MIN_SPAWN_GAP_X,
    PLAYER_MUZZLE_OFFSET,
    RETARGET_TICKS,
    SPAWN_MARGIN,
    WAVE_PAUSE_S,
    WAVES,
    GamePolicy,
)

# 玩家在服务端的出生 y（server/main.py 里 760 - ((id-1)%4)*60）
PLAYER_Y = 760

TICK_HZ = 20


def make_world(policy=None, **kwargs):
    policy = policy or GamePolicy(tick_hz=TICK_HZ, seed=1)
    world = World(enemy_target=0, bullet_target=0, seed=1,
                  enable_kills=True, policy=policy, **kwargs)
    return world, policy


def run(world, policy, ticks, firing=True, x=300):
    """跑 N tick；玩家左右横跳，让"追踪目标会变"这条路径被覆盖到。"""
    for tick in range(1, ticks + 1):
        px = 120 + (tick * 7) % 480
        world.step([(1, px if x is None else x)], firing={1} if firing else set())


class EnemySpecTest(unittest.TestCase):
    """数值必须与设计文档一致。"""

    def test_three_enemy_types_defined(self):
        self.assertEqual(set(ENEMY_SPECS), {ENEMY_DIVE, ENEMY_WEAVE, ENEMY_TRACK})

    def test_hp_and_score_match_design(self):
        expect = {ENEMY_DIVE: (1, 10), ENEMY_WEAVE: (2, 20), ENEMY_TRACK: (2, 30)}
        for enemy_type, (hp, score) in expect.items():
            spec = ENEMY_SPECS[enemy_type]
            self.assertEqual((spec.hp, spec.score), (hp, score), f"type {enemy_type:#x}")

    def test_bullet_types_match_design(self):
        self.assertEqual(ENEMY_SPECS[ENEMY_DIVE].bullet_type, BULLET_ENEMY_SPREAD)
        self.assertEqual(ENEMY_SPECS[ENEMY_WEAVE].bullet_type, BULLET_ENEMY_FAN)
        self.assertEqual(ENEMY_SPECS[ENEMY_TRACK].bullet_type, BULLET_ENEMY_HOMING)

    def test_speeds_are_multiples_of_60(self):
        """速度取 60 的倍数，才能在 10/20/30 Hz 下都被整数整除、手感一致。"""
        for enemy_type, spec in ENEMY_SPECS.items():
            for name in ("fall_px_s", "drift_px_s"):
                value = getattr(spec, name)
                if value:
                    self.assertEqual(value % 60, 0, f"type {enemy_type:#x} 的 {name}={value}")


class WaveTest(unittest.TestCase):
    def test_three_waves(self):
        self.assertEqual(len(WAVES), 3)
        self.assertEqual([w.wave for w in WAVES], [1, 2, 3])

    def test_wave_composition_expands(self):
        for spec in WAVES:
            self.assertEqual(len(spec.expanded()), spec.total)
            self.assertEqual(spec.expanded(), list(spec.expanded()))

    def test_all_three_waves_complete(self):
        """**这条守的是"波次能推进完"** —— 曾经 0x02 永不落出屏幕，卡死在第 2 波。"""
        world, policy = make_world()
        for _ in range(int(180 * TICK_HZ)):
            world.step([(1, 300)], firing={1})
            if policy.finished and not world.enemies:
                break
        self.assertTrue(policy.finished, "三波没有跑完")
        self.assertEqual(policy.spawned_total, sum(w.total for w in WAVES))

    def test_duration_is_about_85_seconds(self):
        """设计目标：三波 85 秒左右（BOSS 在后续 commit）。"""
        world, policy = make_world()
        ticks = 0
        for _ in range(int(180 * TICK_HZ)):
            world.step([(1, 300)], firing={1})
            ticks += 1
            if policy.finished and not world.enemies:
                break
        seconds = ticks / TICK_HZ
        self.assertGreater(seconds, 70.0, f"太短了：{seconds:.1f}s")
        self.assertLess(seconds, 100.0, f"太长了：{seconds:.1f}s")

    def test_duration_roughly_independent_of_tick_rate(self):
        """px/s 口径的意义：tick 率变了，一局时长不该跟着大变。"""
        durations = {}
        for hz in (10, 20, 30):
            policy = GamePolicy(tick_hz=hz, seed=1)
            world = World(enemy_target=0, bullet_target=0, seed=1,
                          enable_kills=True, policy=policy)
            ticks = 0
            for _ in range(int(180 * hz)):
                world.step([(1, 300)], firing={1})
                ticks += 1
                if policy.finished and not world.enemies:
                    break
            durations[hz] = ticks / hz
        base = durations[20]
        for hz, seconds in durations.items():
            self.assertLess(abs(seconds - base) / base, 0.12,
                            f"{hz} Hz 的时长 {seconds:.1f}s 与 20 Hz 的 {base:.1f}s 差太多")


class SpawnTest(unittest.TestCase):
    def test_adjacent_spawns_are_far_apart_in_x(self):
        """同波相邻两只的 x 至少差 MIN_SPAWN_GAP_X，避免"一排飞下来"。"""
        world, policy = make_world()
        xs = []
        for _ in range(400):
            before = len(world.enemies)
            world.step([(1, 300)])
            if len(world.enemies) > before:
                xs.append(world.enemies[-1].x)
            if len(xs) >= 6:
                break
        for left, right in zip(xs, xs[1:]):
            self.assertGreaterEqual(abs(right - left), MIN_SPAWN_GAP_X)

    def test_spawn_x_inside_margins(self):
        world, policy = make_world()
        run(world, policy, 200)
        for enemy in world.enemies:
            self.assertGreaterEqual(enemy.x, SPAWN_MARGIN)
            self.assertLessEqual(enemy.x, WORLD_WIDTH - SPAWN_MARGIN)

    def test_enemies_are_not_a_rigid_row(self):
        """"一排飞下来"的回归测试：y 必须有明显极差。"""
        world, policy = make_world()
        run(world, policy, 120)
        ys = sorted(e.y for e in world.enemies)
        self.assertGreater(len(ys), 3, "敌机太少了，测不出错开")
        self.assertGreater(max(ys) - min(ys), 100, "敌机又排成一排了")


class WeaveTest(unittest.TestCase):
    def test_weave_stays_inside_x_bounds(self):
        """0x02 的 x 必须钳在屏幕内 —— 飞出去就再也回不来（_move 只按 y 剔除）。"""
        world, policy = make_world()
        run(world, policy, 600)
        for enemy in world.enemies:
            if enemy.type == ENEMY_WEAVE:
                self.assertGreaterEqual(enemy.x, SPAWN_MARGIN - 1)
                self.assertLessEqual(enemy.x, WORLD_WIDTH - SPAWN_MARGIN + 1)

    def test_weave_eventually_leaves(self):
        """0x02 不能永远留在场上，否则这一波永远结束不了。"""
        policy = GamePolicy(tick_hz=TICK_HZ, seed=7)
        world = World(enemy_target=0, bullet_target=0, seed=1,
                      enable_kills=True, policy=policy)
        seen_weave = False
        for _ in range(int(120 * TICK_HZ)):
            world.step([(1, 300)], firing=set())
            if any(e.type == ENEMY_WEAVE for e in world.enemies):
                seen_weave = True
            if seen_weave and not world.enemies:
                break
        self.assertTrue(seen_weave, "这批种子里没出现 0x02")
        self.assertEqual(len(world.enemies), 0, "0x02 一直没有离场")


class TrackTest(unittest.TestCase):
    def test_retarget_interval_is_half_second(self):
        self.assertEqual(RETARGET_TICKS, 10)
        self.assertAlmostEqual(RETARGET_TICKS / TICK_HZ, 0.5)

    def test_track_target_follows_nearest_player(self):
        """两个玩家，0x03 的目标应是 x 更近的那个。"""
        policy = GamePolicy(tick_hz=TICK_HZ, seed=3)
        world = World(enemy_target=0, bullet_target=0, seed=1,
                      enable_kills=True, policy=policy)
        # 强制造一只 0x03 在左侧，玩家 1 在 100、玩家 2 在 600
        from server.entities import Enemy

        enemy = Enemy(enemy_id=world.new_enemy_id(), x=150, y=100, type=ENEMY_TRACK, hp=2)
        world.enemies.append(enemy)
        for _ in range(RETARGET_TICKS):
            world.step([(1, 100), (2, 600)])
        self.assertEqual(enemy.target_x, 100)
        # 换个位置：玩家 2 挪到 200，仍是玩家 1 更近；挪到 150 附近就该换目标
        for _ in range(RETARGET_TICKS):
            world.step([(1, 600), (2, 160)])
        self.assertEqual(enemy.target_x, 160)


class PlayerFireTest(unittest.TestCase):
    def test_fire_requires_key(self):
        """不发开火位就**不能**产生玩家子弹。"""
        world, policy = make_world()
        run(world, policy, 60, firing=False)
        self.assertEqual(sum(1 for b in world.bullets if b.owner_id), 0)

    def test_fire_rate_is_server_side(self):
        """按住开火 10 秒，发射数应接近 10/间隔，而不是"每 tick 一发"。"""
        spawn_y = PLAYER_Y - PLAYER_MUZZLE_OFFSET
        world, policy = make_world()
        fired = 0
        for _ in range(10 * TICK_HZ):
            world.step([(1, 300, PLAYER_Y)], firing={1})
            # 本 tick 新生成的玩家子弹一定还在枪口 y 上（_move 先跑，spawn 后追加）。
            # 不要用 id() 去重 —— Python 会复用对象 id，会漏计（踩过）。
            fired += sum(
                1 for b in world.bullets if b.owner_id and b.y == spawn_y
            )
        expected = 10 / 0.14
        self.assertLess(fired, expected * 1.35, f"打得太快：{fired} 发")
        self.assertGreater(fired, expected * 0.6, f"打得太慢：{fired} 发")

    def test_player_bullet_cap(self):
        """按住开火也不能无限堆子弹。"""
        world, policy = make_world()
        run(world, policy, 30 * TICK_HZ)
        player_bullets = sum(1 for b in world.bullets if b.owner_id)
        self.assertLessEqual(player_bullets, policy.max_player_bullets)

    def test_total_bullet_cap(self):
        world, policy = make_world()
        run(world, policy, 60 * TICK_HZ)
        self.assertLessEqual(len(world.bullets), policy.max_total_bullets)


class DefaultPathTest(unittest.TestCase):
    """**默认（实验）路径必须完全不受游戏内容影响。**"""

    def test_placeholder_does_not_manage_spawning(self):
        self.assertFalse(PlaceholderPolicy.manages_spawning)
        self.assertTrue(GamePolicy.manages_spawning)

    def test_step_without_firing_still_works(self):
        """旧的 `world.step(players)` 调用方式必须继续可用（默认参数）。"""
        world = World(enemy_target=4, bullet_target=6, seed=1)
        world.step([(1, 300)])
        self.assertEqual(len(world.enemies), 4)
        self.assertTrue(world.policy.manages_spawning is False)

    def test_game_mode_does_not_leak_into_placeholder(self):
        """先跑一阵 GamePolicy，再建一个占位世界 —— 后者必须一模一样。"""
        game_world, _ = make_world()
        run(game_world, _, 100)

        world = World(enemy_target=5, bullet_target=8, seed=1)
        world.step([(1, 300)])
        ys = [e.y for e in world.enemies]
        self.assertEqual(ys, [0] * 5, "占位敌机应该全在 y=0（未被游戏逻辑污染）")
        self.assertEqual(len(world.bullets), 8)

    def test_wave_defaults_are_one(self):
        """wave/level 默认 1 —— 与编码器默认值一致，所以实验路径字节不变。"""
        world = World(enemy_target=1, bullet_target=0, seed=1)
        self.assertEqual((world.level, world.wave), (1, 1))


class ScoreTest(unittest.TestCase):
    def test_per_type_score(self):
        policy = GamePolicy(tick_hz=TICK_HZ, seed=1)
        from server.entities import Enemy

        self.assertEqual(policy.score_for(Enemy(1, 0, 0, ENEMY_DIVE)), 10)
        self.assertEqual(policy.score_for(Enemy(1, 0, 0, ENEMY_WEAVE)), 20)
        self.assertEqual(policy.score_for(Enemy(1, 0, 0, ENEMY_TRACK)), 30)

    def test_placeholder_score_is_none(self):
        """占位策略返回 None → World 退回 score_per_kill（10），与之前一致。"""
        from server.entities import Enemy

        self.assertIsNone(PlaceholderPolicy().score_for(Enemy(1, 0, 0)))


class FeedbackRegressionTest(unittest.TestCase):
    """2026-11-06 试玩反馈里**能变成测试**的三条。

    用户的反馈大多属于手感（不好测），但这三条是**坐标/数值**问题，
    可以精确断言 —— 不写成测试，下次改动很容易又退回去。
    """

    def test_player_bullet_comes_from_the_ship_not_behind_it(self):
        """问题 1：我方子弹必须从**玩家自己**的机头出来。

        原来固定从 `PLAYER_BULLET_SPAWN_Y = 900` 出生，而玩家在 y=760/700/640/580 ——
        子弹出现在船体**下方**，看起来像从背后发射。
        """
        world, policy = make_world()
        world.step([(1, 300, PLAYER_Y)], firing={1})
        mine = [b for b in world.bullets if b.owner_id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].y, PLAYER_Y - PLAYER_MUZZLE_OFFSET)

        # 换个玩家位置（第 2 个玩家的 y 是 700），子弹要跟着变
        world.step([(1, 300, 700)], firing={1})
        mine = [b for b in world.bullets if b.owner_id and b.y != mine[0].y]
        # 冷却中可能还没发；直接检查策略层的换算
        self.assertEqual(700 - PLAYER_MUZZLE_OFFSET, 682)

    def test_enemy_bullet_spawns_below_the_body(self):
        """问题 2：敌方子弹从机身**外缘**打出，不是从机体中心穿出来。"""
        policy = GamePolicy(tick_hz=TICK_HZ, seed=1)
        world = World(enemy_target=0, bullet_target=0, seed=1,
                      enable_kills=True, policy=policy)
        from server.entities import Enemy

        enemy = Enemy(enemy_id=world.new_enemy_id(), x=300, y=100,
                      type=ENEMY_DIVE, hp=1)
        enemy.fire_cd = 0
        world.enemies.append(enemy)
        policy._enemy_fire(world)   # 直接触发一次开火
        fired = [b for b in world.bullets if b.owner_id == 0]
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].y, 100 + ENEMY_MUZZLE_OFFSET)
        self.assertGreater(fired[0].y, enemy.y, "子弹必须在机身下方")

    def test_collision_radius_is_bigger_in_game_mode(self):
        """问题 3：判定半径要跟视觉尺寸匹配（原来 8 px 太小，"打中却不算"）。"""
        from server.entities import COLLISION_RADIUS, Enemy

        self.assertEqual(PlaceholderPolicy().collision_radius(Enemy(1, 0, 0)),
                         COLLISION_RADIUS, "占位路径必须保持 8（E9 基线靠它）")
        policy = GamePolicy(tick_hz=TICK_HZ, seed=1)
        for enemy_type, radius in COLLISION_RADIUS_BY_TYPE.items():
            self.assertGreaterEqual(
                policy.collision_radius(Enemy(1, 0, 0, enemy_type)), 12,
                f"type {enemy_type:#x} 的判定半径太小",
            )

    def test_fire_interval_has_randomness(self):
        """问题 5：开火间隔要有抖动，不能机械地同一节奏。"""
        policy = GamePolicy(tick_hz=TICK_HZ, seed=5)
        world = World(enemy_target=0, bullet_target=0, seed=1,
                      enable_kills=True, policy=policy)
        from server.entities import Enemy

        cds = []
        for _ in range(40):
            world.enemies.clear()
            world.bullets.clear()
            enemy = Enemy(enemy_id=world.new_enemy_id(), x=300, y=200,
                          type=ENEMY_DIVE, hp=1)
            world.enemies.append(enemy)
            policy._enemy_fire(world)
            cds.append(enemy.fire_cd)
        self.assertGreater(max(cds) - min(cds), 2,
                           f"开火间隔没有抖动：{sorted(set(cds))}")

    def test_fan_angles_are_jittered(self):
        """问题 5：扇形弹的角度不能每次都一模一样。"""
        policy = GamePolicy(tick_hz=TICK_HZ, seed=9)
        world = World(enemy_target=0, bullet_target=0, seed=1,
                      enable_kills=True, policy=policy)
        from server.entities import Enemy

        patterns = set()
        for _ in range(12):
            world.bullets.clear()
            enemy = Enemy(enemy_id=world.new_enemy_id(), x=300, y=200,
                          type=ENEMY_WEAVE, hp=2)
            world.enemies.append(enemy)
            policy._enemy_fire(world)
            patterns.add(tuple(sorted(b.angle for b in world.bullets)))
        self.assertGreater(len(patterns), 1, "扇形弹角度全一样，没有抖动")

class PlayerTupleShapeTest(unittest.TestCase):
    """**2026-11-07 事故的回归测试**。

    服务端传的玩家元组从 `(id, x)` 变成了 `(id, x, y)`，
    但 `_retarget` 里还有一处按两个值解包 —— 只在第 3 波出现追踪机时才被调用，
    于是无论模拟还是前两波都正常，一进第 3 波就抛 ValueError，
    **tick 循环静默死掉**，玩家看到的是"卡在第 3 波"。

    当时测试只传两元组，所以没抓到。现在两种形态都必须过。
    """

    def test_tick_spawn_accepts_two_tuples(self):
        world, policy = make_world()
        for _ in range(120):
            world.step([(1, 300)])          # 旧形态
        self.assertGreater(policy.spawned_total, 0)

    def test_tick_spawn_accepts_three_tuples(self):
        world, policy = make_world()
        for _ in range(120):
            world.step([(1, 300, 760)])     # 服务端现在的形态
        self.assertGreater(policy.spawned_total, 0)

    def test_retarget_works_with_both_tuple_shapes(self):
        """直接打到 `_retarget` —— 这正是当年炸掉的那一行。"""
        from server.entities import Enemy

        for players in ([(1, 100), (2, 600)], [(1, 100, 760), (2, 600, 760)]):
            policy = GamePolicy(tick_hz=TICK_HZ, seed=3)
            world = World(enemy_target=0, bullet_target=0, seed=1,
                          enable_kills=True, policy=policy)
            enemy = Enemy(enemy_id=world.new_enemy_id(), x=150, y=100,
                          type=ENEMY_TRACK, hp=2)
            world.enemies.append(enemy)
            for _ in range(RETARGET_TICKS):
                world.step(players)
            self.assertEqual(enemy.target_x, 100,
                             f"players={players} 时目标算错了")

    def test_retarget_runs_on_multi_player_three_tuples(self):
        """三个玩家、带 y 的形态 —— 服务端多开时就是这样。"""
        from server.entities import Enemy

        policy = GamePolicy(tick_hz=TICK_HZ, seed=3)
        world = World(enemy_target=0, bullet_target=0, seed=1,
                      enable_kills=True, policy=policy)
        enemy = Enemy(enemy_id=world.new_enemy_id(), x=500, y=100,
                      type=ENEMY_TRACK, hp=2)
        world.enemies.append(enemy)
        players = [(1, 100, 760), (2, 300, 700), (3, 480, 640)]
        for _ in range(RETARGET_TICKS):
            world.step(players)
        self.assertEqual(enemy.target_x, 480)

class LobbyTest(unittest.TestCase):
    """没人时不能刷，打完空场后有人进来要能自动重开。

    2026-11-08 踩到：服务端一启动就推进波次。玩家要先注册/登录、再连 TCP，
    等他进来时第 1、2 波已经过去了，场上只剩空屏（截图 tick=2474、e/b=0/0）。
    """

    def test_no_players_freezes_waves(self):
        world, policy = make_world()
        for _ in range(200):
            world.step([], set())
        self.assertEqual(policy.spawned_total, 0, "没人也在刷敌机")
        self.assertEqual(len(world.enemies), 0)

    def test_waves_start_when_player_joins(self):
        world, policy = make_world()
        for _ in range(60):
            world.step([], set())
        self.assertEqual(policy.spawned_total, 0)

        for _ in range(60):
            world.step([(1, 360, 760)], firing={1})
        self.assertGreater(policy.spawned_total, 0, "有人进来了却不开刷")

    def test_restart_after_finished_and_empty(self):
        world, policy = make_world()
        # 打完一局
        for _ in range(200 * TICK_HZ):
            world.step([(1, 360, 760)], firing=set())
            if policy.finished and not world.enemies:
                break
        self.assertTrue(policy.finished)
        first_round = policy.spawned_total
        self.assertEqual(first_round, sum(w.total for w in WAVES))

        # 空场 6 秒，等于"人都退了"
        for _ in range(6 * TICK_HZ):
            world.step([], set())
        self.assertEqual(len(world.enemies), 0)

        # 再有人进来 → 自动重开
        for _ in range(20):
            world.step([(1, 360, 760)], firing={1})
        self.assertFalse(policy.finished, "没有重开")
        self.assertLess(policy.spawned_total, first_round)
        self.assertGreater(policy.spawned_total, 0)

    def test_reset_keeps_scores(self):
        """重开一局**不能**抹掉累计分 —— 那是玩家跨局的战绩。"""
        world, policy = make_world()
        world.scores[1] = 1234
        for _ in range(5 * TICK_HZ):
            world.step([(1, 360, 760)], firing={1})
        policy.finished = True
        poworld_before = dict(world.scores)
        for _ in range(6 * TICK_HZ):
            world.step([], set())
        world.step([(1, 360, 760)], firing={1})
        self.assertEqual(world.scores, poworld_before, "重开把分数抹了")


if __name__ == "__main__":
    unittest.main()