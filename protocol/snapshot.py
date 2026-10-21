"""S_SNAPSHOT 的最小实现：只同步玩家。

正式快照格式见 docs/02-协议设计.md §6.2。本阶段只实现“快照头 + 玩家条目”，
敌机 / 子弹 / 道具的计数固定为 0；等第 6 步以后再加。

快照头（13 B）：

    偏移  长度  字段
    0     4     tick          uint32
    4     1     level         uint8
    5     1     wave          uint8
    6     1     wave_state    uint8
    7     1     player_count  uint8
    8     1     enemy_count   uint8
    9     2     bullet_count  uint16
    11    1     item_count    uint8
    12    1     boss_present  uint8

玩家条目（11 B）：

    player_id uint16 | x uint16 | y uint16 | power uint8 | color uint8 | flags uint8 | score uint16
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from protocol.framing import ProtocolError

# !IBBBBBHBB = 4 + 5 + 2 + 2 = 13 B
SNAPSHOT_HEADER = struct.Struct("!IBBBBBHBB")

# !HHHBBBH = 2 + 2 + 2 + 1 + 1 + 1 + 2 = 11 B
PLAYER = struct.Struct("!HHHBBBH")

assert SNAPSHOT_HEADER.size == 13
assert PLAYER.size == 11


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
class Snapshot:
    tick: int
    level: int
    wave: int
    wave_state: int
    players: tuple[PlayerSnapshot, ...]


def pack_snapshot(tick: int, players: list[PlayerSnapshot]) -> bytes:
    """把快照头 + 玩家条目打包成 S_SNAPSHOT 的载荷。"""
    if len(players) > 0xFF:
        raise ProtocolError(f"玩家数超出 uint8：{len(players)}")
    header = SNAPSHOT_HEADER.pack(
        tick,
        1,  # level
        1,  # wave
        0,  # wave_state
        len(players),
        0,  # enemy_count
        0,  # bullet_count
        0,  # item_count
        0,  # boss_present
    )
    body = b"".join(
        PLAYER.pack(p.player_id, p.x, p.y, p.power, p.color, p.flags, p.score)
        for p in players
    )
    return header + body


def unpack_snapshot(payload: bytes) -> Snapshot:
    """解析 S_SNAPSHOT 载荷；本阶段只接受“只有玩家”的快照。"""
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

    if enemy_count or bullet_count or item_count or boss_present:
        raise ProtocolError("阶段 5 只支持玩家快照，敌机/子弹/道具计数必须为 0")

    expected = SNAPSHOT_HEADER.size + player_count * PLAYER.size
    if len(payload) != expected:
        raise ProtocolError(f"快照长度不匹配：{len(payload)} != {expected}")

    players = []
    offset = SNAPSHOT_HEADER.size
    for _ in range(player_count):
        players.append(PlayerSnapshot(*PLAYER.unpack_from(payload, offset)))
        offset += PLAYER.size

    return Snapshot(
        tick=tick,
        level=level,
        wave=wave,
        wave_state=wave_state,
        players=tuple(players),
    )
