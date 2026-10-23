# 第 7 步 7a · 观察者机器人（人话版）

> 对应代码：[bot/main.py](../../bot/main.py)
>
> 对应测试：`tests/test_bot_metrics.py`（3 个）
>
> 日期：2026-10-22

---

## 0. 一句话

机器人客户端就是**一群没有窗口的假玩家**：它们像真实客户端一样连服务端、收快照，
但不画画，只负责制造连接和记录数据。

---

## 1. 这一步解决什么问题？

压测需要几十个客户端，但：

- 手动开 50 个 pygame 窗口不现实
- 每个窗口都要 GPU/CPU，测到的不是服务端性能
- 人不可能 5 秒点一次“连接”

所以需要一个**无界面、可批量、能统计**的假客户端。

第 7 步拆成两半：

| 版本 | 做什么 | 改服务端吗 |
|---|---|---|
| **7a 观察者** | 只连接 + 收快照 | 不改 |
| 7b 输入版 | 额外发 `C_INPUT` + heartbeat | 要改 |

先做 7a，是为了**隔离变量**：如果 20 个连接都连不上，先查连接/广播；
如果 7a 稳定，7b 出问题就只可能是输入处理。

---

## 2. 7a 的数据流

```text
bot 1 ──连接──┐
bot 2 ──连接──┤
...           ├──► server.main ──► 20 Hz 广播
bot 20 ─连接──┘

每个 bot：收 welcome → 循环收 snapshot → 记录 snapshots / bytes / interval
```

机器人**不发任何消息**，所以服务端的 `while recv_frame_async` 一直等着；
机器人断开时，服务端收到 EOF，清理。

---

## 3. 核心代码逐行讲

### 3.1 一个机器人：`run_bot`

```python
reader, writer = await asyncio.open_connection(host, port)
welcome = await recv_frame_async(reader)

deadline = time.perf_counter() + duration
while True:
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        break

    frame = await asyncio.wait_for(recv_frame_async(reader), timeout=remaining)
    ...
```

- `open_connection`：异步建连，不阻塞其他 bot。
- `recv_frame_async`：复用第 5 步的 asyncio 收帧。
- `wait_for(... timeout=remaining)`：到时间就退出，不会卡在收包上。
- 每个 bot 有自己的 `deadline`，所以总耗时 ≈ `duration + ramp × (N-1)`。

### 3.2 批量启动：`run_farm`

```python
for _ in range(args.clients):
    tasks.append(asyncio.create_task(run_bot(...)))
    if args.ramp > 0:
        await asyncio.sleep(1.0 / args.ramp)
return await asyncio.gather(*tasks)
```

- `create_task`：每个 bot 一个协程，单线程里并发。
- `ramp`：每秒起几个。`ramp=10` 就是每 100 ms 起一个。
- `gather`：等所有 bot 结束，收集结果。

### 3.3 汇总：`summarize`

```python
connected = sum(1 for r in results if r.connected)
snapshots = sum(r.snapshots for r in results)
intervals = [x for r in results for x in r.intervals]
```

输出：

| 字段 | 含义 |
|---|---|
| `clients_connected` | 成功连上的数量 |
| `snapshots` | 所有 bot 收到的快照总数 |
| `snapshots_per_s` | 总吞吐 |
| `bytes_per_s` | 广播带宽 |
| `interval_p50_ms` | 一半快照间隔小于这个值 |
| `interval_p95_ms` | 95% 快照间隔小于这个值 |
| `errors` | 连接/协议错误数 |

> p50 / p95 比“平均值”更有用：平均值会被少数抖动拉偏，p95 能看出“最慢的 5%”。

---

## 4. 防御性代码（单独看）

| 代码 | 防的是什么 |
|---|---|
| `asyncio.wait_for(..., timeout=remaining)` | bot 不会因为服务端不发而永远卡住 |
| `if frame is None: errors.append("server closed")` | 服务端主动关闭时记录，不静默 |
| `except (OSError, ProtocolError)` | 连接拒绝、协议错误都记到 errors，不让进程崩 |
| `finally: writer.close(); await wait_closed()` | 每个 bot 都释放连接，服务端才能清理 |
| `ramp` | 避免 50 个连接在同一瞬间打过去 |
| `clients_connected` 与 `clients_requested` 分开 | 能看出失败率，而不是只看“跑了” |

---

## 5. 可以跳过的语法（放心跳）

1. `argparse` —— 命令行参数解析；先看 `--clients` / `--duration` / `--ramp` 三个就够。
2. `@dataclass BotResult` —— 装结果的盒子，和 `Frame` 一样。
3. `asyncio.gather` —— 等所有 bot 结束，收集返回值。
4. `percentile()` —— 手写分位数，不用 `numpy`。
5. `json.dumps(..., ensure_ascii=False)` —— 输出中文/JSON。

**不要跳过的**：`open_connection`、`wait_for`、`create_task`、`gather`、`ramp`。

---

## 6. 自测题（5 道）

### Q1. 为什么用 asyncio，不用每个 bot 一个线程？

<details>
<summary>答案</summary>

几十上百个连接，用线程会有线程创建/切换开销，还要处理锁。
asyncio 一个线程里跑几十个协程，连接空闲时不占 CPU，和服务器模型一致。

</details>

---

### Q2. 为什么要 ramp-up，不一次性全连？

<details>
<summary>答案</summary>

一次性全连测到的是“连接风暴”的瞬时峰值，不是稳态并发；
真实玩家是陆续上线的。ramp 每秒起几个，更接近真实负载，也避免把服务端打崩。

</details>

---

### Q3. 7a 为什么不让机器人发输入？

<details>
<summary>答案</summary>

7a 只验证“连接 + 广播”。如果同时加输入，出问题时分不清是连接、广播还是输入处理。
先观察者，7a 稳定后再加 `C_INPUT`，变量隔离。

</details>

---

### Q4. p50 和 p95 分别说明什么？

<details>
<summary>答案</summary>

p50（中位数）：一半的快照间隔小于它，代表“典型情况”。
p95：95% 的快照间隔小于它，代表“最慢的 5%”有多慢。
网络/调度抖动看 p95 比平均值更有意义。

</details>

---

### Q5. 为什么正式实验不能在同一个 CPU 上压？

<details>
<summary>答案</summary>

bot 和服务端抢同一个 CPU，服务端拿到的 CPU 时间变少，E8 的 CPU/内存数据会失真，
延迟也会被放大。正式实验用 VMnet1 把 bot 和服务端分开，或至少分进程并记录干扰。

</details>

---

## 7. 答辩话术（可直接背）

> 机器人客户端是一个无界面的假客户端：用 asyncio 在一个进程里开多个协程，
> 每个协程连接服务端、接收快照，并统计连接数、快照间隔、带宽和错误。
> 第一步只做观察者，不改服务端，用来隔离“连接/广播”问题；确认稳定后再加输入和心跳，
> 测输入处理负载。机器人只发输入、不发坐标，保证服务端权威。正式实验会把机器人和服务端
> 放在 VMnet1 的两端，避免同机抢 CPU。

---

## 8. 这一步改了哪些代码

| 文件 | 改动 |
|---|---|
| [bot/main.py](../../bot/main.py) | asyncio 机器人农场、ramp、指标汇总 |
| [bot/\_\_init\_\_.py](../../bot/__init__.py) | 机器人包 |
| [tests/test_bot_metrics.py](../../tests/test_bot_metrics.py) | 3 个指标汇总用例 |
| [server/main.py](../../server/main.py) | 客户端断开不再打印 error，只保留 joined / left |

**怎么跑**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --ramp 5
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 50 --duration 5 --ramp 20 --out bot_50.json
```

---

## 9. 实测结果（本机 loopback）

| 场景 | 连接 | 快照 | p50 | p95 | errors |
|---|---|---|---|---|---|
| 20 bots / 5 s / ramp 10 | 20/20 | 1996 | 47.3 ms | 62.9 ms | 0 |
| 50 bots / 5 s / ramp 20 | 50/50 | 4988 | 47.5 ms | 63.1 ms | 0 |

> p95 略高于 50 ms 是调度抖动，不是协议错误。
> 这些是 loopback 数据，**不是最终网络实验数据**（D-016）。

---

## 10. 现在的限制 / 下一步

- 机器人**不发输入**：服务端还是占位摆动。
- 没有 heartbeat：测不了 RTT。
- 只有 JSON 汇总：还没有逐秒 CSV / 出图。
- 同机压测会抢 CPU。

**7b**：加 `C_INPUT`（1 字节 keys）+ `C_HEARTBEAT` / `S_HEARTBEAT_ACK`，
让机器人真的移动、测 RTT，再跑 E2/E3/E9。

---

## 11. 验收标准

能用自己的话说出这三句，就算过：

1. **机器人 = 无界面假客户端**：批量连接、收快照、统计指标。
2. **7a 先不改服务端**：只验证连接/广播，隔离变量。
3. **ramp-up + p95**：避免连接风暴，用 p95 看最慢的 5%。
