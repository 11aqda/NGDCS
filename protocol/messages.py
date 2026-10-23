"""消息类型与固定格式的载荷。

正式类型表见 docs/02-协议设计.md §5。已实现的正式类型：

    C_INPUT          = 0x06  输入位掩码（客户端只发意图，不发坐标，见 D-006）
    C_HEARTBEAT      = 0x07  心跳（client_time，毫秒）
    S_SNAPSHOT       = 0x84  20 Hz 全量快照（格式见 protocol/snapshot.py）
    S_HEARTBEAT_ACK  = 0x87  心跳响应（回显 client_time + 服务端时间）

阶段 1 的临时类型（0x7C / 0x7F 不在正式 C→S 0x0X / S→C 0x8X 区间内，避免冲突）：

    S_WELCOME = 0x7C  服务端分配 player_id / color（正式认证见 S_AUTH_OK 0x81）
    ECHO      = 0x7F  第 2~4 步的回声测试（保留）

分工约定：
    本模块**只做结构校验**（长度对不对、值域够不够），
    不判断「这个位有没有意义」——保留位由业务层用 KEYS_MASK 掩掉。
"""

import struct
import time

from protocol.framing import ProtocolError

ECHO = 0x7F
S_WELCOME = 0x7C
S_SNAPSHOT = 0x84

C_INPUT = 0x06
C_HEARTBEAT = 0x07
S_HEARTBEAT_ACK = 0x87

# S_WELCOME 载荷：player_id uint16 + color uint8
WELCOME = struct.Struct("!HB")

# C_INPUT 载荷：keys uint8（位掩码，见 02 §4.5）
INPUT = struct.Struct("!B")

# C_HEARTBEAT 载荷：client_time uint32（毫秒）
HEARTBEAT = struct.Struct("!I")

# S_HEARTBEAT_ACK 载荷：client_time uint32 + server_time uint32
HEARTBEAT_ACK = struct.Struct("!II")

# 输入位掩码（02 §4.5）：bit 0 左、bit 1 右，bit 2~7 保留。
# 业务层只认 KEYS_MASK 里的位，其余一律掩掉 —— 这样将来加「上下移动」（bit 2）时，
# 旧服务端不会因为不认识新位就断连接（前向兼容）。
KEY_LEFT = 0x01
KEY_RIGHT = 0x02
KEYS_MASK = KEY_LEFT | KEY_RIGHT

# 实体类型（02 §4.5）。这里只定义当前用到的值，完整表见文档。
ENEMY_DIVE = 0x01  # 直线俯冲（占位实体用的就是它）
ENEMY_BOSS = 0xFF  # BOSS —— 用来推导快照头的 boss_present 标志

BULLET_PLAYER_L1 = 0x01  # 玩家 Lv1 子弹
BULLET_ENEMY_SPREAD = 0x11  # 敌方直线散射弹

ITEM_POWER = 0x01  # 火力道具

# 角度基准（02 §4.5）：0° = 正上方，顺时针增加。
# 竖版飞机大战「向上」是主方向，所以 0 放在正上而不是数学习惯的正右。
ANGLE_UP = 0
ANGLE_RIGHT = 64
ANGLE_DOWN = 128
ANGLE_LEFT = 192

_TIME_MASK = 0xFFFFFFFF


def _require_size(payload: bytes, layout: struct.Struct, name: str) -> None:
    """载荷必须**正好**是这么多字节，多一字节少一字节都是协议错误。"""
    if len(payload) != layout.size:
        raise ProtocolError(
            f"{name} 载荷长度错误：{len(payload)} B != {layout.size} B"
        )


def now_ms() -> int:
    """单调时钟的毫秒时间戳，取低 32 位。

    为什么不用 time.time()：墙上时钟会被 NTP 回拨或跳变，一旦回拨，
    客户端算出来的 now - sent 就是负数，RTT 直接废掉。monotonic 只增不减。

    为什么取低 32 位：协议里的时间戳是 uint32。回绕周期约 49.7 天，
    一局游戏碰不到；而且 rtt_ms() 用无符号差值，连回绕也免疫。
    """
    return int(time.monotonic() * 1000) & _TIME_MASK


def rtt_ms(sent_ms: int, now: int | None = None) -> int:
    """用无符号差值算 RTT（毫秒），天然容忍 32 位回绕。

    例：sent=0xFFFFFFF0、now=0x00000010（已经绕过一圈）→ 32 ms，不是 -4294967264。

    注意 RTT 只需要「客户端自己的时钟」：服务端把 client_time **原样回显**，
    所以这个计算完全在客户端本地完成，不依赖两端时钟同步（钟差会污染 RTT）。
    """
    if now is None:
        now = now_ms()
    return (now - sent_ms) & _TIME_MASK


def pack_keys(keys: int) -> bytes:
    if not 0 <= keys <= 0xFF:
        raise ProtocolError(f"keys 超出 uint8：{keys}")
    return INPUT.pack(keys)


def unpack_keys(payload: bytes) -> int:
    """解析 C_INPUT 载荷，返回原始位掩码（**不掩保留位**）。"""
    _require_size(payload, INPUT, "C_INPUT")
    return INPUT.unpack(payload)[0]


def pack_heartbeat(client_time: int) -> bytes:
    if not 0 <= client_time <= _TIME_MASK:
        raise ProtocolError(f"client_time 超出 uint32：{client_time}")
    return HEARTBEAT.pack(client_time)


def unpack_heartbeat(payload: bytes) -> int:
    """解析 C_HEARTBEAT 载荷，返回 client_time。"""
    _require_size(payload, HEARTBEAT, "C_HEARTBEAT")
    return HEARTBEAT.unpack(payload)[0]


def pack_heartbeat_ack(client_time: int, server_time: int) -> bytes:
    for name, value in (("client_time", client_time), ("server_time", server_time)):
        if not 0 <= value <= _TIME_MASK:
            raise ProtocolError(f"{name} 超出 uint32：{value}")
    return HEARTBEAT_ACK.pack(client_time, server_time)


def unpack_heartbeat_ack(payload: bytes) -> tuple[int, int]:
    """解析 S_HEARTBEAT_ACK 载荷，返回 (client_time, server_time)。"""
    _require_size(payload, HEARTBEAT_ACK, "S_HEARTBEAT_ACK")
    return HEARTBEAT_ACK.unpack(payload)