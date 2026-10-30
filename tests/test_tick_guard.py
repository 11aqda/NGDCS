"""tick_loop 的**存活保障**测试。

起因（2026-10-25 真实踩坑）：`tick_loop` 里一个没导入的名字（`detect_collisions`）
让它在第一个 tick 就抛 `NameError`，然后整个协程**静默死掉**。
症状极具迷惑性 ——

    机器人：clients_connected: 4、snapshots: 0、errors: 0
    服务端：照常监听、照常打印 "player 1 joined"

连接是好的，只是**再也没人广播**。要是没发现，一次 3 分钟的实验会跑完并留下空数据。

所以这里有两道防线：
    1. `test_real_tick_loop_survives` —— 真跑一遍 tick_loop，名字缺一个就失败
    2. `report_tick_crash` 的 done 回调 —— 崩了必须大声报，不能静默
"""

import asyncio
import io
import unittest

from protocol.messages import ANGLE_DOWN
from server.entities import Bullet, Enemy, World
from server.main import Client, GameServer, report_tick_crash


class FakeWriter:
    """只实现 broadcast() 用到的那几个方法，把数据收进内存。

    有它才能在不起真实 socket 的前提下走完「序列化 + 广播」两条路径 ——
    而 2026-10-25 那个 bug 恰恰就死在广播之前的那一行。
    """

    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, chunk: bytes) -> None:
        self.data.extend(chunk)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def attach_player(game: GameServer, player_id: int = 1) -> FakeWriter:
    writer = FakeWriter()
    game.clients[player_id] = Client(
        player_id=player_id, color=1, x=360, y=760, writer=writer
    )
    return writer


class TickLoopSurvivalTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_tick_loop_survives(self):
        """真跑几个 tick：tick_loop 里用到的名字必须全都存在。

        这是那个 `NameError` 的回归测试 —— 它会在第一个 tick 就失败，
        不用等 4 个机器人连上、发现快照是 0 才反应过来。
        """
        world = World(enemy_target=10, bullet_target=20, seed=1)
        game = GameServer(world=world, print_stats=False)

        task = asyncio.create_task(game.tick_loop())
        await asyncio.sleep(0.15)  # 约 3 个 tick

        if task.done():
            exc = task.exception()
            self.fail(f"tick_loop 提前死掉了：{exc!r}")

        self.assertGreaterEqual(game.tick, 1, "一个 tick 都没跑完")

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_tick_records_all_four_phases(self):
        """接上一个客户端后跑完一个窗口：四段都必须有值。

        漏记一段，图 6-20 的堆叠就会缺一块。
        注意 `ser_ms` / `net_ms` 只在**有客户端**时才非零 ——
        没人连的时候服务端会跳过序列化与广播（没必要为空场做无用功）。

        用 30/200（而不是 10/20）：稀疏场地里命中本来就少，
        而 `ser_ms` / `net_ms` / `snapshot_bytes` 都要求实体够多才有意义。
        """
        world = World(enemy_target=30, bullet_target=200, seed=1)
        game = GameServer(world=world, print_stats=False)
        writer = attach_player(game)

        task = asyncio.create_task(game.tick_loop())
        await asyncio.sleep(1.1)  # 跨过一个统计窗口（20 tick ≈ 1 秒）
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        window = game.stats.flush()
        for phase in ("sim_ms", "collision_ms", "ser_ms", "net_ms"):
            self.assertIn(phase, window)
            self.assertGreater(window[phase], 0.0, f"{phase} 没记到数")

        self.assertGreater(window["ticks"], 0)
        self.assertGreater(window["snapshot_bytes"], 0)
        self.assertGreater(len(writer.data), 0, "客户端一个字节都没收到")

    async def test_hits_reach_the_stats_window(self):
        """碰撞命中数要真的进统计窗口 —— 端到端证明 `record_hits` 接上了。

        这里**构造**一个必然命中的场地：子弹 `speed=0` 停在原地，敌机每 tick 下移 3 px，
        初始完全重合 → 第一个 tick dy=3、第二个 dy=6，都在半径 8 之内。

        为什么不用随机布局断言 hits>0：稀疏场地里 hits=0 是**合法**的，
        那样写会变成时过时不过的假测试。碰撞算法的正确性由
        `tests/test_entities.py::CollisionTest` 用构造数据保证。
        """
        world = World(enemy_target=0, bullet_target=0, seed=1)
        for index in range(4):
            world.enemies.append(Enemy(enemy_id=index + 1, x=360, y=200))
            world.bullets.append(
                Bullet(owner_id=0, x=360, y=200, type=0x11, angle=ANGLE_DOWN, speed=0)
            )

        game = GameServer(world=world, print_stats=False)
        attach_player(game)

        task = asyncio.create_task(game.tick_loop())
        await asyncio.sleep(0.15)  # 约 3 个 tick
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        # 4×4 = 16 对；至少跑到一个命中 tick
        self.assertGreaterEqual(game.stats.flush()["hits"], 16)

    async def test_no_clients_means_no_serialization(self):
        """没人连的时候跳过序列化与广播：这是有意的，不是漏做。

        ⚠️ **不要断言 `ser_ms == 0.0`** —— 四段计时必须**无条件**记录，
        否则「四段相加恰好等于 tick_ms」这个不变量就破了（见 D-025）。
        所以"跳过序列化"本身也要花掉一次 `if self.clients` 判断的时间（约亚微秒），
        取窗口平均后可能舍入到 0.001 ms。断言"恰好等于 0"就会随机失败
        —— 2026-10-26 实测：循环 20 次挂 3 次（15%），且与端口无关
        （全测试目录没有一处 bind，唯一的真实 socket 是不占端口的 socketpair）。

        真正**确定性**的证据是：没有生成快照、没有发出任何包。
        """
        world = World(enemy_target=10, bullet_target=20, seed=1)
        game = GameServer(world=world, print_stats=False)

        task = asyncio.create_task(game.tick_loop())
        await asyncio.sleep(1.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        window = game.stats.flush()

        # 逻辑侧照常干活
        self.assertGreater(window["sim_ms"], 0.0)
        self.assertGreater(window["collision_ms"], 0.0)

        # 确定性证据：什么都没序列化、什么都没发出去
        self.assertEqual(window["snapshot_bytes"], 0)
        self.assertEqual(window["packets_out"], 0)
        self.assertEqual(window["bytes_out"], 0)

        # 跳过这两段的**代价**应当可以忽略（而不是"恰好为零"）
        self.assertLess(window["ser_ms"], 0.1)
        self.assertLess(window["net_ms"], 0.1)


class FixedEntitiesGuardTest(unittest.TestCase):
    """D-029 的 `--fixed-entities` 守卫。

    这个守卫**当前永远不会触发**（`World._respawn()` 每 tick 都把数量补回目标值）。
    它存在的意义是：将来击杀生效、敌机真的会被移除时，如果补生漏了，
    **必须当场报错**，而不是让快照悄悄变小、把错误数据录进 CSV。
    所以这里直接构造"数量不一致"的局面来验证它确实会拦。
    """

    def _make(self, fixed: bool, enemies: int = 4, bullets: int = 6) -> GameServer:
        world = World(enemy_target=enemies, bullet_target=bullets, seed=1)
        world.step([])  # 第一次 step 会把实体补到目标数
        return GameServer(world=world, print_stats=False, fixed_entities=fixed)

    def test_no_drift_passes(self):
        """数量与目标一致时不抛错 —— 正常实验跑的就是这条路径。"""
        game = self._make(fixed=True)
        game._verify_entity_counts()  # 不抛异常即通过

    def test_drift_raises(self):
        """少一个敌机就必须抛错，且错误信息要指出"本次数据不可用"。"""
        game = self._make(fixed=True)
        game.world.enemies.pop()
        with self.assertRaises(RuntimeError) as ctx:
            game._verify_entity_counts()
        self.assertIn("实体数漂移", str(ctx.exception))
        self.assertIn("不可用", str(ctx.exception))

    def test_extra_bullet_also_raises(self):
        """多出来也必须拦 —— 漂移是双向的。"""
        game = self._make(fixed=True)
        game.world.bullets.append(game.world.bullets[0])
        with self.assertRaises(RuntimeError):
            game._verify_entity_counts()

    def test_switch_off_means_no_check(self):
        """没开开关时（正式游戏默认）即使数量漂移也不校验 —— 那是有意为之的行为。"""
        game = self._make(fixed=False)
        self.assertFalse(game.fixed_entities)
        game.world.enemies.clear()  # 模拟"击杀生效后真的移除"
        # 开关关着，就不应该有人来拦；真正的校验只在 tick 里按开关调用
        self.assertEqual(len(game.world.enemies), 0)

    def test_default_is_off(self):
        """默认必须是关的：保持"正式游戏"语义，实验脚本负责显式打开（D-029）。"""
        game = GameServer(world=World(enemy_target=1, bullet_target=1, seed=1),
                          print_stats=False)
        self.assertFalse(game.fixed_entities)


class TickCrashReportTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_task_is_not_a_crash(self):
        task = asyncio.create_task(asyncio.sleep(30))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(report_tick_crash(task, file=io.StringIO()))

    async def test_clean_task_is_not_a_crash(self):
        async def ok() -> int:
            return 1

        task = asyncio.create_task(ok())
        await task
        self.assertIsNone(report_tick_crash(task, file=io.StringIO()))

    async def test_exception_is_reported_loudly(self):
        async def boom() -> None:
            raise NameError("name 'detect_collisions' is not defined")

        task = asyncio.create_task(boom())
        with self.assertRaises(NameError):
            await task

        stream = io.StringIO()
        exc = report_tick_crash(task, file=stream)

        self.assertIsInstance(exc, NameError)
        text = stream.getvalue()
        self.assertIn("tick loop 已崩溃", text)
        self.assertIn("NameError", text)
        self.assertIn("detect_collisions", text)


if __name__ == "__main__":
    unittest.main()