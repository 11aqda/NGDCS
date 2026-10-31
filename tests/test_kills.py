"""击杀生效（`--enable-kills`）的测试。

这个改动的**第一原则是别动基线**：E9/E1/E2 的全部数据都是在「碰撞只判定不生效」
下测的，`collision_ms` 是那些图的一部分。所以：

- 默认（`enable_kills=False`）**走原来那条只计数的循环，一字未改**
- 结算逻辑单独一份 `resolve_kills()`，只在显式开启时才走

下面既测新功能，也测"没开的时候行为一点没变"。
"""

import unittest

from protocol.messages import ANGLE_DOWN, ANGLE_UP, BULLET_ENEMY_SPREAD, BULLET_PLAYER_L1
from server.entities import Bullet, Enemy, World, detect_collisions


def player_bullet(x: int, y: int, owner: int = 7) -> Bullet:
    return Bullet(owner_id=owner, x=x, y=y, type=BULLET_PLAYER_L1, angle=ANGLE_UP)


def enemy_bullet(x: int, y: int) -> Bullet:
    return Bullet(owner_id=0, x=x, y=y, type=BULLET_ENEMY_SPREAD, angle=ANGLE_DOWN)


def make_world(**kwargs) -> World:
    return World(enemy_target=0, bullet_target=0, seed=1, **kwargs)


class BaselineUnchangedTest(unittest.TestCase):
    """没开击杀时，一切必须和改动前一模一样。"""

    def test_default_is_off(self):
        self.assertFalse(make_world().enable_kills)
        self.assertFalse(make_world().fixed_entities)

    def test_counting_path_still_counts_only(self):
        enemies = [Enemy(enemy_id=1, x=100, y=100)]
        bullets = [player_bullet(100, 100)]
        hits = detect_collisions(bullets, enemies)
        self.assertEqual(hits, 1)
        # 关键：只数不动
        self.assertEqual(len(enemies), 1)
        self.assertEqual(enemies[0].hp, 1)
        self.assertEqual(len(bullets), 1)

    def test_entities_stay_at_target_without_kills(self):
        world = World(enemy_target=5, bullet_target=5, seed=1)
        for _ in range(5):
            world.step([])
        self.assertEqual(world.counts(), (5, 5))


class ResolveKillsTest(unittest.TestCase):
    def test_hit_kills_and_awards(self):
        world = make_world(enable_kills=True)
        world.enemies = [Enemy(enemy_id=1, x=100, y=100, hp=1)]
        world.bullets = [player_bullet(100, 100, owner=7)]
        hits, killed = world.resolve_kills()
        self.assertEqual((hits, killed), (1, 1))
        self.assertEqual(world.scores[7], world.score_per_kill)
        self.assertEqual(world.enemies, [])
        self.assertEqual(world.bullets, [], "命中的子弹必须被消耗掉")

    def test_tough_enemy_needs_multiple_hits(self):
        world = make_world(enable_kills=True)
        world.enemies = [Enemy(enemy_id=1, x=100, y=100, hp=3)]
        world.bullets = [player_bullet(100, 100)]
        _, killed = world.resolve_kills()
        self.assertEqual(killed, 0)
        self.assertEqual(world.enemies[0].hp, 2)
        self.assertEqual(world.scores, {})

    def test_miss_changes_nothing(self):
        world = make_world(enable_kills=True)
        world.enemies = [Enemy(enemy_id=1, x=500, y=100)]
        world.bullets = [player_bullet(100, 100)]
        hits, killed = world.resolve_kills()
        self.assertEqual((hits, killed), (0, 0))
        self.assertEqual(len(world.bullets), 1)
        self.assertEqual(len(world.enemies), 1)

    def test_enemy_bullets_never_score(self):
        """敌方子弹 owner_id=0，即使压在敌机上也该被跳过。

        真实情况里它朝下飞、不会碰到敌机，但逻辑上必须挡住 ——
        否则将来加"友军伤害"或 AI 后会出现"敌人自己给自己加分"。
        """
        world = make_world(enable_kills=True)
        world.enemies = [Enemy(enemy_id=1, x=100, y=100)]
        world.bullets = [enemy_bullet(100, 100)]
        hits, killed = world.resolve_kills()
        self.assertEqual((hits, killed), (0, 0))
        self.assertEqual(world.scores, {})

    def test_one_bullet_hits_only_one_enemy(self):
        world = make_world(enable_kills=True)
        world.enemies = [
            Enemy(enemy_id=1, x=100, y=100),
            Enemy(enemy_id=2, x=102, y=100),
        ]
        world.bullets = [player_bullet(101, 100)]
        hits, killed = world.resolve_kills()
        self.assertEqual((hits, killed), (1, 1))
        self.assertEqual(len(world.enemies), 1, "一颗子弹只该带走一个目标")

    def test_score_saturates_at_uint16(self):
        """score 是协议里的 uint16 字段，越界会让 struct.pack 抛错 -
        那会像 E2 的 257 玩家一样直接搞死 tick 循环，所以必须夹住。"""
        world = make_world(enable_kills=True)
        world.scores[7] = 0xFFFF - 1
        world._award(7)
        self.assertEqual(world.scores[7], 0xFFFF)


class RespawnTest(unittest.TestCase):
    def test_fixed_entities_refills_immediately(self):
        """实验期：击杀后必须立刻补满，实体数恒定（D-029）。

        否则 `--fixed-entities` 的守卫会当场抛错 —— 这正是它该做的事。
        """
        world = World(enemy_target=10, bullet_target=0, seed=1,
                      enable_kills=True, fixed_entities=True)
        for _ in range(3):
            world.step([])
        self.assertEqual(world.counts()[0], 10)

        world.enemies.pop()  # 模拟一次击杀
        world.step([])
        self.assertEqual(world.counts()[0], 10, "固定模式下必须立刻补回目标数")

    def test_fixed_entities_refills_right_after_a_kill(self):
        """⭐ 回归测试：击杀**当场**就要补，不能等下一个 tick 的 `_respawn()`。

        2026-10-31 实测踩到：守卫在 `step()` 之后检查，那时已补满，所以守卫**通过**；
        而击杀发生在它之后，快照里的敌机数变成 27~30 —— 守卫形同虚设、数据已不符契约。
        快照字节数是 E9「逐字节等于公式」校验的基础，一浮动就全废。
        """
        world = World(enemy_target=10, bullet_target=0, seed=1,
                      enable_kills=True, fixed_entities=True)
        world.step([])
        world.enemies = [Enemy(enemy_id=99, x=100, y=100, hp=1)]
        world.bullets = [player_bullet(100, 100)]
        _, killed = world.resolve_kills()
        self.assertEqual(killed, 1)
        self.assertEqual(world.counts()[0], 10,
                         "击杀之后必须立刻补回目标数，否则快照字节数会浮动")

    def test_non_fixed_does_not_refill_after_kill(self):
        """反过来：正式游戏模式击杀后**不该**立刻补，玩家要看得到"打掉了"。"""
        world = World(enemy_target=10, bullet_target=0, seed=1,
                      enable_kills=True, fixed_entities=False)
        world.step([])
        world.enemies = [Enemy(enemy_id=99, x=100, y=100, hp=1)]
        world.bullets = [player_bullet(100, 100)]
        _, killed = world.resolve_kills()
        self.assertEqual(killed, 1)
        self.assertEqual(world.counts()[0], 0, "非固定模式应当真的把敌机移除")

    def test_non_fixed_respawn_is_rate_limited(self):
        """正式游戏：一次清空后不该下一 tick 就满血复活，否则玩家看不到反馈。"""
        world = World(enemy_target=20, bullet_target=0, seed=1,
                      enable_kills=True, fixed_entities=False)
        world.enemies.clear()
        world.step([])
        self.assertLessEqual(world.counts()[0], world.respawn_per_tick)
        self.assertLess(world.counts()[0], 20)

    def test_rate_limit_applies_over_ticks(self):
        world = World(enemy_target=6, bullet_target=0, seed=1,
                      enable_kills=True, fixed_entities=False)
        world.enemies.clear()
        for _ in range(3):
            world.step([])
        self.assertEqual(world.counts()[0], 6, "几个 tick 之后应当补满")

    def test_bullets_are_not_rate_limited(self):
        """子弹是发射物，补慢了弹幕会变稀，所以不设速率上限。"""
        world = World(enemy_target=0, bullet_target=100, seed=1,
                      enable_kills=True, fixed_entities=False)
        world.bullets.clear()
        world.step([])
        self.assertEqual(world.counts()[1], 100)


if __name__ == "__main__":
    unittest.main()