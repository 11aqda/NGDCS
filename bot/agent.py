"""单个机器人：连接 →（可选）发输入 / 发心跳 → 收快照，统计指标。

7a 的机器人只有一个协程，阻塞在 recv 上就够了（它什么都不发）。
7b 要同时**发**（输入 20 Hz + 心跳 5 s）和**收**，单协程做不到 ——
recv 一阻塞，发送就停。所以拆成三个协程，各管一件事：

    _recv_loop        收快照 / 心跳 ack，记到达间隔
    _input_loop       每 1/input_hz 秒发一次 C_INPUT
    _heartbeat_loop   每 heartbeat 秒发一次 C_HEARTBEAT

asyncio 是单线程：StreamWriter.write() 是同步追加到缓冲区，两个协程同时发
**不会撕裂帧**，drain() 只是背压等待。这一点在 7a 的观察者上看不到。

三个协程都自己把异常收进 result.errors，不往外抛 —— 否则 TaskGroup 会
取消同组的其他协程，一个机器人出错会连带把它的统计也清掉。
"""

from __future__ import annotations

import asyncio
import itertools
import random
import time
from dataclasses import dataclass, field, replace

from protocol.framing import HEADER, ProtocolError, recv_frame_async, send_frame_async
from protocol.interp import PlayerInterp
from protocol.messages import (
    C_HEARTBEAT,
    C_INPUT,
    KEY_FIRE,
    KEY_LEFT,
    KEY_RIGHT,
    S_HEARTBEAT_ACK,
    S_SNAPSHOT,
    S_WELCOME,
    now_ms,
    pack_heartbeat,
    pack_keys,
    rtt_ms,
    unpack_heartbeat_ack,
    WELCOME,
)
from protocol.snapshot import unpack_snapshot


@dataclass(frozen=True)
class BotConfig:
    host: str = "127.0.0.1"
    port: int = 9527
    duration: float = 10.0
    input_hz: float = 20.0  # 0 = 观察者（不发输入）
    heartbeat: float = 5.0  # 0 = 不发心跳（配合服务端 --timeout 0 做纯广播基线）
    key_hold: float = 0.5  # 一个按键按住多久才换
    hold_fire: bool = False  # 试玩用：一直按住开火（步骤 11 的 --game-mode）
    seed: int = 0  # 0 = 系统随机；非 0 = 可复现（第 i 个机器人用 seed+i）

    # ---- 插值误差（err_px）采集：E4 / 图 6-8~6-10、6-12 ----
    # **默认关**。它要给每一帧快照做 unpack_snapshot，那和客户端渲染是同样的开销；
    # E2/E9 的基线都是"机器人只数帧不解析"下测的，默认打开会悄悄改变那些数据。
    measure_err_px: bool = False
    # **客户端侧丢包模拟**：按概率把收到的快照"当没收到"。
    # 用途只有一个 —— 在没有 netem 的机器上验证 err_px 这把尺子是准的
    # （无丢包应为 0 增长、丢包应单调上升）。**不能替代 E4 的真实链路**。
    sim_loss: float = 0.0


@dataclass
class BotResult:
    connected: bool = False
    snapshots: int = 0
    bytes: int = 0  # 收到的总字节数（含快照和心跳回包）
    intervals: list[float] = field(default_factory=list)  # 快照到达间隔（秒）
    inputs_sent: int = 0
    heartbeats_sent: int = 0
    heartbeats_acked: int = 0
    rtts: list[float] = field(default_factory=list)  # 心跳 RTT（秒）
    errors: list[str] = field(default_factory=list)
    # err_px：各机器人**自己**那一帧的插值误差（像素）。空列表 = 没开采集
    err_track: PlayerInterp = field(default_factory=PlayerInterp)


def _random_keys(rng: random.Random) -> int:
    """随机挑一组按键（左 / 右 / 松手）。

    真实玩家不会每 50 ms 换一次键 —— 按住几百毫秒才是常态。所以按键状态
    每 key_hold 秒才换一次，期间**重复发送同一个 keys**：这正好演示了
    定频发送的冗余性（丢一帧，下一帧自动补上同样的状态）。
    """
    keys = rng.choice((0, KEY_LEFT, KEY_RIGHT))
    return keys


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """睡 seconds；期间被通知「连接坏了」就立刻醒。返回 True 表示该收工了。"""
    if seconds <= 0:
        return stop.is_set()
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False


async def _recv_loop(
    reader: asyncio.StreamReader,
    result: BotResult,
    config: BotConfig,
    my_id: int,
    rng: random.Random,
    deadline: float,
    stop: asyncio.Event,
) -> None:
    last_snapshot_at: float | None = None

    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break

        try:
            frame = await asyncio.wait_for(recv_frame_async(reader), timeout=remaining)
        except TimeoutError:
            break
        except ProtocolError as exc:
            result.errors.append(str(exc))
            stop.set()
            break

        if frame is None:
            result.errors.append("server closed")
            stop.set()
            break

        now = time.perf_counter()
        result.bytes += HEADER.size + len(frame.payload)

        if frame.msg_type == S_SNAPSHOT:
            if last_snapshot_at is not None:
                result.intervals.append(now - last_snapshot_at)
            last_snapshot_at = now
            result.snapshots += 1

            # ---- err_px 采集（默认关，见 BotConfig 的说明）----
            if config.measure_err_px:
                # 客户端侧丢包模拟：决定**这一帧要不要喂给插值器**。
                # 只是不喂，帧本身照收 —— 不改变网络行为、不影响服务端。
                if config.sim_loss <= 0.0 or rng.random() >= config.sim_loss:
                    try:
                        snapshot = unpack_snapshot(frame.payload)
                    except ProtocolError as exc:
                        result.errors.append(f"snapshot: {exc}")
                        continue
                    # 只跟踪**自己**：这是玩家真正看到的那一帧。跟踪全部玩家会让
                    # 样本数 ×N，但误差在玩家间高度相关，对"显示偏差"没有额外信息。
                    for player in snapshot.players:
                        if player.player_id == my_id:
                            result.err_track.ingest(now, (player.x, player.y))
                            break

        elif frame.msg_type == S_HEARTBEAT_ACK:
            # 心跳是我们**发**的，但 RTT 只能靠**收到**的回包算，
            # 所以这段逻辑在接收路径上，不在心跳协程里
            try:
                client_time, _server_time = unpack_heartbeat_ack(frame.payload)
            except ProtocolError as exc:
                result.errors.append(str(exc))
                continue
            result.heartbeats_acked += 1
            result.rtts.append(rtt_ms(client_time) / 1000.0)


async def _input_loop(
    writer: asyncio.StreamWriter,
    result: BotResult,
    config: BotConfig,
    rng: random.Random,
    deadline: float,
    stop: asyncio.Event,
    seq: itertools.count,
) -> None:
    interval = 1.0 / config.input_hz
    next_send = time.perf_counter()
    next_key_change = next_send + config.key_hold
    keys = _random_keys(rng)

    while True:
        now = time.perf_counter()
        if now >= deadline:
            break
        if now >= next_key_change:
            keys = _random_keys(rng)
        if config.hold_fire:
            keys |= KEY_FIRE  # 一直按住开火（试玩 --game-mode 用）
            next_key_change = now + config.key_hold

        try:
            await send_frame_async(writer, C_INPUT, next(seq), pack_keys(keys))
        except (ConnectionError, RuntimeError) as exc:
            result.errors.append(repr(exc))
            stop.set()
            break

        result.inputs_sent += 1
        next_send += interval
        if await _sleep_or_stop(stop, next_send - time.perf_counter()):
            break


async def _heartbeat_loop(
    writer: asyncio.StreamWriter,
    result: BotResult,
    config: BotConfig,
    deadline: float,
    stop: asyncio.Event,
    seq: itertools.count,
) -> None:
    interval = config.heartbeat
    next_send = time.perf_counter()  # 立刻发第一拍：让服务端早点知道我们活着

    while True:
        if time.perf_counter() >= deadline:
            break

        try:
            await send_frame_async(
                writer, C_HEARTBEAT, next(seq), pack_heartbeat(now_ms())
            )
        except (ConnectionError, RuntimeError) as exc:
            result.errors.append(repr(exc))
            stop.set()
            break

        result.heartbeats_sent += 1
        next_send += interval
        if await _sleep_or_stop(stop, next_send - time.perf_counter()):
            break


async def run_bot(config: BotConfig) -> BotResult:
    """一个机器人：连上 → 收发 → 到点收工。异常都记在 result.errors 里。"""
    result = BotResult()
    deadline = time.perf_counter() + config.duration

    try:
        reader, writer = await asyncio.open_connection(config.host, config.port)
    except OSError as exc:
        result.errors.append(repr(exc))
        return result

    result.connected = True

    try:
        welcome = await recv_frame_async(reader)
        if welcome is None or welcome.msg_type != S_WELCOME:
            result.errors.append("no S_WELCOME")
            return result
        # S_WELCOME 载荷：player_id uint16 + color uint8（err_px 要跟踪"自己"）
        my_id = WELCOME.unpack(welcome.payload)[0]

        # seq 是「发送方递增序号」（见 protocol/framing.py）。输入和心跳
        # **共用**一个计数器，否则两条流各自从 1 开始，服务端会看到重复的 seq。
        seq = itertools.count(1)
        stop = asyncio.Event()

        async with asyncio.TaskGroup() as tg:
            # 丢包模拟要用独立的随机源：不能和按键选择共用，
            # 否则"按键更随机"会顺带改变丢包模式，两个变量就纠缠在一起了
            tg.create_task(
                _recv_loop(
                    reader, result, config, my_id,
                    random.Random((config.seed or 0) + 7_777), deadline, stop,
                )
            )
            if config.input_hz > 0:
                rng = random.Random(config.seed) if config.seed else random.Random()
                tg.create_task(
                    _input_loop(writer, result, config, rng, deadline, stop, seq)
                )
            if config.heartbeat > 0:
                tg.create_task(
                    _heartbeat_loop(writer, result, config, deadline, stop, seq)
                )
    except ProtocolError as exc:
        result.errors.append(str(exc))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass

    return result


async def run_farm(
    config: BotConfig, clients: int, ramp: float
) -> list[BotResult]:
    """按 ramp 速率启动 N 个机器人，等它们全部结束。

    每个机器人分到不同的种子（seed+i）：这样「固定 --seed 结果可复现」
    和「不同机器人的按键不一样」可以同时成立。
    """
    tasks = []
    for index in range(clients):
        bot_config = replace(config, seed=config.seed + index) if config.seed else config
        tasks.append(asyncio.create_task(run_bot(bot_config)))
        if ramp > 0:
            await asyncio.sleep(1.0 / ramp)
    return list(await asyncio.gather(*tasks))