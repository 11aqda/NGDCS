"""策略接口的测试：证明"扩展点"真的接上了，而且默认行为没变。

这不是游戏内容测试 —— 它验证的是**重构本身**：

1. 默认构造出来的 World 用的是 `PlaceholderPolicy`
2. 换一个自定义策略，`World` 真的会去问它（否则这个"扩展点"是假的）
3. 默认策略的数值与重构前的常量完全一致

第 3 条尤其重要：如果哪天有人"顺手"把 `PlaceholderPolicy` 里的 3 px/tick
改成 4，黄金基线会红，但这个测试能**当场指出是哪个常量被改了**，
比对着 SHA 猜要快得多。
"""

import random
import unittest

from protocol.world import WORLD_WIDTH
from server.entities import (
    BULLET_SPEED_PER_TICK,
    ENEMY_SPEED_PER_TICK,
    SPAWN_MARGIN,
    Bullet,
    Enemy,
    PlaceholderPolicy,
    World,
    angle_to_delta,
)


class DefaultPolicyTest(unittest.TestCase):
    def test_world_uses_placeholder_by_default(self):
        self.assertIsInstance(World().policy, PlaceholderPolicy)

    def test_constants_match_pre_refactor(self):
        """重构前的常量：敌机 3 px/tick、子弹 12 px/tick。

        这两个数字是 E1/E2/E9 全部基线的一部分，改它们必须同步更新黄金基线。
        """
        self.assertEqual(ENEMY_SPEED_PER_TICK, 3)
        self.assertEqual(BULLET_SPEED_PER_TICK, 12)

    def test_enemy_moves_down_by_the_old_speed(self):
        policy = PlaceholderPolicy()
        self.assertEqual(policy.enemy_move(Enemy(1, 100, 100)), (0, ENEMY_SPEED_PER_TICK))

    def test_bullet_move_matches_angle_table(self):
        policy = PlaceholderPolicy()
        for angle in range(0, 256, 32):
            bullet = Bullet(owner_id=0, x=10, y=10, type=0, angle=angle, speed=12)
            self.assertEqual(
                policy.bullet_move(bullet), angle_to_delta(angle, bullet.speed)
            )

    def test_enemy_spawn_uses_exactly_one_rng_call(self):
        """**这条是重构的红线**：出生只许调一次 rng。

        多调一次就会让整条随机数序列错位 —— 快照字节全变，而代码看起来没问题。
        用"可复现的 rng 状态"间接验证：同一 seed 下，连续出生 N 个后的状态
        必须与手工调用 N 次 randrange 一致。
        """
        policy = PlaceholderPolicy()

        via_policy = random.Random(12345)
        for _ in range(5):
            policy.enemy_spawn(via_policy)

        manual = random.Random(12345)
        for _ in range(5):
            manual.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN)

        self.assertEqual(via_policy.random(), manual.random())

    def test_bullet_spawn_uses_one_rng_call_per_branch(self):
        """玩家弹与敌方弹**两条分支各一次** rng 调用 —— 奇偶轮换不影响序列长度。"""
        policy = PlaceholderPolicy()
        players = [(1, 100), (2, 200)]

        via_policy = random.Random(999)
        for want_player in (True, False, True, False):
            policy.bullet_spawn(via_policy, players, want_player)

        manual = random.Random(999)
        for pick_player in (True, False, True, False):
            if pick_player:
                manual.randrange(len(players))
            else:
                manual.randrange(SPAWN_MARGIN, WORLD_WIDTH - SPAWN_MARGIN)

        self.assertEqual(via_policy.random(), manual.random())

    def test_no_players_still_produces_enemy_bullets(self):
        """场上没人时也要能出弹（否则子弹数永远补不满，实体数会漂）。"""
        policy = PlaceholderPolicy()
        result = policy.bullet_spawn(random.Random(1), [], want_player=True)
        self.assertEqual(result[0], 0)            # owner_id = 0 → 敌方子弹


class _RecordingPolicy(PlaceholderPolicy):
    """记录被问过什么，证明扩展点是真的接上了。"""

    def __init__(self) -> None:
        self.enemy_spawns = 0
        self.enemy_moves = 0
        self.bullet_spawns = 0
        self.bullet_moves = 0

    def enemy_spawn(self, rng):
        self.enemy_spawns += 1
        return super().enemy_spawn(rng)

    def enemy_move(self, enemy):
        self.enemy_moves += 1
        return super().enemy_move(enemy)

    def bullet_spawn(self, rng, players, want_player):
        self.bullet_spawns += 1
        return super().bullet_spawn(rng, players, want_player)

    def bullet_move(self, bullet):
        self.bullet_moves += 1
        return super().bullet_move(bullet)


class CustomPolicyTest(unittest.TestCase):
    def test_world_actually_consults_the_policy(self):
        policy = _RecordingPolicy()
        world = World(enemy_target=5, bullet_target=8, seed=1, policy=policy)
        world.step([(1, 300)])
        world.step([(1, 300)])

        self.assertGreater(policy.enemy_spawns, 0, "World 没有用策略出生敌机")
        self.assertGreater(policy.enemy_moves, 0, "World 没有用策略移动敌机")
        self.assertGreater(policy.bullet_spawns, 0, "World 没有用策略出生子弹")
        self.assertGreater(policy.bullet_moves, 0, "World 没有用策略移动子弹")

    def test_custom_policy_changes_behavior(self):
        """换个策略就该得到不同结果 —— 否则扩展点形同虚设。"""

        class _FastEnemy(PlaceholderPolicy):
            def enemy_move(self, enemy):
                return 0, 99

        slow = World(enemy_target=3, seed=1)
        fast = World(enemy_target=3, seed=1, policy=_FastEnemy())
        # 两个 tick：第一个 tick 是「先移动、后补生」，所以敌机 born 在移动之后，
        # 要到第二个 tick 才体现出速度差异
        for _ in range(2):
            slow.step([])
            fast.step([])
        self.assertLess(max(e.y for e in slow.enemies), max(e.y for e in fast.enemies))

    def test_ids_and_turn_state_stay_in_world(self):
        """ID 分配与子弹轮换**留在 World**，策略替换不能影响它们。"""
        world = World(enemy_target=3, seed=1, policy=_RecordingPolicy())
        world.step([])
        self.assertEqual([e.enemy_id for e in world.enemies], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()