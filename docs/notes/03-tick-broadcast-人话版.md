# 第 5 步 · asyncio + 20 Hz tick + 广播（人话版）

> 对应代码：[server/main.py](../../server/main.py)、[client/main.py](../../client/main.py)、
> [protocol/snapshot.py](../../protocol/snapshot.py)、
> [protocol/framing.py](../../protocol/framing.py)
>
> 对应测试：`tests/test_snapshot.py`、`tests/test_framing_async.py`
>
> 日期：2026-10-21

---

## 0. 一句话

服务端像一个 **20 Hz 的广播员**：每 50 ms 算一次所有玩家的位置，然后向所有连着的客户端喊一遍“现在谁在哪”。

---

## 1. 这一步解决什么问题？

第 4 步之前，服务端只会“你发一句，我回一句”，而且一次只能服务一个客户端。

真实游戏不是这样：

- 多个客户端要**同时**连着
- 服务端要**持续**算位置，而不是等客户端发
- 所有人的画面要**一致**，所以由服务端统一算、统一广播

这就是 **服务端权威 + tick + 广播**：

```
客户端只负责“收”和“画”
服务端负责“算”和“广播”
```

为什么不让每个客户端自己算？

- 客户端算，10 个客户端就有 10 个版本的世界，谁对？
- 客户端可以伪造坐标
- 服务端算一次，所有人看到同一份结果（D-006）

---

## 2. 数据流

```
客户端 A ──连接──┐
客户端 B ──连接──┤
                 ▼
          asyncio 服务端
                 │
     ┌───────────┴───────────┐
     │  handle_client        │  收连接、发 welcome、等断开
     │  tick_loop (20 Hz)    │  每 50 ms：更新坐标 → 广播快照
     └───────────┬───────────┘
                 │  S_SNAPSHOT（同一份字节）
     ┌───────────┴───────────┐
     ▼                       ▼
客户端 A                 客户端 B
```

---

## 3. 核心代码逐行讲（必须懂的最小集合）

### 3.1 启动服务端

```python
server = await asyncio.start_server(game.handle_client, HOST, port)
tick_task = asyncio.create_task(game.tick_loop())
async with server:
    await server.serve_forever()
```

- `start_server`：每来一个客户端，就自动开一个协程去跑 `handle_client`。
- `create_task`：把 `tick_loop` 丢到后台，和“接收连接”同时跑。
- `serve_forever`：主协程停在这里，直到 Ctrl+C。

**关键理解**：这些任务都在**同一个线程**里，由事件循环轮流执行；不是多线程。

### 3.2 新客户端进来

```python
player_id = self.next_id
self.next_id += 1
color = player_id % 8
client = Client(player_id=..., color=..., x=360, y=..., writer=writer)
self.clients[player_id] = client

await send_frame_async(writer, S_WELCOME, 0, WELCOME.pack(player_id, color))
```

1. 分配一个递增的 `player_id`
2. 选一个颜色
3. 把客户端放进 `self.clients` 字典
4. 回一条 `S_WELCOME`，告诉客户端“你是几号、什么颜色”

然后：

```python
while True:
    frame = await recv_frame_async(reader)
    if frame is None:
        break
```

阶段 5 不处理客户端消息，这个循环只用来**检测断开**：客户端一关，`recv_frame_async` 返回 `None`，循环结束，进入清理。

### 3.3 20 Hz tick

```python
next_tick = loop.time()
while True:
    next_tick += 0.05
    await asyncio.sleep(max(0.0, next_tick - loop.time()))

    self.tick += 1
    self.update_players()
    await self.broadcast_snapshot()
```

为什么不是直接 `await asyncio.sleep(0.05)`？

- `sleep(0.05)` 每次都会“多睡一点点”，误差累积，跑一小时可能偏几秒。
- `next_tick += 0.05` 是**按绝对时间排班**：第 1 次 0.05，第 2 次 0.10……
- `max(0.0, ...)` 防止某次广播太慢导致“睡负数”。

### 3.4 更新占位坐标

```python
for client in self.clients.values():
    phase = self.tick * 0.05 + client.player_id
    client.x = 360 + int(120 * math.sin(phase))
```

每个玩家在自己的 y 附近左右摆动。现在**不读键盘**，所以这不是真正的游戏操作，只是让你看到“服务端在算、客户端在收”。

### 3.5 打包快照

```python
payload = pack_snapshot(self.tick, players)
await send_frame_async(client.writer, S_SNAPSHOT, self.tick, payload)
```

`pack_snapshot` 做两件事：

1. 打包 13 B 快照头（tick、关卡、波次、各类计数）
2. 每个玩家追加 11 B（id、x、y、power、color、flags、score）

同一 tick 里，所有客户端收到的是**同一份字节**，所以画面一致。

### 3.6 客户端收快照

```python
welcome = await recv_frame_async(reader)
player_id, color = WELCOME.unpack(welcome.payload)

while True:
    frame = await recv_frame_async(reader)
    snapshot = unpack_snapshot(frame.payload)
    print(f"tick={snapshot.tick} ...")
```

客户端不做逻辑，只解析和打印。第 6 步会把 `print` 换成 pygame 绘制 + 插值。

---

## 4. 防御性代码（单独看）

| 代码 | 防的是什么 |
|---|---|
| `try / finally` 里 `clients.pop(player_id)` | 客户端异常断开也要清理，避免幽灵玩家 |
| `writer.close()` + `await writer.wait_closed()` | 释放连接资源 |
| `except ConnectionError` | 对端强杀时 `wait_closed` 可能抛错，不能让服务端崩 |
| `broadcast_snapshot` 里 `try/except` + `pop` | 某个客户端发送失败时，只移除它，不拖垮其他人 |
| `if not self.clients: return` | 没人在线时不做无用打包 |
| `max(0.0, next_tick - loop.time())` | 广播超时后不睡负数 |
| `unpack_snapshot` 校验长度/计数 | 防止对端发一个畸形快照把客户端解析崩 |
| `parse_header` / `recv_frame_async` | 帧头 magic/version/length 校验，半包/截断处理 |

---

## 5. 可以跳过的语法（放心跳）

1. `@dataclass class Client` —— 可以当成“带字段的字典”，先不用管它怎么生成 `__init__`。
2. `dict[int, Client]` —— 类型注解，运行时不检查。
3. `asyncio.create_task` —— 可以先理解成“后台开一个协程，和主循环同时跑”。
4. `async with server` —— 自动关闭服务器的语法糖。
5. `sorted(..., key=lambda c: c.player_id)` —— 按 id 排序，保证输出顺序稳定。
6. f-string 里的 `:02X` —— 十六进制格式化，调试用。

**不要跳过的**：`await`、`async def`、`start_server`、`tick_loop`、`recv_frame_async`。

---

## 6. 自测题（5 道，先自己说一遍）

### Q1. 为什么 tick 用 `next_tick += 0.05`，不直接 `sleep(0.05)`？

<details>
<summary>答案</summary>

`sleep(0.05)` 每次都会多睡一点，误差会累积；`next_tick += 0.05` 是给每个 tick 排一个**绝对时间**，
每次只睡“到下一个绝对时间还差多少”，所以长时间跑也不会越来越慢。

</details>

---

### Q2. 为什么快照里没有“删除玩家”的消息？

<details>
<summary>答案</summary>

因为**快照是全量真相**（D-012）：客户端每收到一帧，就完全按快照重建玩家列表；
快照里没有的玩家，客户端自然就不画了。所以不需要单独的“删除”消息。

</details>

---

### Q3. 为什么服务端先发 `S_WELCOME`，再开始广播？

<details>
<summary>答案</summary>

客户端要先知道自己的 `player_id`，才能在自己的画面里区分“我”和“别人”。
`S_WELCOME` 就是“你是几号、什么颜色”；之后的快照里会带所有玩家，包括自己。

</details>

---

### Q4. 一个客户端断线，服务端怎么清理？

<details>
<summary>答案</summary>

`handle_client` 里的 `recv_frame_async` 在连接关闭时返回 `None`，跳出循环，
进入 `finally`：从 `self.clients` 里 `pop` 掉，关闭 writer，打印 left。
如果是在广播时发送失败，`broadcast_snapshot` 也会把它 `pop` 掉。

</details>

---

### Q5. 为什么是 20 Hz，不是 60 Hz？

<details>
<summary>答案</summary>

20 Hz 是**服务端逻辑/网络同步频率**：每 50 ms 广播一次，带宽和 CPU 都省。
客户端渲染可以是 60 fps，中间用**插值**把 20 Hz 的快照补成 60 fps 的平滑动画（第 6 步）。
如果直接 60 Hz 广播，带宽和 CPU 都会成倍增加，但游戏体验提升有限。

</details>

---

### 附加题. 当前广播最大的隐患是什么？

<details>
<summary>答案</summary>

`await send_frame_async(...)` 是**串行**的：如果一个客户端网络很慢，`drain()` 会卡住，
整个 tick 都会等它。现在客户端少（2~4 人）没问题；后面要改成
“每个客户端一个发送队列 + 丢旧帧”，慢客户端只影响自己。

</details>

---

## 7. 答辩话术（可直接背）

> 服务端用 asyncio 单线程事件循环，每个客户端连接对应一个协程；同时有一个 20 Hz 的 tick 循环，
> 用绝对时间累加避免 sleep 漂移。每个 tick 服务端更新权威状态，打包成全量快照，
> 向所有客户端广播同一份字节。客户端只负责解析和渲染，不参与世界状态计算。
> 玩家断线时服务端在 finally 中清理；某个客户端发送失败只移除它，不影响其他人。
> 当前快照只包含玩家条目，敌机/子弹/道具后续扩展；慢客户端的发送队列是下一步优化。

---

## 8. 这一步改了哪些代码

| 文件 | 改动 |
|---|---|
| [server/main.py](../../server/main.py) | asyncio 服务端、20 Hz tick、广播、断线清理 |
| [client/main.py](../../client/main.py) | 控制台客户端，打印每帧玩家位置 |
| [protocol/snapshot.py](../../protocol/snapshot.py) | 13 B 快照头 + 11 B 玩家条目编解码 |
| [protocol/framing.py](../../protocol/framing.py) | `parse_header`、`recv_frame_async`、`send_frame_async` |
| [protocol/messages.py](../../protocol/messages.py) | `S_WELCOME=0x7C`、`S_SNAPSHOT=0x84`、`WELCOME` |
| [tests/test_snapshot.py](../../tests/test_snapshot.py) | 7 个快照用例 |
| [tests/test_framing_async.py](../../tests/test_framing_async.py) | 5 个 asyncio 接收用例 |

**怎么跑**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.main Alice
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.main Bob
```

开两个客户端窗口，能看到同一个 tick 里两个玩家的坐标。

---

## 9. 现在的限制 / 下一步

- 没有房间：所有人都在同一个世界。
- 没有客户端输入：坐标是服务端占位摆动。
- 没有渲染和插值：客户端只打印。
- 没有慢客户端队列：一个慢客户端可能拖慢 tick。
- 快照只带玩家：敌机 / 子弹 / 道具计数为 0。

**下一步（第 6 步）**：客户端渲染 + 插值，把 20 Hz 快照补成 60 fps 的占位方块动画。

---

## 10. 验收标准

能用自己的话说出这三句，就算过：

1. **服务端权威**：位置由服务端算，客户端只收快照。
2. **20 Hz tick**：每 50 ms 更新 + 广播一次；用绝对时间累加，不用 `sleep(0.05)` 累积误差。
3. **全量快照**：同一 tick 所有客户端收到同一份字节；快照里没有的玩家就是删除了。
