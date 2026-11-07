"""验证 tick 循环的异常保护：**抛异常也不能死**。

复现 2026-11-07 那次事故的形态：策略在 tick 里抛 ValueError。
修复前的表现是"进程还在、客户端还连着，但 tick 永远停在某一帧"；
修复后应该是：记异常、跳过这一步、**继续出帧**。
"""

import asyncio

import server.main as m
from server.entities import World


class _FakeWriter:
    """够 broadcast 用就行：write / drain / close / is_closing。"""

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False

    def get_extra_info(self, name, default=None):
        return default


class BadPolicy:
    manages_spawning = True

    def tick_spawn(self, world, players, firing):
        raise ValueError("故意的：模拟策略在 tick 里炸掉")

    def enemy_move(self, enemy):
        return (0, 0)

    def bullet_move(self, bullet):
        return (0, 0)

    def collision_radius(self, enemy):
        return 8

    def score_for(self, enemy):
        return None


async def scenario() -> tuple[int, int]:
    world = World(enemy_target=0, bullet_target=0, seed=1, policy=BadPolicy())
    server = m.GameServer(world=world, print_stats=False)
    server.clients[1] = m.Client(
        player_id=1, color=1, x=360, y=760, writer=_FakeWriter(),  # type: ignore[arg-type]
    )
    server.tick = 0

    task = asyncio.create_task(server.tick_loop())
    await asyncio.sleep(0.8)
    alive = not task.done()      # 任务还活着 = 循环没死
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return server.tick, server._tick_errors if alive else -1


tick, errors = asyncio.run(scenario())
print(f"  跑了 {tick} tick，捕获异常 {errors} 次")

if tick > 5 and errors > 0:
    print("  [OK] 异常被吃掉，tick 继续前进 —— 不会再出现'卡在第 N 波'")
elif errors < 0:
    print("  [FAIL] tick 循环当场死掉了")
else:
    print(f"  [FAIL] tick={tick} errors={errors}")
raise SystemExit(0 if (tick > 5 and errors > 0) else 1)