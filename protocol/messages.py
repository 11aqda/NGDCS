"""消息类型与固定格式的载荷。

正式类型表见 docs/02-协议设计.md §5。
阶段 1 只实现最小闭环，所以有两个临时类型：

    S_WELCOME  = 0x7C  服务端分配 player_id / color（临时，正式认证见 0x81）
    ECHO       = 0x7F  第 2~4 步的回声测试（保留）
    S_SNAPSHOT = 0x84  正式快照类型（本阶段只带玩家，敌机/子弹/道具计数为 0）

0x7C / 0x7F 不在正式的 C→S（0x0X）/ S→C（0x8X）区间内，避免和 C_AUTH(0x01)
等正式类型冲突。
"""

import struct

ECHO = 0x7F
S_WELCOME = 0x7C
S_SNAPSHOT = 0x84

# S_WELCOME 载荷：player_id uint16 + color uint8
WELCOME = struct.Struct("!HB")
