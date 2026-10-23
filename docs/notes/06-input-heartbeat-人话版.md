# 第 7 步 7b · 输入 + 心跳（人话版）

> 对应代码：[protocol/messages.py](../../protocol/messages.py)（编解码）、
> [server/main.py](../../server/main.py)（输入 / 心跳 / 超时）、
> [server/movement.py](../../server/movement.py)（运动学）、
> [server/stats.py](../../server/stats.py)（tick 耗时）、
> [bot/agent.py](../../bot/agent.py)（机器人）、
> [client/main.py](../../client/main.py)（键盘）、[client/net.py](../../client/net.py)（发送队列）
>
> 对应测试：`tests/test_input.py`（12）、`tests/test_heartbeat.py`（14）、
> `tests/test_movement.py`（11）、`tests/test_tick_stats.py`（7）
>
> 日期：2026-10-23

---

## 0. 一句话

7a 之前，服务端是**一个人在自言自语**：它只管广播快照，客户端说什么它都不听
（`server/main.py` 里那个收包循环，收到什么都直接丢掉，只用来发现"对方挂了"）。

7b 把**客户端 → 服务端**这条路接通了：客户端终于能"抬手"（输入）和"报平安"（心跳），
服务端也终于要**回话**了。

---

## 1. 这一步解决什么问题？

### 1.1 输入：从「服务端自己晃」到「玩家说了算」

7a 时方块的左右移动是服务端用 `sin()` 算出来的 —— 那是**占位动画**，
不是任何人的操作。7b 之后：

```text
你按 ←  →  客户端发 C_INPUT(keys=0b01)  →  服务端按 keys 移动你  →  广播新坐标  →  你看到自己动了
```

**注意这条链有三个"没想到"的地方**，也是答辩的加分点：

1. **客户端不发坐标，只发"我按了什么"**（D-006）。这样客户端再怎么改程序，
   也没法把自己瞬移到屏幕中间。
2. **你看到的不是"你按下去"的瞬间**，而是"按下去 → 告诉服务端 → 服务端算 → 广播回来"
   这一整圈之后的结果。所以按下去到画面动，中间隔着一个 RTT + 最多一帧。
3. **服务端会忘记你的按键**。超过 0.5 秒没收到新输入，就当成你松手了 ——
   不然你拔网线之前正好按着"左"，角色会一直往左走，看起来像闹鬼。

### 1.2 心跳：确认"你还在"，顺便量出 RTT

TCP 本身知道连接通不通（拔网线会报错），但它的问题是：
**如果对方只是卡住了（没崩、没拔线、就是没响应），TCP 能傻等十几分钟。**

所以应用层要自己规定：「每 5 秒说一句'在'，15 秒没动静就当断线。」
这就是心跳。同时它顺手干了第二件事 —— **量 RTT**：

```text
客户端：C_HEARTBEAT(client_time=12345678)     ← 把我这边的计时器读数带上
服务端：S_HEARTBEAT_ACK(client_time=12345678) ← 原样抄回去
客户端：现在读数 12345681，差值 3 → RTT = 3 ms
```

**关键设计**：服务端把 `client_time` **原样抄回**，不做任何加工。
这样 RTT 完全由客户端本地算出来，**两台机器的钟快几秒慢几秒都无所谓**。
（如果改成"发我的时间、发你的时间再相减"，那两端的钟必须先对表，钟差会直接算进 RTT 里。）

---

## 2. 7b 的数据流

```text
                        ┌──────────────────────────────┐
   每 50 ms  ──C_INPUT─►│ dispatch()  只记 keys         │
   每 5  s   ──C_HB────►│ dispatch()  回 S_HB_ACK      │
                        │                              │
                        │ update_players()  按 keys 走 │  每 50 ms
                        │ build_snapshot()             │◄──────────┐
                        └──────────────┬───────────────┘           │
                                       │ S_SNAPSHOT（全量）        │
                        ┌──────────────▼───────────────┐           │
                        │ 所有客户端                    │───────────┘
                        └──────────────────────────────┘

   每 20 个 tick（约 1 秒）：
        reap_timeouts()   15 秒没收到任何消息 → 关掉
        print_stats()     tick 耗时 + 每秒收到多少条输入
```

---

## 3. 核心代码逐行讲

> 🔴 = **必须懂的最小集合**（这几个懂了，7b 就懂了）
> ⚪ = 可以先跳过

### 3.1 🔴 载荷只有 1 字节

```python
INPUT = struct.Struct("!B")          # C_INPUT：keys 位掩码
HEARTBEAT = struct.Struct("!I")      # C_HEARTBEAT：client_time（毫秒）
HEARTBEAT_ACK = struct.Struct("!II") # S_HEARTBEAT_ACK：client_time + server_time
```

`!` = 大端（网络字节序），`B` = 1 字节无符号，`I` = 4 字节无符号。

位掩码（`02-协议设计.md §4.5`）：

| 位 | 含义 |
|---|---|
| 0 | 左（A / ←） |
| 1 | 右（D / →） |
| 2~7 | 保留 |

所以 `keys = 0b01` 是往左、`0b10` 往右、`0b11` 是**同时按住**。

> **帧头开销**：C_INPUT 整帧 = 12 字节帧头 + 1 字节载荷 = 13 字节。
> 帧头是载荷的 12 倍 —— 这正是 `02 §4.1` 说的"小包开销占比高"，
> 也是后面"批量合并发送"优化项的动机。

### 3.2 🔴 服务端收到消息后做什么：`dispatch`

```python
async def dispatch(self, client, frame):
    if frame.msg_type == C_INPUT:
        client.keys = unpack_keys(frame.payload)      # 只记「按了什么」
        client.last_input_at = time.perf_counter()    # 记时间，给保质期用
        if self.stats is not None:
            self.stats.record_input()

    elif frame.msg_type == C_HEARTBEAT:
        client_time = unpack_heartbeat(frame.payload)
        payload = pack_heartbeat_ack(client_time, now_ms())
        await send_frame_async(client.writer, S_HEARTBEAT_ACK, frame.seq, payload)
```

三件事值得注意：

1. **收到的是"意图"，不是"结果"** —— 存 `keys`，不存 `x`。
2. **心跳的 `seq` 回带请求的 `seq`** —— 这叫"请求-响应关联"（`02 §4.2`）。
   客户端一看帧头 seq 就知道"这是回我的第 7 次心跳"。
3. **不认识的类型直接忽略**，不报错 —— 将来加新消息时，旧服务端不会因此崩掉。

### 3.3 🔴 输入的「保质期」：`active_keys`

```python
def active_keys(self, client, now):
    if now - client.last_input_at > self.input_ttl:   # 默认 0.5 秒
        return 0        # 太久没收到新输入 = 松手
    return client.keys
```

**为什么需要它**：定频发送的意思是"我按住什么就反复告诉你什么"。
但如果客户端突然卡了/断网了，服务端手里还攥着最后那条"按住左"，
角色就会一直往左走 —— 用户看到的是"我没按啊，它怎么自己在动"。

加上保质期之后，**输入变成有有效期的意图**，而不是一个永久状态。

### 3.4 🔴 怎么移动：`server/movement.py`

```python
def keys_to_dx(keys):
    keys &= KEYS_MASK                     # 只认 bit 0/1，保留位掩掉
    direction = (1 if keys & KEY_RIGHT else 0) - (1 if keys & KEY_LEFT else 0)
    return direction * PLAYER_SPEED_PER_TICK   # 15 像素 / tick

def apply_input(x, keys):
    return clamp_x(x + keys_to_dx(keys))  # 先走一步，再夹在场地内
```

- **15 像素/tick × 20 tick/s = 300 像素/秒** → 2.4 秒横穿 720 像素屏幕。
- **左右同时按 = 抵消不动**（`direction` 算出来是 0）。这是**故意的**，不是 bug：
  真实玩家真的会同时按 A 和 D。
- **保留位先掩掉**：`keys &= 0b11`。这样将来加"上下移动"（bit 2）时，
  旧服务端就算不认识这一位，也只是"当没看见"，不会直接断连。
- **边界夹住**：`clamp_x` 把坐标限制在 `[20, 700]`，留 20 像素余量 ——
  因为方块是**按中心点**画的，不夹的话走到边上会有一半飘出屏幕。

> **为什么用整数像素 / tick，不用"速度 × 时间"这种浮点写法？**
> 两个原因：① `02 §4.3` 已经规定协议里禁用浮点；② **确定性** ——
> 同样的输入序列，两台机器上跑出来的轨迹**一模一样**，实验才能逐帧对账。
> 浮点累加的末位误差会让"复现实验"变成玄学。

### 3.5 🔴 心跳的时间怎么算：`now_ms` / `rtt_ms`

```python
def now_ms():
    return int(time.monotonic() * 1000) & 0xFFFFFFFF

def rtt_ms(sent_ms, now=None):
    if now is None:
        now = now_ms()
    return (now - sent_ms) & 0xFFFFFFFF
```

- **用 `monotonic()` 不用 `time.time()`**：墙上时钟会被 NTP 回拨。
  一旦回拨，`now - sent` 就是负数，RTT 直接废掉。`monotonic` 只增不减。
- **取低 32 位**：协议里的时间戳是 `uint32`。回绕周期约 49.7 天，一局游戏碰不到。
- **`& 0xFFFFFFFF` 的作用**：就算真回绕了，无符号差值也是对的。
  例：`sent = 0xFFFFFFF0`、`now = 0x00000010`（已经绕过一圈）→
  `(0x10 - 0xFFFFFFF0) & 0xFFFFFFFF = 32` 毫秒。一行掩码买永久免疫。

### 3.6 🔴 超时判定：只判定，不关闭

```python
def check_timeouts(self, now):
    if self.timeout <= 0:
        return []                       # --timeout 0：关掉判定
    return [c for c in self.clients.values()
            if now - c.last_recv_at > self.timeout]
```

这个函数**只回答问题，不动手**。真正关连接在 `tick_loop` 里，真正的清理在
`handle_client` 的 `finally` 里。

**为什么要拆成三段？** 两个理由：

1. **可测**：测试塞一个假的 `now` 进去就能验 15 秒超时，不用真的等 15 秒。
2. **避免两处清理打架**：如果超时逻辑自己去删 `self.clients`，
   而客户的 `finally` 也在删，就会变成"两处都改同一个字典"——删两次、或者删错人。

**唯一的清理点**是这条规矩的名字。收到消息时只更新 `last_recv_at`：

```python
client.last_recv_at = time.perf_counter()   # 任何消息都算「还活着」，不只是心跳
```

### 3.7 🔴 客户端：非阻塞 socket 上怎么"发"

非阻塞 socket 的 `send()` **不保证全发出去**：可能只写进去一部分，
也可能一个字节都写不进去（抛 `BlockingIOError`）。所以不能直接发：

```python
def send(self, msg_type, payload):
    frame = pack_frame(msg_type, self.seq + 1, payload)
    if len(self.outbox) + len(frame) > MAX_OUTBOX:   # 64 KiB 上限
        self.dropped_frames += 1
        return None                                   # 宁可丢一条输入，也不把内存吃光
    self.seq += 1
    self.outbox.extend(frame)                         # 只排队，不发
    return self.seq

def flush(self):                                      # 每帧 poll() 时调一次
    while self.outbox:
        try:
            written = self.sock.send(self.outbox)
        except BlockingIOError:
            return                                    # 内核缓冲区满了，下一帧再来
        del self.outbox[:written]
```

**这就是 D-007 早就点名的代价**：非阻塞省掉了卡顿，但发送要自己写队列。

### 3.8 🔴 定频发送：20 Hz

```python
if net.connected and now >= next_input_at:
    net.send(C_INPUT, pack_keys(keys))
    inputs_sent += 1
    next_input_at += INPUT_INTERVAL      # 注意是 +=，不是 = now + 间隔
```

**为什么定频发，而不是"按键变了才发"？**

| 方案 | 问题 |
|---|---|
| **每次按键变化发一次** | 万一"松开"那条消息没送到，服务端以为你还按着 → 角色一直走 |
| **每帧发（60 Hz）** | 服务端只用 20 Hz 算移动，多出来的 2/3 是白发的 |
| ✅ **定频 20 Hz** | 内容永远是"我现在按住什么"，**丢一帧下一帧自动补上**，不需要重传 |

> `next_input_at += INPUT_INTERVAL` 而不是 `= now + INPUT_INTERVAL`：
> 后者会把上报频率**量化到帧率**上。60 fps 下每帧 16.7 ms，
> 而 50 ms 不是 16.7 的整数倍，实测只有 **17 次/秒**；
> 改成累加之后实测稳定在 **20 次/秒**。这和服务端 `tick_loop` 用的是同一个模式。

### 3.9 🔴 机器人：为什么必须拆成三个协程

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(_recv_loop(...))       # 收快照 / 心跳回包
    tg.create_task(_input_loop(...))      # 每 50 ms 发输入
    tg.create_task(_heartbeat_loop(...))  # 每 5 s 发心跳
```

7a 的机器人只有一个协程，因为它**什么都不发**，阻塞在 `recv` 上没关系。
7b 不行了：`recv` 一阻塞，发送就停了，20 Hz 的输入会变成"想起来才发一次"。

**asyncio 是单线程，两个协程同时 `write()` 会不会把帧撕成两半？**
不会。`StreamWriter.write()` 是**同步**地把整帧追加进缓冲区，中间不会被打断；
`await drain()` 只是等缓冲区排空。

**为什么每个协程自己吞异常？** `TaskGroup` 里任何一个任务抛异常，
会**取消同组的其他任务** —— 一个机器人出错，连它的统计一起清掉，
数据就少了一份，还看不出为什么。

---

## 4. 防御性代码（单独看）

| 代码 | 防的是什么 |
|---|---|
| `_require_size(payload, layout, name)` | 帧头 length 对了，不代表**载荷长度**对。C_INPUT 多一个字节就是协议错误 |
| `pack_keys` 检查 `0 <= keys <= 0xFF` | 值域溢出，和 D-012 那个 `struct.error` 是同一类问题 |
| `keys &= KEYS_MASK` | 保留位乱入导致行为异常；同时保证将来加新位时旧服务端不崩 |
| `INPUT_TTL = 0.5` | 客户端卡死/断网后角色"幽灵移动" |
| `timeout <= 0` 时不判定 | 做"纯广播"基线实验时，客户端不发心跳也不会被踢 |
| `check_timeouts` 只判定不关闭 | 清理逻辑只写一遍，避免两处改同一个字典 |
| `MAX_OUTBOX = 64 KiB` | 服务端不读时发送队列无限增长，把内存吃光 |
| `writer.close()` 包在 `try/except ConnectionError` | 对方已经断了再 close 会抛异常，属于常态 |
| `except (ConnectionError, RuntimeError)` | 客户端强退是**常态**，不是服务器错误，不该刷屏 |
| `_sleep_or_stop()` | 连接坏了要**立刻**停发，不能傻等 50 ms；否则每个协程都往死连接里写 |
| `keys` 超时归零而不是删除 | 保留"最后一次意图"，恢复发送后立刻生效 |

---

## 5. 可以跳过的语法（放心跳）

1. ⚪ `asyncio.TaskGroup` —— 3.11+ 的"任务组"，等价于手动 gather + 出错取消。
   知道它"等三个协程一起结束"就够。
2. ⚪ `itertools.count(1)` —— 无限递增计数器，给输入和心跳**共用**一个 seq。
   （共用是必须的：两条流各自从 1 开始的话，服务端会看到重复 seq。）
3. ⚪ `@dataclass(frozen=True)` 的 `BotConfig` + `dataclasses.replace` ——
   给每个机器人发一个不同的随机种子。
4. ⚪ `random.Random(seed)` —— 独立随机数发生器，不污染全局随机状态。
5. ⚪ `argparse` 的 `nargs="?"` —— 让 `python -m server.main 9527` 和
   `python -m server.main --timeout 5` 两种写法都能用。
6. ⚪ `contextlib.suppress(asyncio.CancelledError)` —— 取消协程时不打印堆栈。

**不要跳过的**：`struct.Struct("!B")`、位掩码、`dispatch` 的分发、
`active_keys` 的保质期、`rtt_ms` 的无符号差值、`send`/`flush` 的队列、
"三个协程"这个结构本身。

---

## 6. 自测题（6 道）

### Q1. 为什么客户端只发按键、不发坐标？

<details>
<summary>答案</summary>

因为坐标是"结果"。如果客户端能直接说自己在哪里，那改一行代码就能瞬移、穿墙、
伪造战绩，服务端完全没法验证。只发"我按了什么"，由服务端统一算坐标，
就保证了单一权威（D-006）。代价是客户端要等一个往返才看到自己动
（局域网 RTT < 1 ms，感觉不到；这正是 D-006 判断"不做客户端预测也不会滞后"的依据）。

</details>

---

### Q2. 输入为什么要设 0.5 秒的保质期？去掉会怎样？

<details>
<summary>答案</summary>

定频发送发的是"当前状态"。如果客户端突然卡住或断网，服务端手里还留着
最后一条"按住左"，角色会一直往左走到 15 秒超时被踢 —— 看起来像闹鬼。
保质期让"输入"变成**有有效期的意图**：0.5 秒没新消息就当松手。
去掉它不会崩，但会有这个可复现的怪现象。

</details>

---

### Q3. 心跳为什么要"原样回显" client_time，而不是各发各的时间戳？

<details>
<summary>答案</summary>

原样回显时，RTT 完全在客户端本地算：`现在读数 - 我发出去的读数`。
不需要两台机器的钟一致。如果改成"服务端发自己的时间，客户端拿本地时间相减"，
那两端的钟差（可能几秒甚至几分钟）会直接算进 RTT，测出来的数就完全不可信了。

</details>

---

### Q4. `rtt_ms` 里的 `& 0xFFFFFFFF` 是干嘛的？

<details>
<summary>答案</summary>

时间戳是 32 位，约 49.7 天回绕一次。回绕后 `now - sent` 会是个很大的负数，
按无符号解释才正确。`& 0xFFFFFFFF` 就是取无符号低 32 位：
`sent = 0xFFFFFFF0`、`now = 0x00000010` 时结果是 32 毫秒，而不是 -4294967264。
一局游戏碰不到回绕，但一行代码就能永久免疫。

</details>

---

### Q5. 超时为什么是"每秒检查一次"，不是每个 tick 都检查？

<details>
<summary>答案</summary>

tick 是 20 Hz。每 tick 遍历一遍所有客户端，就是每秒做 20 次同样的判断，
而超时精度只差 50 ms 毫秒级完全无所谓。这个项目里 tick 预算是 50 ms，
省下的时间要留给游戏逻辑。**低频的检查用低频的节奏**。

</details>

---

### Q6. 为什么机器人要拆成三个协程，一个协程里"收一下、发一下"不行吗？

<details>
<summary>答案</summary>

不行。`recv` 会一直挂起协程直到有数据来；如果发送逻辑写在收包循环里，
那"没收到东西"的时候就不会发输入，20 Hz 会变成"有快照才发一次"。
必须让"收"和"发"各自独立推进，所以拆成三个协程。
（7a 能用一个协程，是因为它只收不发。）

</details>

---

## 7. 答辩话术（可直接背）

> 这一步把客户端到服务端的上行链路接通了。输入用 `C_INPUT`，载荷只有 1 字节的
> 位掩码，客户端**只上报按键意图、不上报坐标**，坐标由服务端权威计算，
> 这样客户端无法伪造位置。上报采用与 tick 同频的 20 Hz 定频发送，
> 内容是"当前按住什么"而不是"刚刚按了什么"，所以丢一帧下一帧自动纠正，
> 不需要确认和重传；同时给输入设了 0.5 秒的保质期，避免客户端失联后角色继续移动。
> 移动用整数像素每 tick 计算，保证同样的输入序列产生完全相同的轨迹，实验可复现。
>
> 心跳用 `C_HEARTBEAT` / `S_HEARTBEAT_ACK`，服务端把客户端的 `client_time`
> **原样回显**，RTT 完全在客户端本地计算，因而不依赖两端时钟同步；
> 时间戳用单调时钟毫秒、无符号差值，天然容忍 32 位回绕。
> 服务端每个连接维护 `last_recv_at`，每秒检查一次，超过 15 秒即 3 倍心跳间隔
> 判定断线并清理会话，避免误判偶发丢包。
>
> 服务端每秒输出一次 tick 耗时与输入帧速率，这是"输入处理负载"的直接数据源。

---

## 8. 这一步改了哪些代码

| 文件 | 改动 |
|---|---|
| [protocol/world.py](../../protocol/world.py) | 🆕 世界尺寸（720×960、20 边距）—— 服务端边界与客户端缩放共用一份 |
| [server/movement.py](../../server/movement.py) | 🆕 运动学纯函数：`keys_to_dx` / `clamp_x` / `apply_input` |
| [server/stats.py](../../server/stats.py) | 🆕 `TickStats`：tick 耗时 p50/p95 + 每秒输入帧数 |
| [bot/agent.py](../../bot/agent.py) | 🆕 单个机器人：3 协程 + `BotConfig` / `BotResult` |
| [protocol/messages.py](../../protocol/messages.py) | ✏️ `C_INPUT` / `C_HEARTBEAT` / `S_HEARTBEAT_ACK` + struct + `now_ms` / `rtt_ms` |
| [server/main.py](../../server/main.py) | ✏️ `dispatch` 分发、输入保质期、超时清理、tick 打点、argparse；删掉 `sin` 摆动 |
| [bot/main.py](../../bot/main.py) | ✏️ 新 CLI（`--input-hz` / `--heartbeat` / `--key-hold` / `--seed`）+ 新指标 |
| [client/net.py](../../client/net.py) | ✏️ `send()` / `flush()` 发送队列 + `MAX_OUTBOX` |
| [client/main.py](../../client/main.py) | ✏️ 键盘 → `C_INPUT`、心跳、HUD 显示 RTT；世界尺寸改为 import |
| [client/console.py](../../client/console.py) | ✏️ 加心跳（不加会被 15 秒超时踢掉）+ 打印 RTT |
| [tests/\*](../../tests) | 🆕 4 个测试文件 + 更新 `test_bot_metrics.py` |

**怎么跑**：

```powershell
# 服务端（--timeout 0 关掉超时判定，--no-stats 不打印每秒统计）
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main 9527 --timeout 5

# 图形客户端：←/→ 或 A/D 移动，HUD 上有 keys / rtt
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.main

# 机器人：--input-hz 0 就是 7a 的观察者
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --ramp 5
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --input-hz 0
```

---

## 9. 实测结果（本机 loopback）

### 9.1 机器人

| 场景 | 连接 | 快照 | 输入 | 心跳 | 间隔 p50 | 间隔 p95 | RTT p50 | RTT p95 | errors |
|---|---|---|---|---|---|---|---|---|---|
| 10 输入 bot / 8 s | 10/10 | 1600 | 1600 | 20/20 ack | 47.3 ms | 62.9 ms | 0.0 ms | 1.0 ms | 0 |
| 10 输入 bot / 6 s（seed 12345） | 10/10 | 1200 | 1200 | 20/20 ack | 47.2 ms | 62.9 ms | 0.0 ms | 1.0 ms | 0 |
| 5 观察 bot / 6 s（`--input-hz 0`） | 5/5 | 598 | 0 | 10/10 ack | — | — | 0.0 ms | 0.0 ms | 0 |

`20 Hz × 8 s × 10 bot = 1600`、`20 Hz × 6 s × 10 bot = 1200` —— **输入条数完全对得上**。

### 9.2 服务端 tick 耗时（每秒一行）

| 场景 | avg | p50 | p95 | in/s |
|---|---|---|---|---|
| 空载 | 0.005 ms | 0.005 ms | 0.008 ms | 0 |
| 5 观察 bot | 0.256 ms | 0.253 ms | 0.286 ms | 0 |
| 10 输入 bot | 0.33 ~ 0.38 ms | 0.33 ms | 0.42 ~ 0.47 ms | **198 ~ 203** |

> 10 个 bot × 20 Hz = 200 条/秒，服务端统计到 198~203 条/秒 —— **对得上**。
> 观察者模式 `in 0/s`，说明"有没有输入"是可观测的，这正是 E9 要的对照。

### 9.3 输入真的驱动了位移（服务端权威验证）

| 操作（持续 1 秒） | x 起点 → 终点 | 位移 | 期望 |
|---|---|---|---|
| 按左 | 345 → 60 | **−285** | −300（采样差一个 tick） |
| 按右 | 35 → 320 | **+285** | +300 |
| 左右同时按 | 455 → 455 | **0** | 0（抵消） |
| 松手 0.4 秒后 | 455 连续 8 帧 | **0** | 0（保质期生效） |

### 9.4 超时（服务端 `--timeout 5`）

| 场景 | 结果 |
|---|---|
| 心跳间隔 2 s（< 5 s 超时） | 活满 12 s，18/18 ack，errors 0 |
| 什么都不发（纯观察） | 约 6 s 被踢，日志 `timed out (no message for > 5s)` |

### 9.5 pygame 客户端

| 版本 | 服务端统计的输入速率 |
|---|---|
| `next_input_at = now + 0.05` | 17/s（被帧率量化了） |
| `next_input_at += 0.05`（现在的写法） | **20/s** ✅ |

> ⚠️ 以上全是本机 loopback 数据（RTT 0~1 ms），**不是最终网络实验数据**（D-016）。

---

## 10. 现在的限制 / 下一步

- **上行带宽没有合并**：C_INPUT 只有 1 字节，帧头 12 字节是它的 12 倍。
  100 个客户端就是 26 KB/s 的纯帧头开销。"批量合并发送"（`02 §12`）列为优化项。
- **没有客户端预测**：按下去到画面动，隔着一个 RTT + 最多一帧（第三梯队 F12）。
- **广播是 O(客户端数)²**：每个客户端都要收到"全部玩家"的快照，
  100 人时每帧 1126 字节。慢客户端的独立发送队列是 D-020 记的账。
- **心跳只看 RTT，不看丢包**：TCP 保证不丢，所以丢包统计要等 E5 用 netem 注入。
- **没有防洪**：`ERR_RATE_LIMITED` 等有认证和真实玩家再说。
- **没有 `S_PLAYER_LEAVE`**：靠"快照是全量真相"（D-012）覆盖，事件同步留给游戏内容阶段。

**下一步（第 8 步）**：数据采集 + 压测实验（**E9 实体数影响是核心**），
把 `bot --out` 的 JSON 和 `TickStats` 接到 `tools/plot.py` 出图。

---

## 11. 验收标准

能用自己的话说出这四句，就算过：

1. **只发意图不发坐标**：客户端说"我按了左"，服务端决定"你在哪"。
2. **定频 20 Hz + 0.5 秒保质期**：丢一帧下一帧自动纠正；失联就当作松手。
3. **心跳原样回显 + 单调时钟**：RTT 本地算，不需要两端对表；32 位回绕也免疫。
4. **收发的三种"分离"**：客户端收发分离（非阻塞 + 发送队列）、
   机器人收发分离（三个协程）、服务端"判定 / 关闭 / 清理"分离（可测且不打架）。