"""S_SNAPSHOT 编解码：快照头 + 玩家 / 敌机 / 子弹 / 道具条目。

正式快照格式见 docs/02-协议设计.md §6.2，本模块是它的完整实现。

快照头（13 B）：

    偏移  长度  字段
    0     4     tick          uint32
    4     1     level         uint8
    5     1     wave          uint8
    6     1     wave_state    uint8
    7     1     player_count  uint8
    8     1     enemy_count   uint8   （含 BOSS）
    9     2     bullet_count  uint16
    11    1     item_count    uint8
    12    1     boss_present  uint8

条目（按 玩家 → 敌机 → 子弹 → 道具 的顺序紧密排列）：

    玩家（11 B）  player_id u16 | x u16 | y u16 | power u8 | color u8 | flags u8 | score u16
    敌机（ 9 B）  enemy_id  u16 | x u16 | y u16 | type  u8 | hp    u16
    子弹（ 8 B）  owner_id  u16 | x u16 | y u16 | type  u8 | angle u8
    道具（ 7 B）  item_id   u16 | x u16 | y u16 | type  u8

两个**容易踩的点**：

1. `boss_present` 不由调用方传，而是**从敌机列表里推导**（有 type == 0xFF 就是 1）。
   两个字段在协议里重复表达同一件事，推导可以保证它们永远不会互相矛盾。
2. **子弹条目没有唯一 ID**（只有 `owner_id`）。这是有意的：子弹生命周期只有几秒、
   数量上百，给每个子弹分配 2 字节 ID 不划算。代价是客户端**无法按实体逐帧匹配子弹**，
   所以子弹不能做实体插值（玩家和敌机可以，它们有 id）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from protocol.framing import ProtocolError
from protocol.messages import ENEMY_BOSS

# !IBBBBBHBB = 4 + 5 + 2 + 2 = 13 B
SNAPSHOT_HEADER = struct.Struct("!IBBBBBHBB")

# !HHHBBBH = 2 + 2 + 2 + 1 + 1 + 1 + 2 = 11 B
PLAYER = struct.Struct("!HHHBBBH")

# !HHHBH = 2 + 2 + 2 + 1 + 2 = 9 B
ENEMY = struct.Struct("!HHHBH")

# !HHHBB = 2 + 2 + 2 + 1 + 1 = 8 B
BULLET = struct.Struct("!HHHBB")

# !HHHB = 2 + 2 + 2 + 1 = 7 B
ITEM = struct.Struct("!HHHB")

assert SNAPSHOT_HEADER.size == 13
assert PLAYER.size == 11
assert ENEMY.size == 9
assert BULLET.size == 8
assert ITEM.size == 7


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    player_id: int
    x: int
    y: int
    power: int = 1
    color: int = 0
    flags: int = 1  # 1 = 在线
    score: int = 0


@dataclass(frozen=True, slots=True)
class EnemySnapshot:
    enemy_id: int
    x: int
    y: int
    type: int = 0x01
    hp: int = 1


@dataclass(frozen=True, slots=True)
class BulletSnapshot:
    owner_id: int  # 敌方子弹为 0
    x: int
    y: int
    type: int = 0x01
    angle: int = 0  # 0 指向正上方，顺时针（02 §4.5）


@dataclass(frozen=True, slots=True)
class ItemSnapshot:
    item_id: int
    x: int
    y: int
    type: int = 0x01


@dataclass(frozen=True, slots=True)
class Snapshot:
    tick: int
    level: int
    wave: int
    wave_state: int
    players: tuple[PlayerSnapshot, ...]
    enemies: tuple[EnemySnapshot, ...] = ()
    bullets: tuple[BulletSnapshot, ...] = ()
    items: tuple[ItemSnapshot, ...] = ()
    boss_present: bool = False

    @property
    def entity_count(self) -> int:
        """快照里的实体总数（E9 的横轴就是它）。"""
        return (
            len(self.players) + len(self.enemies) + len(self.bullets) + len(self.items)
        )


def _check_count(count: int, limit: int, name: str) -> None:
    if count > limit:
        raise ProtocolError(f"{name} 数量超出上限：{count} > {limit}")


def pack_snapshot(
    tick: int,
    players: list[PlayerSnapshot],
    enemies: list[EnemySnapshot] | None = None,
    bullets: list[BulletSnapshot] | None = None,
    items: list[ItemSnapshot] | None = None,
    level: int = 1,
    wave: int = 1,
    wave_state: int = 0,
) -> bytes:
    """把快照头 + 各类条目打包成 S_SNAPSHOT 的载荷。"""
    enemies = enemies or []
    bullets = bullets or []
    items = items or []

    _check_count(len(players), 0xFF, "玩家")
    _check_count(len(enemies), 0xFF, "敌机")
    _check_count(len(bullets), 0xFFFF, "子弹")
    _check_count(len(items), 0xFF, "道具")

    # 推导而不是传参：boss_present 和敌机的 0xFF 类型永远一致
    boss_present = 1 if any(e.type == ENEMY_BOSS for e in enemies) else 0

    header = SNAPSHOT_HEADER.pack(
        tick,
        level,
        wave,
        wave_state,
        len(players),
        len(enemies),
        len(bullets),
        len(items),
        boss_present,
    )
    body = b"".join(
        PLAYER.pack(p.player_id, p.x, p.y, p.power, p.color, p.flags, p.score)
        for p in players
    )
    body += b"".join(
        ENEMY.pack(e.enemy_id, e.x, e.y, e.type, e.hp) for e in enemies
    )
    body += b"".join(
        BULLET.pack(b.owner_id, b.x, b.y, b.type, b.angle) for b in bullets
    )
    body += b"".join(ITEM.pack(i.item_id, i.x, i.y, i.type) for i in items)
    return header + body


def _unpack_many(layout, factory, payload: bytes, offset: int, count: int):
    entries = []
    for _ in range(count):
        entries.append(factory(*layout.unpack_from(payload, offset)))
        offset += layout.size
    return tuple(entries), offset


def unpack_snapshot(payload: bytes) -> Snapshot:
    """解析 S_SNAPSHOT 载荷。

    长度必须**正好**等于「头 + 各计数 × 条目大小」——
    把尾巴上多出来的字节当成下一条消息，是粘包 bug 的经典来源。
    """
    if len(payload) < SNAPSHOT_HEADER.size:
        raise ProtocolError(f"快照太短：{len(payload)} B")

    (
        tick,
        level,
        wave,
        wave_state,
        player_count,
        enemy_count,
        bullet_count,
        item_count,
        boss_present,
    ) = SNAPSHOT_HEADER.unpack_from(payload, 0)

    expected = (
        SNAPSHOT_HEADER.size
        + player_count * PLAYER.size
        + enemy_count * ENEMY.size
        + bullet_count * BULLET.size
        + item_count * ITEM.size
    )
    if len(payload) != expected:
        raise ProtocolError(f"快照长度不匹配：{len(payload)} != {expected}")

    offset = SNAPSHOT_HEADER.size
    players, offset = _unpack_many(PLAYER, PlayerSnapshot, payload, offset, player_count)
    enemies, offset = _unpack_many(ENEMY, EnemySnapshot, payload, offset, enemy_count)
    bullets, offset = _unpack_many(BULLET, BulletSnapshot, payload, offset, bullet_count)
    items, offset = _unpack_many(ITEM, ItemSnapshot, payload, offset, item_count)

    return Snapshot(
        tick=tick,
        level=level,
        wave=wave,
        wave_state=wave_state,
        players=players,
        enemies=enemies,
        bullets=bullets,
        items=items,
        boss_present=bool(boss_present),
    )