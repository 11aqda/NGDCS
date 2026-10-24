# 第 8 步 8a 补 · 碰撞判定与分阶段计时（人话版）

> 对应代码：[server/entities.py](../../server/entities.py)（`detect_collisions`）、
> [server/stats.py](../../server/stats.py)（四段拆解）、
> [server/main.py](../../server/main.py)（五处计时点 + 崩溃上报）、
> [server/metrics.py](../../server/metrics.py)（5 个新列）、
> [tools/plot.py](../../tools/plot.py)（图 6-17 多线 + 图 6-20）
>
> 对应测试：`tests/test_tick_guard.py`（6，新增）、`tests/test_entities.py`（+9）、
> `tests/test_tick_stats.py`（+8）、`tests/test_metrics.py`（+2）、`tests/test_plot.py`（+3）
>
> 日期：2026-10-25 ｜ 前置：D-024（8a 第一轮）

---

## 0. 一句话

8a 第一轮把「实体」造出来了，但跑完发现 **CPU 曲线是平的** ——
因为占位实体没有碰撞检测，而 `01 §7.1` 那份「87.3% 单核」的基准里，
**碰撞检测才是花时间的大头**。

这一轮补上碰撞，同时做一件更重要的事：**把一帧的时间拆成四段分别计时**。
于是这张图从「一条线」变成了「一条线 + 它由什么构成」。

---

## 1. 这一步解决什么问题？

### 1.1 为什么 CPU 曲线要「弯」

`03-实验清单.md` 的图 6-19 要画「实体数 vs 单核占用」，并且**标出 50% 舒适线**。
如果曲线一直贴在地板上（实测 100 敌机 + 800 子弹才 1.7%），
这张图什么也证明不了 —— **没有拐点，就没有"上限从哪来"的结论**。

而 `D-011` 的「同屏敌机 ≤ 30、子弹 ≤ 300」正是从那份基准反推出来的。
曲线不弯，这条约束在论文里的论证链就断了一半。

### 1.2 为什么「碰撞」和「通信」必须分开

这是本次最关键的要求。假设只报一个总耗时「6.1 ms」，你能回答下面哪个问题？

- ❌ 这 6.1 ms 里，是自定义协议的序列化慢，还是广播慢？
- ❌ 实体数涨 3.86 倍时，是哪一部分涨得最快？
- ❌ 如果要把性能提上去，应该优化网络层还是游戏逻辑？
- ❌ **这个通信系统到底好不好？**（这是毕设题目本身）

一个总数一个都答不了。**拆成四段之后，四个问题全都有答案。**

---

## 2. 四段是怎么切的

```text
                    started ─────────────────────────────────────────────► net_done
                       │                                                        │
        ┌──────────────┼──────────────┬───────────────┬─────────────────────────┘
        ▼              ▼              ▼               ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ sim_ms  │   │collision │   │  ser_ms  │   │  net_ms  │
   │ 模拟     │   │ 碰撞判定  │   │ 序列化    │   │ 广播发送  │
   └─────────┘   └──────────┘   └──────────┘   └──────────┘
    移动/剔除/      朴素 O        逐实体          逐客户端
    补足数量      (子弹×敌机)   struct.pack    write+drain
        └──────┬──────┘              └──────┬──────┘
            逻辑耗时                     通信耗时
```

**五个计时点首尾相接**，所以：

```
sim_ms + collision_ms + ser_ms + net_ms  ≡  tick_ms_avg      （严格相等，不是约等于）
```

这条恒等式很要紧：它让图 6-20 能画成 **100% 堆叠柱**，不需要"其它"那一类含糊的项。
答辩时被问「你怎么保证没有漏计的部分」，答案就是这句话。

---

## 3. 核心代码逐行讲

> 🔴 = **必须懂的最小集合** ｜ ⚪ = 可以先跳过

### 3.1 🔴 朴素碰撞：两层循环，先判 x

```python
def detect_collisions(bullets, enemies):
    radius = COLLISION_RADIUS          # 8 px
    hits = 0
    for bullet in bullets:
        bx = bullet.x                  # ① 取到局部变量
        by = bullet.y
        for enemy in enemies:
            dx = bx - enemy.x
            if -radius <= dx <= radius:     # ② 先判 x
                dy = by - enemy.y
                if -radius <= dy <= radius: # ③ x 重叠了才去算 y
                    hits += 1
    return hits
```

**① 为什么把 `bullet.x` 取出来？**
内层循环跑 800 次（敌机数），如果每次写 `bullet.x`，就要做 800 次属性查找。
提到循环外面只做 1 次 —— 这是**同一份数据的两种写法里更省的那个**。

**② 为什么先判 x 再判 y？**
子弹和敌机的 x 大部分时候是不重叠的，`dx` 判断一失败就直接跳到下一对，
**y 的两次比较就省掉了**。这叫「短路」。
如果不这么写（例如用 `abs(dx) <= r and abs(dy) <= r` 一次判完），
每一对都要算 4 次运算，实测会明显更慢。

> ⚠️ 这两条优化**改变的是常数因子，不改变 O(子弹×敌机) 的复杂度**。
> 论文里必须写清楚：我们复现的是**算法复杂度**，所以**趋势**能和 `01 §7.1` 对上，
> 但**绝对值不能逐位对齐**（当年那个原型是一次性代码，没留下来）。

### 3.2 🔴 为什么「只判定不生效」

```python
# 命中之后什么都不做，只把 hits 加一
hits += 1
```

**碰撞检测明明判出命中了，为什么不把子弹和敌机删掉？** 三个理由：

1. **E9 的自变量必须恒定**。`--enemies 100 --bullets 800` 的意义是
   「屏幕上**一直**有 100 个敌机和 800 颗子弹」。如果命中就删，
   数量就会忽多忽少 —— 而"删掉立刻补足"又等于**把命中效果当场抹平**，
   绕一圈回到原点，还多了一堆复杂度。
2. **伤害结算不属于这一步**。掉血、掉落、计分是第 11 步的游戏内容。
   现在做等于白做 —— 第 11 步要重写。
3. **它和「补足数量」是同一件事的两种做法**：
   补足是"少了就加"，只判定不生效是"根本不会少"。后者更干净。

**但为什么还要数 `hits`？**
因为它证明**这个循环真的在算**。如果没有它，一个写错方向、
实际上什么都没遍历的空转循环，同样会报出很漂亮的耗时曲线 ——
而你完全看不出来。`hits` 随实体数增长，就是"工作量真实"的证据。

### 3.3 🔴 五个计时点，一次不多一次不少

```python
started = time.perf_counter()

self.update_players(started)                    # 玩家按输入移动
self.world.step([...])                          # 实体移动/剔除/补足
sim_done = time.perf_counter()                  # ← ① 结束

hits = detect_collisions(self.world.bullets, self.world.enemies)
collision_done = time.perf_counter()            # ← ② 结束

payload = self.build_snapshot() if self.clients else None
ser_done = time.perf_counter()                  # ← ③ 结束

if payload is not None:
    await self.broadcast(payload)
net_done = time.perf_counter()                  # ← ④ 结束

self.stats.record_tick(net_done - started)      # 总
self.stats.record_phase("sim", sim_done - started)
self.stats.record_phase("collision", collision_done - sim_done)
self.stats.record_phase("ser", ser_done - collision_done)
self.stats.record_phase("net", net_done - ser_done)
```

每一段都是「上一个计时点到这一个计时点」，**没有缝隙也没有重叠**。
这就是 §2 那条恒等式的来源 —— 它不是凑出来的，是**结构上保证**的。

> 为什么要把 `broadcast_snapshot()` 拆成 `build_snapshot()` + `broadcast(payload)`？
> 因为原来这两件事写在一个方法里，**没法分别计时**。
> 拆分本身不改变行为，只是让"序列化"和"发送"能被分开观察。

### 3.4 🔴 为什么每段取「平均值」，不取 p95

因为 **p95 之间不能相加**。

假设 sim 的 p95 是 1 ms、collision 的 p95 是 3 ms，它们的和 4 ms
**不等于**总耗时的 p95（总耗时的 p95 要各段在**同一次 tick** 里同时最慢，那是另一回事）。
用平均值就没有这个问题：`E[a+b] = E[a] + E[b]`，数学上就成立。

总耗时的 p95 我们照样保留（`tick_ms_p95`），只是它单独用，不参与堆叠。

### 3.5 🔴 tick_loop 的崩溃上报（这次真的踩到了）

这次改代码时漏了一行 import，结果：

```text
[server] tick loop started at 20 Hz
[server] player 1 joined from ('127.0.0.1', 57567)
[server] player 2 joined from ('127.0.0.1', 57568)
[server] player 1 left
```

看起来一切正常。但机器人那边的结果是：

```json
{ "clients_connected": 4, "snapshots": 0, "errors": 0 }
```

**连接是好的，一个报错都没有，但一帧快照都没收到。**

原因是 `tick_loop` 在第一个 tick 就抛了 `NameError`，**协程静静死掉**。
而 asyncio 有个很容易坑人的行为：

> 未取回的异常**只在任务对象被垃圾回收时**才打印。

`main()` 里 `tick_task = asyncio.create_task(...)` 一直**持有引用**，
所以只要进程活着，那个异常就**永远不会被打印**。

修法是挂一个 done 回调：

```python
tick_task.add_done_callback(report_tick_crash)
```

```python
def report_tick_crash(task, file=None):
    if task.cancelled():
        return None
    exc = task.exception()
    if exc is None:
        return None
    print(f"[server] !! tick loop 已崩溃，不再广播快照：{type(exc).__name__}: {exc}", ...)
    traceback.print_exception(...)
    return exc
```

**为什么这条防线对本项目特别重要**：E9 是**无人值守跑 3 分钟**的实验。
没有它，你会得到一份**跑完了、但全是 0 的数据**，
然后花半天怀疑是 CSV 写错了、是机器人有问题、是网络不通。

---

## 4. 防御性代码（单独看）

| 代码 | 防的是什么 |
|---|---|
| 先判 x 再判 y | 常数因子白白大几倍（不影响正确性，但影响可信度） |
| `(angle >> 5) & 0x07`（前一轮） | 角度越界 → 数组越界 |
| **只判定不生效** | 碰撞偷偷删实体，破坏 E9 自变量的恒定性 |
| 返回 `hits` | 空转的假循环也会报出漂亮的耗时，`hits` 是照妖镜 |
| 阶段名拼错就抛 `ValueError` | 阶段名打错 → 那一秒的数据**静默丢失**，图上就是缺一块 |
| 四段计时点首尾相接 | 堆叠图出现"其它"这一类含糊项，论文里说不清 |
| `report_tick_crash` | 静默死掉的 tick loop —— 跑完一整场实验却零数据 |
| `tests/test_tick_guard.py` 真跑 tick_loop | 上面那个 `NameError` 本该在**第一个 tick** 就被抓住 |

---

## 5. 可以跳过的语法（放心跳）

1. ⚪ `asyncio.Task.add_done_callback` —— 任务结束时自动调一个函数。
2. ⚪ `task.cancelled()` / `task.exception()` —— 区分"被取消"和"真出错"。
3. ⚪ `traceback.print_exception(type, exc, tb, file=...)` —— 手动打印堆栈。
4. ⚪ `unittest.IsolatedAsyncioTestCase` —— 标准库自带的异步测试基类。
5. ⚪ `matplotlib` 的 `ax.bar(..., bottom=...)` —— 堆叠柱状图就是"把每段往上垒"。
6. ⚪ `PHASE_SERIES` 元组表 —— 把"列名 / 图例 / 颜色 / 点型"打包，画图时循环用。

**不要跳过的**：两层循环的短路写法、**只判定不生效的三个理由**、
五个计时点的首尾相接、**为什么用平均值而不是 p95**、done 回调那条防线。

---

## 6. 自测题（6 道）

### Q1. 为什么碰撞检测判出命中了，却什么都不做？

<details>
<summary>答案</summary>

因为 E9 的自变量是「**同屏**实体数」。命中就删，数量就会波动；
"删了立刻补足"又等于把命中效果当场抹平，绕一圈回到原点。
只判定不生效，数量就**由构造保证**恒定，自变量最干净。
伤害结算是第 11 步的游戏内容，现在做是白做。

</details>

---

### Q2. 既然什么都不做，为什么还要统计 `hits`？

<details>
<summary>答案</summary>

它是「这个循环真的在算」的证据。一个写错方向、实际什么都没遍历的空转循环，
同样会报出很漂亮的耗时曲线 —— 光看 `collision_ms` 分辨不出来。
`hits` 随实体数增长，才能证明工作量是真实的。

</details>

---

### Q3. 为什么四段之和严格等于总耗时？

<details>
<summary>答案</summary>

因为五个计时点**首尾相接**：每一段都从"上一个计时点"量到"这一个计时点"，
中间既没有缝隙也没有重叠。所以这不是凑出来的巧合，是**结构上的恒等式**。
正因如此，图 6-20 的堆叠柱才能画成 100%，不需要"其它"这一类含糊项。

</details>

---

### Q4. 为什么每段取平均值而不是 p95？

<details>
<summary>答案</summary>

因为 **p95 之间不可相加**。`p95(a) + p95(b)` 不等于 `p95(a+b)` ——
后者要求两段在**同一次 tick** 里同时最慢。
平均值满足 `E[a+b] = E[a] + E[b]`，所以堆叠图只能用平均值。
总耗时的 p95 单独保留（`tick_ms_p95`），不参与堆叠。

</details>

---

### Q5. 实测发现「广播耗时几乎不随快照变大而增加」，为什么？

<details>
<summary>答案</summary>

实测 `net_ms` 从 0.196 ms 到 0.200 ms（基本持平），而同期快照从 1927 B 涨到 7357 B。
原因是**内核发送缓冲区没饱和**时，`await writer.drain()` 会立即返回 ——
它只在缓冲区满时才真的等待。所以广播的开销主要是
「每个客户端一次 write 调用」的固定成本，**≈ O(客户端数)，与包大小无关**。
（前提是缓冲区不饱和；一旦发得比链路快，就会退化。）

</details>

---

### Q6. 服务端日志一切正常、机器人却收不到快照，最可能是什么问题？

<details>
<summary>答案</summary>

`tick_loop` 协程**静默死掉了**。asyncio 的未取回异常只在任务对象被回收时才打印，
而 `main()` 一直持有 `tick_task` 的引用，所以进程活着时什么都不显示。
症状就是「连接正常、`snapshots: 0`、`errors: 0`」。
解决办法：挂 `add_done_callback` 主动上报 + 写一个真跑 tick_loop 的回归测试。
**长时间无人值守的实验尤其要防这个** —— 否则会跑完并留下一整份空数据。

</details>

---

## 7. 答辩话术（可直接背）

> 为了定位性能瓶颈，我把服务端单帧耗时拆成四个阶段分别计时：
> 模拟（实体移动与数量维护）、碰撞判定、序列化、广播发送，
> 并且五个计时点首尾相接，使四段之和在结构上严格等于总耗时 ——
> 因此可以用 100% 堆叠图呈现耗时构成，不存在无法归类的部分。
> 各阶段取平均值而非分位数，也是为了保证可加性。
>
> 实测结果表明：当同屏实体数从 234 增至 904（3.86 倍）时，
> 碰撞判定耗时增长 10.3 倍，符合 O(子弹×敌机) 的预期；
> 而通信部分合计只增长约 2 倍，其占比从 45.2% 下降到 15.7%。
> 其中广播发送耗时基本持平，说明在内核缓冲区未饱和时，
> 广播成本主要由客户端数量决定、与报文大小无关。
> 这组数据同时支撑两个结论：一是本系统的通信层具有良好可扩展性，
> 二是设计上限由游戏逻辑的算法复杂度决定，而非网络层。

---

## 8. 这一步改了哪些代码

| 文件 | 改动 |
|---|---|
| [server/entities.py](../../server/entities.py) | ✏️ 新增 `detect_collisions()`：朴素 O(子弹×敌机)，只判定不生效 |
| [server/stats.py](../../server/stats.py) | ✏️ tick 拆四段 + `hits` 计数；`PHASE_LABELS` / `LOGIC_PHASES` / `COMMS_PHASES` |
| [server/main.py](../../server/main.py) | ✏️ 五处计时点；`broadcast()` 与 `build_snapshot()` 拆开；**`report_tick_crash` 崩溃上报** |
| [server/metrics.py](../../server/metrics.py) | ✏️ CSV 新增 `sim_ms` / `collision_ms` / `ser_ms` / `net_ms` / `hits` |
| [tools/plot.py](../../tools/plot.py) | ✏️ 图 6-17 改多线；**新增图 6-20** 耗时构成占比 |
| [tests/test_tick_guard.py](../../tests/test_tick_guard.py) | 🆕 真跑 tick_loop 抓 `NameError` + 崩溃上报 + 四段都有值 |
| [tests/test_entities.py](../../tests/test_entities.py) | ✏️ 新增 `CollisionTest`（9 个） |
| [tests/test_tick_stats.py](../../tests/test_tick_stats.py) | ✏️ 新增 `PhaseTest` / `HitsTest` |
| [docs/03-实验清单.md](../03-实验清单.md) | ✏️ 指标定义补四段；图 6-17 描述更新；**新增图 6-20**；图表总数 19 → 20 |

**怎么跑**：

```powershell
# 服务端：屏幕上会直接打出分段耗时
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main --enemies 100 --bullets 800 --scenario E9-e100-b800-01

# 机器人 + 出图
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 4 --duration 180
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m tools.plot --csv data/server_metrics.csv --out docs/figures
```

服务端每秒一行，长这样：

```text
[server] tick 20 Hz | total 6.105 ms (p50 6.012 p95 6.480 max 7.113) |
  logic 5.148 (sim 0.374 + col 4.775) | comms 0.957 (ser 0.757 + net 0.200) |
  players 4 | e/b 100/800 | snap 7357 B | hits 26 | in 80/s
```

---

## 9. 实测结果（本机 loopback 冒烟，**不是 E9 正式数据**）

4 个输入机器人，每档约 20 秒，丢掉前 8 秒：

| 场景 | 实体 | 总 ms | 模拟 | **碰撞** | 序列化 | **广播** | 通信合计 | 快照 | 下行/客户端 | 单核 | hits/s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 30 敌机 + 200 子弹 | 234 | 1.071 | 0.125 | **0.462** | 0.288 | **0.196** | 0.484 | 1927 B | 38.8 KB/s | 1.4 % | 39 |
| 100 敌机 + 800 子弹 | 904 | 6.105 | 0.374 | **4.775** | 0.757 | **0.200** | 0.957 | 7357 B | 147.4 KB/s | 13.2 % | 514 |
| **增长倍数** | **3.86×** | 5.7× | 3.0× | **10.3×** | 2.6× | **1.02×** | 2.0× | 3.8× | 3.8× | 9.4× | 13.2× |

**构成占比（图 6-20 的数据）**：

| 场景 | 碰撞 | 模拟 | 序列化 | 广播 | **通信合计** |
|---|---|---|---|---|---|
| 30/200 | 43.1 % | 11.7 % | 26.9 % | 18.3 % | **45.2 %** |
| 100/800 | 78.2 % | 6.1 % | 12.4 % | 3.3 % | **15.7 %** |

**三条可以写进论文的结论**：

1. **通信占比随实体数下降**（45.2 % → 15.7 %）→ 通信层可扩展，**瓶颈在游戏逻辑侧**
2. **碰撞超线性增长**：实体 3.86 倍 → 碰撞 10.3 倍；
   配对数 6,000 → 80,000（13.3 倍），符合 O(子弹×敌机)
3. ⭐ **广播耗时与包大小几乎无关**（0.196 → 0.200 ms），
   同期快照涨 3.8 倍 —— 反直觉，但有数据支撑

> ⚠️ **8b 档位建议**：按这个斜率外推，**要在 50% 舒适线上找到拐点，
> 最高档得提到 200/1600 甚至 250/2000**（100/800 时单核只占 13.2%）。
> `03-实验清单.md §5` 已记这条。

---

## 10. 现在的限制 / 下一步

**限制**

- 碰撞**只判定不生效**：这是 E9 的测量需要，不是最终形态（第 11 步补伤害结算）
- 常数因子与 `01 §7.1` 的老原型**不可逐位对齐**（老代码没留下来），
  只能对齐**复杂度与趋势**
- 广播的"与包大小无关"结论**以缓冲区不饱和为前提**；
  真到瓶颈时会退化（那正是 E4/E5 网络损伤实验要测的）
- 仍是本机 loopback（D-016）

**下一步（8b）**：按 `03-实验清单.md §8` 的档位（**建议加两档到 200/1600 或 250/2000**）
各跑 3 分钟 × 2 次，出图 6-17 / 6-18 / 6-19 / 6-20，按 §7 模板写 `docs/experiments/` 记录。

---

## 11. 验收标准

能用自己的话说出这五句，就算过：

1. **碰撞只判定不生效**：为了 E9 自变量恒定；`hits` 是"循环真在算"的证据。
2. **五个计时点首尾相接**：所以四段之和**严格等于**总耗时，堆叠图没有"其它"。
3. **用平均值不用 p95**：因为 p95 之间不可相加。
4. **通信占比随实体数下降**：这是"通信层可扩展"的直接证据 —— 也是本次最大的收获。
5. **静默死掉的协程必须主动兜底**：asyncio 不会替你报错，无人值守的实验尤其要防。