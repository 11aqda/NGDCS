"""玩家运动学：纯函数，不碰 socket / asyncio，所以能直接单测。

服务端权威（D-006）：坐标**只由服务端算**，客户端上报的 keys 是「意图」，
不是坐标。所以快照里不回传 keys —— 客户端知道自己按了什么，回传纯属浪费。

为什么用「整数像素 / tick」而不是「浮点速度 × 时间」：

    1. 02 §4.3 已经禁用浮点（跨平台舍入可能不一致）
    2. **确定性** —— 同样的输入序列必然得到同样的坐标轨迹，实验可复现。
       浮点累加在不同机器上末位会有偏差，压测数据就没法逐帧对账了。

代价：15 px/tick 的粒度不支持「加速 30%」这种道具。真要做时改成
「定点 1/16 像素」即可，现在不需要（游戏内容排在最后，D-013）。
"""

from __future__ import annotations

from protocol.messages import KEY_LEFT, KEY_RIGHT, KEYS_MASK
from protocol.world import PLAYER_MARGIN, WORLD_WIDTH

# 15 px/tick × 20 tick/s = 300 px/s → 2.4 秒横穿 720 px 屏幕
PLAYER_SPEED_PER_TICK = 15

MIN_X = PLAYER_MARGIN
MAX_X = WORLD_WIDTH - PLAYER_MARGIN


def keys_to_dx(keys: int) -> int:
    """把按键位掩码翻译成这一 tick 的水平位移（像素）。

    - 只按左 → -15；只按右 → +15
    - **左右同时按 → 0（抵消不动）**：这是有意的，不是 bug。
      真实玩家可能同时按住 A 和 D，抵消是最符合直觉的结果。
    - 保留位（bit 2~7）先被 KEYS_MASK 掩掉，前向兼容（见 protocol/messages.py）
    """
    keys &= KEYS_MASK
    direction = (1 if keys & KEY_RIGHT else 0) - (1 if keys & KEY_LEFT else 0)
    return direction * PLAYER_SPEED_PER_TICK


def clamp_x(x: int) -> int:
    """把横坐标钳制在场地内，留 PLAYER_MARGIN 的余量。"""
    return max(MIN_X, min(MAX_X, x))


def apply_input(x: int, keys: int) -> int:
    """走一个 tick：先按输入位移，再钳制。"""
    return clamp_x(x + keys_to_dx(keys))