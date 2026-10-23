"""占位实体（server/entities.py）的单元测试。

重点验证三件事：
    1. 角度 → 位移的换算（8 方向整数表，0° = 正上）
    2. 出屏即剔除（D-012）
    3. **数量恒定** —— 这是 E9 自变量成立的前提
"""

import unittest

from protocol.messages import ANGLE_DOWN, ANGLE_LEFT, ANGLE_RIGHT, ANGLE_UP
from protocol.world import WORLD_HEIGHT, WORLD_WIDTH
from server.entities import (
    BULLET_SPEED_PER_TICK,
    ENEMY_SPEED_PER_TICK,
    Bullet,
    Enemy,
    World,
    angle_to_delta,
)

PLAYERS = [(1, 360)]


class AngleTest(unittest.TestCase):
    """0° = 正上方、顺时针（02 §4.5）。"""

    def test_four_cardinal_directions(self):
        self.assertEqual(angle_to_delta(ANGLE_UP, 10), (0, -10))
        self.assertEqual(angle_to_delta(ANGLE_RIGHT, 10), (10, 0))
        self.assertEqual(angle_to_delta(ANGLE_DOWN, 10), (0, 10))
        self.assertEqual(angle_to_delta(ANGLE_LEFT, 10), (-10, 0))

    def test_diagonal(self):
        self.assertEqual(angle_to_delta(32, 10), (10, -10))

    def test_quantized_to_eight_directions(self):
        # 每一档 32，档内任意角度结果相同
        self.assertEqual(angle_to_delta(0, 7), angle_to_delta(31, 7))
        self.assertEqual(angle_to_delta(32, 7), angle_to_delta(63, 7))
        self.assertNotEqual(angle_to_delta(0, 7), angle_to_delta(32, 7))

    def test_out_of_range_angle_is_masked(self):
        # 角度是 uint8：超出的高位被掩掉，等价于对 256 取模
        self.assertEqual(angle_to_delta(256, 10), angle_to_delta(0, 10))
        self.assertEqual(angle_to_delta(288, 10), angle_to_delta(32, 10))


class WorldValidationTest(unittest.TestCase):
    def test_enemy_target_must_fit_uint8(self):
        with self.assertRaises(ValueError):
            World(enemy_target=256)
        with self.assertRaises(ValueError):
            World(enemy_target=-1)

    def test_bullet_target_must_fit_uint16(self):
        with self.assertRaises(ValueError):
            World(bullet_target=65536)

    def test_limits_are_the_protocol_limits(self):
        World(enemy_target=255, bullet_target=65535)  # 边界值应当接受


class WorldSpawnTest(unittest.TestCase):
    def test_fills_to_target_on_first_step(self):
        world = World(enemy_target=12, bullet_target=30, seed=1)
        self.assertEqual(world.counts(), (0, 0))

        world.step(PLAYERS)
        self.assertEqual(world.counts(), (12, 30))

    def test_entity_count_stays_constant(self):
        # E9 的自变量必须稳定：跑 300 个 tick 后数量不能变
        world = World(enemy_target=20, bullet_target=100, seed=2)
        for _ in range(300):
            world.step(PLAYERS)
            self.assertEqual(world.counts(), (20, 100))

    def test_enemies_spawn_at_the_top_edge(self):
        # _move() 先跑、_respawn() 后跑，所以刚生成的敌机这一 tick 还停在 y=0，
        # 下一个 tick 才开始往下走（不会「凭空往下跳一步」）
        world = World(enemy_target=5, seed=3)
        world.step([])
        self.assertTrue(all(e.y == 0 for e in world.enemies))

        world.step([])
        self.assertTrue(all(e.y == ENEMY_SPEED_PER_TICK for e in world.enemies))

    def test_bullets_split_between_players_and_enemy(self):
        world = World(bullet_target=10, seed=4)
        world.step(PLAYERS)

        owners = [b.owner_id for b in world.bullets]
        self.assertEqual(owners.count(0), 5)  # 5 颗敌方子弹
        self.assertEqual(owners.count(1), 5)  # 5 颗玩家 1 的子弹

    def test_player_bullets_start_from_the_player(self):
        world = World(bullet_target=2, seed=4)
        world.step([(9, 555)])

        player_bullet = next(b for b in world.bullets if b.owner_id == 9)
        self.assertEqual(player_bullet.x, 555)
        self.assertEqual(player_bullet.angle, ANGLE_UP)

    def test_enemy_bullets_fly_down(self):
        world = World(bullet_target=4, seed=5)
        world.step(PLAYERS)
        for bullet in world.bullets:
            if bullet.owner_id == 0:
                self.assertEqual(bullet.angle, ANGLE_DOWN)

    def test_no_players_still_produces_enemy_bullets(self):
        # 没有玩家连进来时不该崩，也不该产出「无主」的玩家子弹
        world = World(bullet_target=6, seed=6)
        world.step([])
        self.assertTrue(all(b.owner_id == 0 for b in world.bullets))

    def test_enemy_ids_are_unique(self):
        world = World(enemy_target=30, seed=7)
        for _ in range(200):
            world.step(PLAYERS)
            ids = [e.enemy_id for e in world.enemies]
            self.assertEqual(len(ids), len(set(ids)))

    def test_enemy_id_wraps_around_uint16(self):
        world = World(enemy_target=1, seed=8)
        world.next_enemy_id = 0xFFFF
        world.step([])

        self.assertEqual(world.enemies[0].enemy_id, 0xFFFF)
        self.assertEqual(world.next_enemy_id, 1)  # 绕回 1，不用 0（0 留给敌方子弹）


class WorldMovementTest(unittest.TestCase):
    def test_enemy_moves_down(self):
        world = World(seed=1)
        world.enemies.append(Enemy(1, 100, 100))
        world.step([])
        self.assertEqual(world.enemies[0].y, 100 + ENEMY_SPEED_PER_TICK)

    def test_bullet_moves_along_its_angle(self):
        world = World(seed=1)
        world.bullets.append(Bullet(0, 100, 100, 0x11, ANGLE_DOWN))
        world.step([])
        self.assertEqual(world.bullets[0].y, 100 + BULLET_SPEED_PER_TICK)

    def test_enemy_leaving_bottom_is_removed(self):
        # 出屏即剔除（D-012）：不写进快照，客户端自然删除它
        world = World(seed=1)  # target 0：剔除后不会补新的
        world.enemies.append(Enemy(1, 100, WORLD_HEIGHT - 1))
        world.step([])
        self.assertEqual(world.enemies, [])

    def test_bullet_leaving_top_is_removed(self):
        world = World(seed=1)
        world.bullets.append(Bullet(0, 100, 5, 0x01, ANGLE_UP))
        world.step([])
        self.assertEqual(world.bullets, [])

    def test_bullet_leaving_side_is_removed(self):
        world = World(seed=1)
        world.bullets.append(Bullet(0, WORLD_WIDTH - 1, 500, 0x11, ANGLE_RIGHT))
        world.step([])
        self.assertEqual(world.bullets, [])

    def test_coordinates_stay_inside_uint16(self):
        # D-012 记录的 struct.error 就是这么来的：越界坐标进了编码器
        world = World(enemy_target=10, bullet_target=40, seed=9)
        for _ in range(400):
            world.step(PLAYERS)
            for enemy in world.enemies:
                self.assertTrue(0 <= enemy.x <= 0xFFFF)
                self.assertTrue(0 <= enemy.y <= 0xFFFF)
            for bullet in world.bullets:
                self.assertTrue(0 <= bullet.x <= 0xFFFF)
                self.assertTrue(0 <= bullet.y <= 0xFFFF)


class WorldDeterminismTest(unittest.TestCase):
    def test_same_seed_gives_same_world(self):
        # 固定种子 → 同样的轨迹，E9 才可复现
        first = World(enemy_target=8, bullet_target=20, seed=42)
        second = World(enemy_target=8, bullet_target=20, seed=42)

        for _ in range(50):
            first.step(PLAYERS)
            second.step(PLAYERS)

        self.assertEqual(first.snapshot_enemies(), second.snapshot_enemies())
        self.assertEqual(first.snapshot_bullets(), second.snapshot_bullets())

    def test_different_seed_gives_different_world(self):
        first = World(enemy_target=8, seed=1)
        second = World(enemy_target=8, seed=2)
        first.step(PLAYERS)
        second.step(PLAYERS)
        self.assertNotEqual(first.snapshot_enemies(), second.snapshot_enemies())


class SnapshotExportTest(unittest.TestCase):
    def test_export_matches_internal_lists(self):
        world = World(enemy_target=3, bullet_target=7, seed=11)
        world.step(PLAYERS)

        enemies = world.snapshot_enemies()
        bullets = world.snapshot_bullets()

        self.assertEqual(len(enemies), 3)
        self.assertEqual(len(bullets), 7)
        self.assertEqual(enemies[0].enemy_id, world.enemies[0].enemy_id)
        self.assertEqual(bullets[0].owner_id, world.bullets[0].owner_id)
        self.assertEqual(world.counts(), (3, 7))


if __name__ == "__main__":
    unittest.main()