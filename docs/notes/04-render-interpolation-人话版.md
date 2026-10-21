# 第 6 步 · pygame 渲染 + 插值（人话版）

> 对应代码：[client/main.py](../../client/main.py)、[client/net.py](../../client/net.py)、
> [protocol/framing.py](../../protocol/framing.py)（`FrameParser`）
>
> 对应测试：`tests/test_frame_parser.py`（8 个）
>
> 日期：2026-10-21

---

## 0. 一句话

服务端每 50 ms 发一张“照片”（快照），客户端每秒要画 60 张画；
**插值**就是在两张照片之间补出中间帧，让方块看起来是滑过去的，而不是一跳一跳。

---

## 1. 这一步解决两个问题

### 问题 A：网络不能卡住渲染

如果主循环里直接 `recv()`，网络一慢，整个窗口就冻住。
所以客户端 socket 设成**非阻塞**：每帧只问一次“现在有数据吗？有就读，没有就继续画”。

### 问题 B：20 Hz 快照直接画会跳

服务端 20 Hz，客户端 60 fps：

```text
快照:  ●────────●────────●       每 50 ms 一个
渲染:  ● ● ● ● ● ● ● ● ● ●       每 16.7 ms 一帧
```

如果每帧都画“最新快照”，方块会每 50 ms 瞬移一次。
插值用**上一帧 → 当前帧**的位置，在 50 ms 内平滑过渡。

---

## 2. 数据流

```text
socket.recv()  ──任意分片──►  FrameParser.buffer
                                   │
                                   ▼
                            next_frame() 完整帧
                                   │
                                   ▼
                          S_SNAPSHOT 解析成玩家坐标
                                   │
                     prev / curr / curr_time
                                   │
                              alpha = 0→1
                                   │
                                   ▼
                         lerp(prev, curr, alpha) → 画
```

---

## 3. 核心代码逐行讲

### 3.1 `FrameParser`：非阻塞拼帧

```python
class FrameParser:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)

    def next_frame(self):
        if len(self.buffer) < 12:
            return None
        header = bytes(self.buffer[:12])
        msg_type, seq, length = parse_header(header)

        total = 12 + length
        if len(self.buffer) < total:
            return None

        payload = bytes(self.buffer[12:total])
        del self.buffer[:total]
        return Frame(msg_type, seq, payload)
```

- `feed`：把每次 `recv` 到的字节追加到缓冲区。
- `next_frame`：数据不够就返回 `None`，**不阻塞**；够就切一条完整帧出来。
- 和阻塞版 `recv_frame` 的区别：阻塞版自己调 `recv` 等数据；这里数据由主循环喂进来。

> 这就是 D-007 说的“每帧轮询 + 自己处理部分写/缓冲”的接收半边。

### 3.2 `NetworkClient.poll()`：每帧只读一次

```python
def _read_available(self):
    while True:
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return              # 没数据了，正常
        if not data:
            self.connected = False
            return
        self.parser.feed(data)
```

- `BlockingIOError` 不是错误，是“现在没数据”。
- 循环读到 `BlockingIOError` 为止，保证这一帧把能读的都读完。
- 解析出的帧由 `poll()` 一次性返回给主循环。

### 3.3 插值：`prev / curr / alpha`

```python
prev = dict(curr)                 # 上一次快照
curr = {p.player_id: p for p in snapshot.players}
curr_time = time.perf_counter()

alpha = min(1.0, (now - curr_time) / 0.05)
x = lerp(old.x, new.x, alpha)
```

假设 P1 上一帧在 `x=100`，这一帧在 `x=200`：

| 时间（新快照后） | alpha | 画在 |
|---|---|---|
| 0 ms | 0.0 | 100 |
| 25 ms | 0.5 | 150 |
| 50 ms | 1.0 | 200 |

所以画面是**滑过去**的，不是瞬移。

> 代价：画面比服务端晚一帧（50 ms）。局域网可接受；这是用“简单”换“不预测”。

### 3.4 绘制

```python
rect = pygame.Rect(0, 0, size, size)
rect.center = (int(x), int(y))
pygame.draw.rect(screen, color, rect, border_radius=5)
```

- 方块 26×26（按窗口缩放）
- 自己的方块多一圈白边
- 网格帮助看出“在动”
- HUD 显示 tick / 人数 / FPS / 连接状态

---

## 4. 防御性代码（单独看）

| 代码 | 防的是什么 |
|---|---|
| `except BlockingIOError: return` | 非阻塞 socket 没数据是正常，不是错误 |
| `except InterruptedError: continue` | 被信号打断时重试 |
| `except OSError: connected=False` | 连接被重置/关闭，不要崩 |
| `FrameParser` 数据不够返回 `None` | 半包不阻塞、不误解析 |
| `parse_header` 校验 magic/version/length | 畸形帧快速失败 |
| `prev.get(player_id, player)` | 新玩家没有上一帧，直接用当前位置，不跳 |
| `alpha = min(1.0, ...)` | 没新快照时不要无限外推，停在最后一帧 |
| `if info.current_h < 1000: 600×800` | 小屏幕放不下 720×960 |
| `finally: net.close(); pygame.quit()` | 退出时释放 socket / 窗口 |

---

## 5. 可以跳过的语法（放心跳）

1. `pygame.Rect` / `border_radius` —— 画方块的参数，改数字就能看出效果。
2. `pygame.font.SysFont("consolas", 18)` —— 系统字体，找不到会退化。
3. `clock.tick(FPS)` —— 让循环每秒最多跑 60 次。
4. `dict[str, ...]` / `list[Frame]` 类型注解 —— 运行时不检查。
5. `screen.blit(...)` —— 把文字/图像贴到窗口上。

**不要跳过的**：`FrameParser.next_frame`、`NetworkClient.poll`、`alpha`/`lerp`、`clock.tick`。

---

## 6. 自测题（5 道）

### Q1. 为什么主循环里不能直接 `recv()`？

<details>
<summary>答案</summary>

`recv()` 默认阻塞：没有数据时线程会停在那里，窗口不刷新、不响应事件。
所以 socket 设非阻塞，每帧只读“现在能读到的”，读不到就继续画。

</details>

---

### Q2. `FrameParser` 收到半包时怎么办？

<details>
<summary>答案</summary>

留在 `self.buffer` 里，`next_frame()` 返回 `None`；下一次 `feed()` 追加新字节，
凑够 12 B 头 + length B 载荷后再切出完整帧。不阻塞、不丢数据。

</details>

---

### Q3. 插值为什么有一帧延迟？这是 bug 吗？

<details>
<summary>答案</summary>

不是 bug，是设计取舍。新快照到达时，`alpha=0`，先画“上一帧”的位置，
再用 50 ms 过渡到“当前帧”。所以画面比服务端晚 50 ms，但换来了平滑和不做预测。
如果做预测（ extrapolation），延迟更低，但网络抖动时会出现“拉回”，复杂度更高。

</details>

---

### Q4. 如果 200 ms 没有新快照，画面会怎样？

<details>
<summary>答案</summary>

`alpha` 被 `min(1.0, ...)` 限制在 1.0，画面停在最后一帧的位置，不会继续外推。
同时 HUD 的 tick 不再变化；如果连接断了，会显示 disconnected。

</details>

---

### Q5. 为什么服务端 20 Hz，客户端 60 fps？

<details>
<summary>答案</summary>

20 Hz 是**同步频率**：每 50 ms 广播一次，省带宽和 CPU。
60 fps 是**渲染频率**：画面要顺滑；中间用插值补足。
如果服务端也 60 Hz，带宽和 CPU 会成倍增加，体验提升有限。

</details>

---

## 7. 答辩话术（可直接背）

> 客户端 socket 设为非阻塞，在 pygame 主循环里每帧轮询一次，读不到数据就继续渲染，
> 所以网络卡顿不会冻住窗口。收到的字节先进入 FrameParser 的用户态缓冲区，
> 半包留到下一帧继续拼，完整帧才交给业务层。
> 服务端 20 Hz 广播快照，客户端保存前后两帧，用 50 ms 的线性插值把 20 Hz 补成 60 fps；
> 代价是画面晚一帧，但换来了不做预测的简单性和稳定画面。

---

## 8. 这一步改了哪些代码

| 文件 | 改动 |
|---|---|
| [client/main.py](../../client/main.py) | pygame 窗口、非阻塞轮询、插值、HUD |
| [client/net.py](../../client/net.py) | 非阻塞 TCP 客户端 + `poll()` |
| [client/console.py](../../client/console.py) | 原控制台客户端（调试用） |
| [protocol/framing.py](../../protocol/framing.py) | 新增 `FrameParser` |
| [tests/test_frame_parser.py](../../tests/test_frame_parser.py) | 8 个非阻塞拼帧用例 |

**怎么跑**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.main
```

想看两个方块：再开一个 `client.main`，或者用 `client.console`。

---

## 9. 现在的限制 / 下一步

- 没有键盘输入：方块是服务端占位摆动，不是你在控制。
- 只有一帧插值：没有快照延迟缓冲，网络抖动大时会不够平滑。
- 没有房间、敌机、子弹、道具。
- 没有断线重连：断开后显示提示，按 ESC 退出。

**下一步（第 7 步）**：机器人客户端。它会自动连服务端、模拟输入/移动，
用来做压测（E2/E3）和后续实验。也是从这一步开始，服务端要真正处理客户端输入。

---

## 10. 验收标准

能用自己的话说出这三句，就算过：

1. **非阻塞**：主循环每帧 `poll` 一次，读不到数据就继续画，绝不卡住。
2. **FrameParser**：半包留在用户态缓冲区，凑齐一条才返回。
3. **插值**：`alpha` 从 0 到 1，位置从上一帧线性过渡到当前帧；代价是一帧延迟。
