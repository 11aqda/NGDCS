"""快照编码器：同一份世界状态，三种编码方式（E1 实验用）。

`03-实验清单.md §5 E1` 要对比「二进制协议 vs JSON」。但只比两种编码会混进一个
说不清的因素 —— **实现方式**。所以这里给三个变体，把两个因素分开：

| 名字 | 是什么 | 用来回答 |
|---|---|---|
| `binary` | 协议的标准编码（`protocol.snapshot.pack_snapshot`），逐条目 pack | 基线 |
| `binary_fast` | **同一个协议、逐字节相同的输出**，但整帧只调一次 `struct.pack` | **实现方式**能带来多少差异 |
| `json` | 短键名 JSON，另一套编码（**编解码双向都实现**） | **编码形式**能带来多少差异 |

`binary` 与 `binary_fast` 的产物**逐字节相同**（`tests/test_encoders.py` 有断言），
所以两者之间任何差异都只能归因于实现；而它们与 `json` 的差异才是**协议形式**的差异。

**为什么 `binary_fast` 会快**：`binary` 对每个实体单独调一次 `struct.pack`，
100 敌机 + 800 子弹就是 **1704 次** Python→C 的跨界调用 + 1704 个小 bytes 对象 + 一次 join。
`binary_fast` 把整帧拼成一个格式串（按实体数缓存 `struct.Struct`），一次调用搞定。

### JSON 是**公平实现**（答辩会被问，这里先写清楚）

对照组的实现方式直接决定结论可信度，所以把"公平"落成可检查的约定：

1. **字段与实体集合完全一致** —— 同一个 `Snapshot` 进去，三种编码装的是同一批数据，
   不多一个字段也不少一个（`tests/test_encoders.py` 用往返测试锁住）
2. **用标准库、不做人为劣化**：
   `json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`
   —— 去掉分隔空格、关掉 ASCII 转义，都是"认真写 JSON"该做的
3. **键名刻意取短**（`t` / `p` / `i` / `x`…）—— 拿一份字段名拼全的 JSON 来比是稻草人
4. **不做协议值域校验** —— JSON 本来就不需要（没有固定位宽），
   给它加校验反而是把二进制协议的约束强加给对照组
5. **不只是"能发"**：解码也实现了（`unpack_snapshot_json`），
   它是一条**完整可用**的协议路径，不是一次性的序列化函数

> ⚠️ **JSON 的 CPU 有可能反而更低** —— `json.dumps` 是 C 实现、一次调用；
> 而 `binary` 是 Python 层循环。所以「二进制更省 CPU」在 Python 实现下**不一定成立**。
> 这正是要加 `binary_fast` 变体的原因：把「协议优势」和「实现优势」分开说。
>
> 还能再压：条目改数组形式（`[1,100,200,0,3]`）体积约再降一半，
> 但那就不是"用 JSON"而是"用 JSON 语法手写二进制"了 —— 本实验不实现，只在记录里讨论量级。
"""

from __future__ import annotations

import json
import struct
from functools import lru_cache
from typing import Protocol as TypingProtocol

from protocol.messages import ENEMY_BOSS
from protocol.snapshot import (
    BULLET,
    ENEMY,
    ITEM,
    PLAYER,
    SNAPSHOT_HEADER,
    BulletSnapshot,
    EnemySnapshot,
    ItemSnapshot,
    PlayerSnapshot,
    Snapshot,
    _check_count,
    pack_snapshot,
)

# 各条目的 `struct` 格式（去掉 `!`，因为整帧只留一个 `!` 在最前面）。
# 从 Struct 对象里读出来，而不是再抄一遍 —— 这样协议改了这里自动跟着变。
_HEADER_FMT = SNAPSHOT_HEADER.format.lstrip("!")
_PLAYER_FMT = PLAYER.format.lstrip("!")
_ENEMY_FMT = ENEMY.format.lstrip("!")
_BULLET_FMT = BULLET.format.lstrip("!")
_ITEM_FMT = ITEM.format.lstrip("!")

ENCODER_NAMES = ("binary", "binary_fast", "json")


class SnapshotEncoder(TypingProtocol):
    """编码器接口：同一份世界状态 → 一帧 S_SNAPSHOT 的载荷。

    三个实现的**签名必须完全一致**（含默认值），否则 E1 的对比会混进
    "参数处理不一样"这种与编码无关的差异。
    """

    name: str

    def encode(
        self,
        tick: int,
        players: list[PlayerSnapshot],
        enemies: list[EnemySnapshot] | None = None,
        bullets: list[BulletSnapshot] | None = None,
        items: list[ItemSnapshot] | None = None,
        level: int = 1,
        wave: int = 1,
        wave_state: int = 0,
    ) -> bytes: ...


class BinaryEncoder:
    """协议的标准编码：逐条目 `struct.pack` 再拼接。"""

    name = "binary"

    def encode(
        self, tick, players, enemies=None, bullets=None, items=None,
        level=1, wave=1, wave_state=0,
    ):
        return pack_snapshot(
            tick, players, enemies, bullets, items, level, wave, wave_state
        )


@lru_cache(maxsize=64)
def _fast_struct(player_count: int, enemy_count: int, bullet_count: int, item_count: int):
    """按实体数组合缓存整帧的 `Struct`。

    **不缓存就等于没优化** —— 每 tick 重新编译一次格式串比逐条目 pack 还慢。
    组合数有限（同一次实验里实体数是稳定的），所以 cache 命中率接近 100%。
    """
    fmt = (
        "!"
        + _HEADER_FMT
        + _PLAYER_FMT * player_count
        + _ENEMY_FMT * enemy_count
        + _BULLET_FMT * bullet_count
        + _ITEM_FMT * item_count
    )
    return struct.Struct(fmt)


class FastBinaryEncoder:
    """**同一个协议、逐字节相同的输出**，但整帧只调一次 `struct.pack`。

    与 `BinaryEncoder` 的差异**只来自实现方式**：省掉了 1700 多次
    Python→C 跨界调用和同样多的小 bytes 对象。产物完全相同（有测试断言）。
    """

    name = "binary_fast"

    def encode(
        self, tick, players, enemies=None, bullets=None, items=None,
        level=1, wave=1, wave_state=0,
    ):
        enemies = enemies or []
        bullets = bullets or []
        items = items or []

        _check_count(len(players), 0xFF, "玩家")
        _check_count(len(enemies), 0xFF, "敌机")
        _check_count(len(bullets), 0xFFFF, "子弹")
        _check_count(len(items), 0xFF, "道具")

        boss_present = 1 if any(e.type == ENEMY_BOSS for e in enemies) else 0

        args: list = [
            tick,
            level,
            wave,
            wave_state,
            len(players),
            len(enemies),
            len(bullets),
            len(items),
            boss_present,
        ]
        for p in players:
            args += (p.player_id, p.x, p.y, p.power, p.color, p.flags, p.score)
        for e in enemies:
            args += (e.enemy_id, e.x, e.y, e.type, e.hp)
        for b in bullets:
            args += (b.owner_id, b.x, b.y, b.type, b.angle)
        for i in items:
            args += (i.item_id, i.x, i.y, i.type)

        layout = _fast_struct(len(players), len(enemies), len(bullets), len(items))
        return layout.pack(*args)


class JsonEncoder:
    """短键名 JSON —— 对照组。

    **条目用对象而不是数组**（`{"i":1,"x":100,...}` 而不是 `[1,100,...]`）：
    这是 JSON 该有的样子，可读、可调试、能直接扔给前端。
    想再压体积的话数组形式能再小约一半，但那就已经不是"用 JSON"了，
    而是"用 JSON 的语法手写二进制"—— 那种方案的意义在本实验里另有讨论。

    **不做协议的值域校验**：JSON 本来就不需要（没有固定位宽），
    给它加校验反而是把二进制协议的约束强加给对照组。
    """

    name = "json"

    def encode(
        self, tick, players, enemies=None, bullets=None, items=None,
        level=1, wave=1, wave_state=0,
    ):
        enemies = enemies or []
        bullets = bullets or []
        items = items or []

        boss_present = 1 if any(e.type == ENEMY_BOSS for e in enemies) else 0
        payload = {
            "t": tick,
            "l": level,
            "w": wave,
            "s": wave_state,
            "bp": boss_present,
            "p": [
                {
                    "i": p.player_id, "x": p.x, "y": p.y, "pw": p.power,
                    "c": p.color, "f": p.flags, "sc": p.score,
                }
                for p in players
            ],
            "e": [
                {"i": e.enemy_id, "x": e.x, "y": e.y, "ty": e.type, "h": e.hp}
                for e in enemies
            ],
            "b": [
                {"o": b.owner_id, "x": b.x, "y": b.y, "ty": b.type, "a": b.angle}
                for b in bullets
            ],
            "i": [
                {"i": i.item_id, "x": i.x, "y": i.y, "ty": i.type} for i in items
            ],
        }
        # separators 去掉空格、ensure_ascii 关掉转义 —— 都是"认真写 JSON"会做的
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


_ENCODERS: dict[str, type] = {
    "binary": BinaryEncoder,
    "binary_fast": FastBinaryEncoder,
    "json": JsonEncoder,
}


def get_encoder(name: str) -> SnapshotEncoder:
    """按名字取编码器。名字不认识就报错，**不要静默退回 binary** ——
    否则 `--encoder jsno` 这种手误会让实验白跑一轮且数据标错编码。"""
    try:
        return _ENCODERS[name]()
    except KeyError:
        raise ValueError(
            f"未知编码器 {name!r}；可选：{', '.join(ENCODER_NAMES)}"
        ) from None


def unpack_snapshot_json(payload: bytes) -> Snapshot:
    """JSON 快照的**解码** —— 与 `protocol.snapshot.unpack_snapshot` 对称。

    为什么对照组也要实现解码：**只实现编码的对照组不算一条协议路径**，
    充其量是个"把数据变丑"的函数。实现了双向之后，
    JSON 才是一个可以真的拿来跑游戏的完整替代方案，
    "它比二进制差多少"这个结论才有意义。

    顺带一个好处：往返测试（encode → decode → 与原对象相等）
    能锁住"JSON 装的字段与二进制完全一致"，这是 §「公平实现」第 1 条的可执行证据。
    """
    data = json.loads(payload.decode("utf-8"))
    return Snapshot(
        tick=data["t"],
        level=data["l"],
        wave=data["w"],
        wave_state=data["s"],
        players=tuple(
            PlayerSnapshot(
                player_id=p["i"], x=p["x"], y=p["y"], power=p["pw"],
                color=p["c"], flags=p["f"], score=p["sc"],
            )
            for p in data["p"]
        ),
        enemies=tuple(
            EnemySnapshot(enemy_id=e["i"], x=e["x"], y=e["y"], type=e["ty"], hp=e["h"])
            for e in data["e"]
        ),
        bullets=tuple(
            BulletSnapshot(
                owner_id=b["o"], x=b["x"], y=b["y"], type=b["ty"], angle=b["a"]
            )
            for b in data["b"]
        ),
        items=tuple(
            ItemSnapshot(item_id=i["i"], x=i["x"], y=i["y"], type=i["ty"])
            for i in data["i"]
        ),
        boss_present=bool(data["bp"]),
    )


# 想再压缩 JSON 的话（本实验不实现，只在实验记录里讨论量级）：
# 把条目从对象改成数组 `[1,100,200,0,3]`，省掉重复的键名，
# 体积大约能降到对象形式的一半 —— 但代价是自描述性，前后端都得靠位置约定去读。