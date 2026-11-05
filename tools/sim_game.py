"""headless 模拟一局，量"三波打完要多久"。

不启服务端、不走网络 —— 只跑 `World.step()`，所以结果是确定性的。
用来核对设计文档 §3 的"三波约 85 秒"是否成立。
"""

from server.entities import World
from server.game_policy import GamePolicy, WAVES

TICK_HZ = 20


def simulate(tick_hz: int = TICK_HZ, firing: bool = True, limit_s: float = 300.0) -> dict:
    policy = GamePolicy(tick_hz=tick_hz, seed=1)
    world = World(enemy_target=0, bullet_target=0, seed=1,
                  enable_kills=True, policy=policy)

    max_enemies = max_bullets = 0
    wave_seen = 0
    wave_start_tick = 0
    wave_times: list[tuple[int, float]] = []

    max_ticks = int(limit_s * tick_hz)
    for tick in range(1, max_ticks + 1):
        # 玩家在场上左右横跳，制造"追踪目标会变"的情况
        x = 120 + (tick * 7) % 480
        world.step([(1, x)], firing={1} if firing else set())

        if world.wave != wave_seen:
            if wave_seen:
                wave_times.append((wave_seen, (tick - wave_start_tick) / tick_hz))
            wave_seen = world.wave
            wave_start_tick = tick

        max_enemies = max(max_enemies, len(world.enemies))
        max_bullets = max(max_bullets, len(world.bullets))

        if policy.finished and not world.enemies:
            break
    else:
        tick = max_ticks

    if wave_seen:
        wave_times.append((wave_seen, (tick - wave_start_tick) / tick_hz))

    return {
        "elapsed_s": round(tick / tick_hz, 1),
        "finished": policy.finished,
        "spawned": policy.spawned_total,
        "expected": sum(w.total for w in WAVES),
        "max_enemies": max_enemies,
        "max_bullets": max_bullets,
        "wave_times": [(w, round(t, 1)) for w, t in wave_times],
    }


if __name__ == "__main__":
    for hz in (20,):
        result = simulate(hz)
        print(f"=== {hz} Hz ===")
        print(f"  三波总时长 : {result['elapsed_s']} s")
        print(f"  每波耗时   : {result['wave_times']}")
        print(f"  生成敌机   : {result['spawned']} / {result['expected']}")
        print(f"  打完       : {result['finished']}")
        print(f"  同屏最多   : {result['max_enemies']} 敌机 / {result['max_bullets']} 子弹")
    print()
    print("  对照：设计文档 §3 预期 ≈85 s（波次 26+23+24 + 停顿 3×3）")
    print()
    # 不同 tick 率下应该**手感一致**（时长不随 tick 率变）
    for hz in (10, 30):
        result = simulate(hz)
        print(f"  {hz} Hz 下三波总时长 {result['elapsed_s']} s"
              f"（与 20 Hz 的偏差 {abs(result['elapsed_s'] - simulate(20)['elapsed_s']):.1f} s）")