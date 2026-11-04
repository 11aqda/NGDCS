"""**黄金基线**：把默认（占位）行为的每一个字节钉死。

## 存在的唯一目的

以后要往游戏里加内容（步骤 11：敌机类型、道具、关卡、BOSS）。
加内容最大的风险不是"新功能坏"，而是**"悄悄改动了实验基线"** ——
默认路径的快照变了几个字节，E1/E2/E9 的历史数字就全部失效，
而且**不会报错**，只会让论文里的图和数据对不上。

所以先上锁：固定 seed + `--fixed-entities` + 4 玩家/30 敌机/200 子弹，
跑 200 tick，把**每帧字节长度、整段 SHA256、若干精确坐标、各 count 字段**写成 JSON 基线。
任何改动让默认路径漂移 → 这里当场红。

## 为什么不会受时钟和网络影响

- 只用 `World.step()` 与 `GameServer.build_snapshot()` —— 两者都**不读墙钟**
- `build_snapshot()` 内部虽然有 `time.perf_counter()`，但只用于统计计时，**不进入字节**
- 完全不走 socket、不走 asyncio —— 没有调度抖动

所以这个测试是**确定性的**：同一份代码永远得到同一串字节。

## 基线怎么更新

**只有故意改变默认行为时**才更新，并且要在提交信息里写清楚为什么：

    .venv\\Scripts\\python.exe -X utf8 -m tools.gen_golden_baseline

更新后 `git diff tests/baselines/golden_default.json` 会显示每一项的变化，
这就是"改动到底影响了什么"的证据。
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path

from protocol.encoders import get_encoder
from protocol.snapshot import unpack_snapshot
from server.entities import World
from server.main import Client, GameServer

BASELINE_PATH = Path(__file__).parent / "baselines" / "golden_default.json"

# 与 D-029 的实验条件一致：4 玩家 / 30 敌机 / 200 子弹
PLAYER_XS = ((1, 100), (2, 260), (3, 420), (4, 580))
ENEMIES = 30
BULLETS = 200
SEED = 1
TICKS = 200


def build_frames() -> tuple[list[bytes], list[dict]]:
    """跑 200 tick，返回（每帧字节, 关键观测点）。

    **刻意不走 asyncio / socket**：这里量的是"协议与模拟"，不是"网络"。
    """
    world = World(
        enemy_target=ENEMIES,
        bullet_target=BULLETS,
        seed=SEED,
        enable_kills=False,      # 占位基线：击杀不生效
        fixed_entities=True,     # D-029
    )
    # 只借它把世界状态编码成快照（build_entities + encoder），不启服务
    game = GameServer(world=world, print_stats=False, encoder=get_encoder("binary"))
    for player_id, x in PLAYER_XS:
        game.clients[player_id] = Client(
            player_id=player_id, color=player_id % 8,
            x=x, y=700, writer=None,  # type: ignore[arg-type]
        )

    frames: list[bytes] = []
    probes: list[dict] = []
    for tick in range(1, TICKS + 1):
        # 与 tick_loop 同序：先模拟，再取快照
        players = [(client.player_id, client.x) for client in game.clients.values()]
        world.step(players)
        game.tick = tick
        payload = game.build_snapshot()
        frames.append(payload)

        if tick in (1, 100, TICKS):
            snapshot = unpack_snapshot(payload)
            probes.append(
                {
                    "tick": tick,
                    "level": snapshot.level,
                    "wave": snapshot.wave,
                    "wave_state": snapshot.wave_state,
                    "player_count": len(snapshot.players),
                    "enemy_count": len(snapshot.enemies),
                    "bullet_count": len(snapshot.bullets),
                    "item_count": len(snapshot.items),
                    "boss_present": int(snapshot.boss_present),
                    "payload_len": len(payload),
                    # 前 5 个敌机的**精确坐标**（不是"大致位置"）
                    "first_enemies": [
                        [enemy.x, enemy.y] for enemy in snapshot.enemies[:5]
                    ],
                }
            )
    return frames, probes


def fingerprint() -> dict:
    frames, probes = build_frames()
    joined = b"".join(frames)
    return {
        "note": "默认（占位）路径的黄金基线。**只有故意改变默认行为时才更新**。",
        "conditions": {
            "players": len(PLAYER_XS), "player_xs": [x for _, x in PLAYER_XS],
            "enemies": ENEMIES, "bullets": BULLETS,
            "seed": SEED, "ticks": TICKS,
            "encoder": "binary", "enable_kills": False, "fixed_entities": True,
            "tick_hz": 20,
        },
        "payload_len_unique": sorted({len(frame) for frame in frames}),
        "total_bytes": len(joined),
        "sha256": hashlib.sha256(joined).hexdigest(),
        "probes": probes,
    }


class GoldenBaselineTest(unittest.TestCase):
    """默认路径的字节级回归。"""

    @classmethod
    def setUpClass(cls):
        cls.actual = fingerprint()

    def test_baseline_file_exists(self):
        self.assertTrue(
            BASELINE_PATH.exists(),
            f"缺少基线文件 {BASELINE_PATH}。"
            f"首次生成：python -X utf8 -m tools.gen_golden_baseline",
        )

    def test_sha256_matches(self):
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            self.actual["sha256"], expected["sha256"],
            "默认路径的 200 帧字节变了！\n"
            "如果这是**有意**改动（例如改占位行为），用 tools.gen_golden_baseline "
            "更新基线并在提交信息里说明；否则说明改坏了实验基线。",
        )

    def test_payload_lengths_match(self):
        """每帧字节长度的集合必须一致 —— 长度一变，E9 的字节公式就失效。"""
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.actual["payload_len_unique"],
                         expected["payload_len_unique"])

    def test_total_bytes_match(self):
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.actual["total_bytes"], expected["total_bytes"])

    def test_probes_match(self):
        """count 字段与若干精确坐标逐项比对。"""
        expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(self.actual["probes"]), len(expected["probes"]))
        for got, want in zip(self.actual["probes"], expected["probes"]):
            with self.subTest(tick=want["tick"]):
                for key in ("level", "wave", "wave_state", "player_count",
                            "enemy_count", "bullet_count", "item_count",
                            "boss_present", "payload_len", "first_enemies"):
                    self.assertEqual(got[key], want[key], f"字段 {key} 漂移")

    def test_snapshot_size_formula(self):
        """字节数必须精确等于 `13 + 11P + 9E + 8B + 7I`（E9 的立论基础）。"""
        snapshot = unpack_snapshot(build_frames()[0][0])
        expected = (
            13
            + 11 * len(snapshot.players)
            + 9 * len(snapshot.enemies)
            + 8 * len(snapshot.bullets)
            + 7 * len(snapshot.items)
        )
        self.assertEqual(len(build_frames()[0][0]), expected)


def main() -> None:
    """生成/更新基线（由 tools/gen_golden_baseline.py 调用）。"""
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = fingerprint()
    BASELINE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f" 已写入 {BASELINE_PATH}")
    print(f"   SHA256 = {data['sha256']}")
    print(f"   每帧长度集合 = {data['payload_len_unique']}")
    print(f"   200 帧总字节 = {data['total_bytes']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--generate":
        main()
    else:
        unittest.main()