# 第 4 步 · 12 字节帧头（人话版）

> 对应代码：[protocol/framing.py](../../protocol/framing.py)、[protocol/messages.py](../../protocol/messages.py)、
> [server/echo_server.py](../../server/echo_server.py)、[client/echo_client.py](../../client/echo_client.py)
>
> 对应测试：[tests/test_framing.py](../../tests/test_framing.py)（19 个用例）
>
> 日期：2026-10-19

---

## 0. 一句话

给每条消息贴一张 **12 字节的快递单**：是不是我们的包裹、规则第几版、里面是什么、第几号、多大。

---

## 1. 这一步解决什么问题？

第 2 步只解决了“**这条消息有多长**”。但真实游戏里，一条 TCP 连接上会跑很多种消息：

- 客户端 → 服务端：登录、加入房间、上报按键、心跳……
- 服务端 → 客户端：玩家列表、20 Hz 快照、BOSS 换阶段、游戏结束……

如果帧头里只有长度，接收方只知道“这是一段 N 字节”，但不知道：

- 这段该交给**谁**处理？（登录？快照？）
- 它是不是**对上一条请求的回复**？
- 对端用的协议**版本和我一样**吗？
- 这真的是我们的协议，还是连错端口了？

12 字节帧头就是快递单上的五项信息：

| 快递单 | 帧头字段 | 作用 |
|---|---|---|
| 是不是我们的包裹 | `magic` | 防止连错端口 / 字节流错位 |
| 规则第几版 | `version` | 协议升级后拒绝不兼容的对端 |
| 里面是什么 | `type` | 决定交给哪个处理函数 |
| 第几号包裹 | `seq` | 请求-响应关联、算 RTT、防重放 |
| 包裹多大 | `length` | 划出消息边界（第 2 步的核心） |

---

## 2. 帧头长什么样

所有多字节字段都是**大端序**（网络字节序）。

| 偏移 | 长度 | 字段 | 类型 | 值 / 说明 |
|---|---|---|---|---|
| 0 | 2 | `magic` | uint16 | 固定 `0x4A59` |
| 2 | 1 | `version` | uint8 | 当前 `1` |
| 3 | 1 | `type` | uint8 | 消息类型；阶段 1 用 `ECHO=0x7F` |
| 4 | 4 | `seq` | uint32 | 发送方递增序号 |
| 8 | 4 | `length` | uint32 | 载荷字节数，**不含帧头** |
| 12 | N | `payload` | bytes | 载荷 |

```
+--------+---------+------+--------+--------+------------------+
| magic  | version | type | seq    | length | payload          |
| uint16 | uint8   | uint8| uint32 | uint32 | length bytes     |
+--------+---------+------+--------+--------+------------------+
|<--------------------- 12 B 帧头 --------------------->|<-- N B -->|
```

**必记**：`2 + 1 + 1 + 4 + 4 = 12`。

---

## 3. 核心代码逐行讲（必须懂的最小集合）

### 3.1 一行 `struct`

```python
HEADER = struct.Struct("!HBBII")
```

拆开看：

| 部分 | 含义 | 占几字节 |
|---|---|---|
| `!` | 网络字节序（大端） | 0 |
| `H` | unsigned short（uint16） | 2 |
| `B` | unsigned char（uint8） | 1 |
| `B` | unsigned char（uint8） | 1 |
| `I` | unsigned int（uint32） | 4 |
| `I` | unsigned int（uint32） | 4 |

所以 `HEADER.size == 12`。

`struct.Struct` 的好处：**格式只写一次，打包/解包都复用它**，比每次写 `struct.pack("!HBBII", ...)` 快，也不容易把顺序写错。

### 3.2 打包：`pack_frame()`

```python
def pack_frame(msg_type: int, seq: int, payload: bytes) -> bytes:
    if not 0 <= msg_type <= 0xFF:
        raise ProtocolError(...)
    if not 0 <= seq <= 0xFFFFFFFF:
        raise ProtocolError(...)
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(...)
    return HEADER.pack(MAGIC, VERSION, msg_type, seq, len(payload)) + payload
```

逐行：

1. **检查 type**：`uint8` 只能是 0~255。超出就报错，不让 `struct` 抛一个难懂的异常。
2. **检查 seq**：`uint32` 只能是 0~4294967295。
3. **检查载荷长度**：超过 64 KiB 就拒绝，防止“发的时候不报错，收的时候把内存吃光”。
4. `HEADER.pack(...)` 生成 12 字节帧头。
5. `+ payload` 把载荷接在后面。

> 记住：`length` 写的是 `len(payload)`，**不包含 12 字节帧头**。

### 3.3 拆包：`recv_frame()`

```python
header = recv_exact(sock, HEADER.size)
if header is None:
    return None

magic, version, msg_type, seq, length = HEADER.unpack(header)
if magic != MAGIC:
    raise ProtocolError(...)
if version != VERSION:
    raise ProtocolError(...)
if length > MAX_PAYLOAD:
    raise ProtocolError(...)

payload = recv_exact(sock, length)
if payload is None:
    raise ProtocolError(...)
return Frame(msg_type=msg_type, seq=seq, payload=payload)
```

逐行：

1. **先读满 12 字节帧头**。`recv_exact` 会循环，所以帧头被拆成几次到达也没关系。
2. 如果 `header is None`：对端在**帧边界**正常关闭，返回 `None`。
3. `HEADER.unpack(header)` 一次解出 5 个字段。
4. **先校验 magic**：不对就立刻报错，不再读载荷。
5. **再校验 version**：不兼容就拒绝。
6. **再校验 length**：超过上限就拒绝，**绝不按恶意长度去分配内存**。
7. 读满 `length` 字节载荷。
8. 如果载荷读了一半连接断了，抛 `ProtocolError`。
9. 返回 `Frame`，业务代码只关心 `msg_type / seq / payload`。

### 3.4 `Frame` 是什么

```python
@dataclass(frozen=True, slots=True)
class Frame:
    msg_type: int
    seq: int
    payload: bytes
```

它就是一个“装三个字段的小盒子”。用 `@dataclass` 后，Python 自动生成 `__init__`、`__repr__`、`__eq__`，不用手写。

- `frozen=True`：创建后不能改，防止业务代码不小心改掉 seq。
- `slots=True`：省一点内存，**初学可以完全忽略**。

使用起来就是：

```python
frame = recv_frame(sock)
print(frame.msg_type, frame.seq, frame.payload)
```

---

## 4. 防御性代码（单独看）

| 代码 | 防的是什么 |
|---|---|
| `if not 0 <= msg_type <= 0xFF` | 把“类型写错”变成清晰的 `ProtocolError`，而不是 `struct.error` |
| `if not 0 <= seq <= 0xFFFFFFFF` | 同上，防止序号溢出 |
| `if len(payload) > MAX_PAYLOAD`（发送端） | 防止自己发出一个接收端必然拒绝的包 |
| `if length > MAX_PAYLOAD`（接收端，**读载荷之前**） | 防止对端声明 4 GB 长度，先把你内存吃光（DoS） |
| `if magic != MAGIC` | 连错端口、协议不一致、字节流错位时**快速失败** |
| `if version != VERSION` | 新旧版本混连时拒绝，而不是解析出乱码 |
| `recv_exact()` 的 `remaining == n` 判断 | 区分“帧边界正常关闭”和“帧读了一半被截断” |
| 服务端捕获 `ProtocolError` 后断开 | 帧都错了，后面的字节流不可信，继续读只会更乱 |

> 一句话：**能在帧层拒绝的，就不要留给业务层猜。**

---

## 5. 可以跳过的语法（放心跳）

这些不影响你理解主流程：

1. `from __future__ import annotations`
   → 只是让类型注解延迟求值，运行逻辑不变。
2. `@dataclass(frozen=True, slots=True)`
   → 可以把它当成“自动生成构造函数的小盒子类”；`slots` 是内存优化。
3. `bytes | None`、`int` 这些类型注解
   → 只是给人看的提示，Python 运行时不会强制检查。
4. f-string 里的 `:02X` / `:04X`
   → 十六进制格式化，让日志好看，例如 `0x7F`、`0x4A59`。
5. `HEADER.size`
   → `struct` 自动算出的 12，不用背。
6. `socket.socketpair()`
   → 测试里用来造一对“真实但不出网卡”的 socket，理解成“一根两端都能读写的管子”即可。

---

## 6. 自测题（5 道，先自己说一遍）

### Q1. 12 字节帧头由哪五部分组成？各占几字节？

<details>
<summary>答案</summary>

`magic` 2 B + `version` 1 B + `type` 1 B + `seq` 4 B + `length` 4 B = **12 B**。

</details>

---

### Q2. 已经有 `length` 了，为什么还要 `magic` 和 `version`？

<details>
<summary>答案</summary>

`length` 只解决“消息边界”，不保证“这是对的协议、对的版本”。

- `magic`：连错端口、协议不一致、字节流错位时，能立刻发现“这不是我们的包”。
- `version`：协议升级后，拒绝不兼容的对端，而不是按旧规则解析新包，解析出一堆乱码。

</details>

---

### Q3. 为什么收到帧头后要先检查 `length`，再读载荷？不检查会怎样？

<details>
<summary>答案</summary>

`length` 是对端给的，不能信。攻击者可以声明 `length = 4294967295`（约 4 GB），
如果不检查就直接 `recv(4 GB)` 或分配缓冲区，内存会被瞬间吃光。

先检查 `length <= MAX_PAYLOAD`，超限就断开，**在分配内存之前失败**。

</details>

---

### Q4. `seq` 至少有哪三个用途？

<details>
<summary>答案</summary>

1. **请求-响应关联**：响应带回请求的 seq，客户端知道“这是回我的第几条”。
2. **算 RTT**：从发出 seq 到收到同一个 seq，中间的时间就是往返时延。
3. **丢包检测 / 防重放**：序号跳跃可以判断丢包；服务端可以拒绝重复 seq 的敏感请求。

</details>

---

### Q5. `recv_frame()` 什么时候返回 `None`，什么时候抛 `ProtocolError`？

<details>
<summary>答案</summary>

- **返回 `None`**：对端在**帧边界**正常关闭（一个字节都没读到就 EOF）。
- **抛 `ProtocolError`**：
  - 帧头只读到一半就断了；
  - 帧头说 10 B，载荷只给 3 B 就断了；
  - magic / version 不对；
  - 声明的 length 超过 `MAX_PAYLOAD`。

一句话：**正常断开返回 None，帧不完整或格式错误抛异常。**

</details>

---

### 附加题（不计入 5 道）. 为什么所有字段用大端？

<details>
<summary>答案</summary>

大端是网络字节序，跨平台一致。`struct` 的 `!` 明确表示大端，这样 Windows / Linux / ARM 解析同一段字节得到同一个值。

</details>

---

## 7. 答辩话术（可直接背）

> 我们的帧头固定 12 字节，包含 magic、version、type、seq、length。
> `length` 解决 TCP 粘包/拆包的边界问题；`type` 让一条连接承载多种消息；
> `seq` 用于请求-响应关联和 RTT 测量；`magic` 和 `version` 让协议错位或版本不匹配
> 在帧层快速失败。接收端先读满 12 字节帧头，校验 magic、version 和 length 之后，
> 再按 length 读载荷，因此一次 `recv` 收到半包或粘包都能正确处理。
> 帧头开销是每帧 12 字节，对 1 字节的输入包来说占比较高，这也是后续讨论
> “批量合并发送”优化的原因。

---

## 8. 这一步改了哪些代码

| 文件 | 改动 |
|---|---|
| [protocol/framing.py](../../protocol/framing.py) | 4 B 长度 → 12 B 帧头；新增 `Frame`；magic/version/type/seq 校验 |
| [protocol/messages.py](../../protocol/messages.py) | 新增临时回声类型 `ECHO = 0x7F` |
| [server/echo_server.py](../../server/echo_server.py) | 打印 `type` / `seq`；回声固定 `type=ECHO`，`seq` 原样带回 |
| [client/echo_client.py](../../client/echo_client.py) | 每条消息 `seq + 1`；校验响应 `type` / `seq` |
| [tests/test_framing.py](../../tests/test_framing.py) | 19 个用例，覆盖 12 B 帧头与各种边界 |

**怎么跑**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_framing -v
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.echo_server 9000
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.echo_client 127.0.0.1 9000
```

> 想按字节看一条消息：运行 `python -X utf8 -m tools.trace_one_message`（纯学习脚本，不改 server/client）。
> 它会打印 `"hi"` 的 14 个字节、半包时的每次 recv、以及两条帧粘在一起时如何分开。

---

## 9. 现在的限制 / 下一步

- 服务端仍然**一次只服务一个客户端**，阻塞在 `accept` / `recv` 上。
- 还没有 20 Hz tick，也没有广播。
- 客户端还是阻塞 socket，第 6 步才会改成非阻塞 + 插值。
- 帧层只校验“结构”，不校验“这个 type 合不合法”；业务分发留到第 5 步。

**下一步（第 5 步）**：20 Hz tick + 广播。按人话笔记制度，**你确认这份笔记看懂了，我才开始第 5 步**。

---

## 10. 验收标准

能用自己的话说出下面三句，就算过：

1. 12 字节帧头解决了“长度之外的四个问题”：是不是我们的包、版本、消息类型、请求序号。
2. `recv_frame()` 的顺序是：读满 12 B → 校验 → 再读 length B；**校验必须在读载荷之前**。
3. 正常断开返回 `None`，帧不完整 / 格式错误抛 `ProtocolError`。
