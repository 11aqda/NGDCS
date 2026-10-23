# 项目进度

> **新会话请先读这份文件**，再读 `DECISIONS.md`，即可接上全部上下文。
> 维护约定：每次会话结束前更新本文件。

最后更新：2026-10-24
当前阶段：**阶段 1：第 8 步 8a「占位实体 + 指标落盘」完成 → 下一步：8b 跑 E9（⚠️ 开工前需先拍板一件事，见 §2.14 末尾）**

---

## 0. 项目背景

- **性质**：本科毕业设计（网络工程专业）
- **题目**：《基于 C/S 架构的网络游戏数据通信系统设计与实现》
- **核心交付物**：数据通信系统（自定义协议 + 服务端 + 客户端通信模块）
- **游戏的角色**：只是验证通信系统的**应用场景**，不需要做得很复杂
- **重仓技术点**：TCP 粘包/拆包、IO 多路复用模型、并发模型、序列化方案对比、Wireshark 抓包

> 答辩话术：游戏只是验证通信系统的应用场景。

---

## 1. 关键路径速查（新会话必看）

### 1.1 路径

| 用途 | 路径 |
|---|---|
| 项目根目录 | `E:\PythonProject` |
| 虚拟环境解释器 | `E:\PythonProject\.venv\Scripts\python.exe` |
| Redis 服务端 | `D:\Tools\Redis\redis-server.exe` |
| Apifox | `D:\Apps\Apifox` |
| MySQL 客户端 | `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe` |

**pip 装包务必带镜像源**（默认 PyPI 会卡死）：

```
E:\PythonProject\.venv\Scripts\python.exe -m pip install <包名> -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir --progress-bar off
```

**venv 无法用 `Activate.ps1` 激活**（ExecutionPolicy 限制），一律直接调用上面的解释器全路径。

### 1.2 环境清单（⭐ **权威** —— 若其他章节与本节冲突，以本节为准）

#### ✅ 已就绪

| 类别 | 项 | 版本 / 状态 |
|---|---|---|
| 语言 | Python | 3.13.3（系统 + venv） |
| 版本控制 | Git | 2.47.1.windows.2 |
| 数据库 | MySQL Server | 8.0.41，服务 `MySQL80` **运行中** |
| 数据库 | 库 `myproject` + 用户 `django_user` | 已建（utf8mb4 / utf8mb4_unicode_ci） |
| 缓存 | Redis 服务端 | 5.0.14.1，已解压到 `D:\Tools\Redis`（**未启动**） |
| 接口调试 | Apifox | 2.8.50，已装于 `D:\Apps\Apifox` |
| 虚拟化 | VMware Workstation + Ubuntu Desktop | 已装；**仅用 VMnet1 仅主机模式**，桥接 WiFi 已实测不可用（D-016） |
| 仓库 | Git | `master` 分支，已提交 19 次 |

**venv 已装 29 个包：**
```
asgiref 3.12.1 · certifi 2026.7.22 · cffi 2.1.1 · charset-normalizer 3.5.1 · contourpy 1.4.0
cryptography 50.0.2 · cycler 0.12.1 · Django 5.2.18 · fonttools 4.67.0 · idna 3.20
kiwisolver 1.5.1 · matplotlib 3.11.2 · numpy 2.5.4 · packaging 26.3 · pillow 13.0.0
pip 26.2.1 · psutil 7.2.2 · pycparser 3.11 · pygame 2.6.1 · PyMySQL 1.2.3
pyparsing 3.3.3 · python-dateutil 3.0.0 · redis 8.1.0 · requests 2.34.2 · six 1.17.0
sqlparse 0.6.0 · tzdata 2026.5 · urllib3 2.8.0
```

> **2026-10-24 新增**：`matplotlib 3.11.2` + `psutil 7.2.2`（8a 出图与采集 CPU/内存），
> 连带装进 `numpy 2.5.4` / `pillow` / `fonttools` / `contourpy` / `kiwisolver` /
> `cycler` / `packaging` / `pyparsing` / `python-dateutil` / `six`。
> **`numpy` 是 matplotlib 的依赖，不是我们主动要用的** ——
> §1.2 原本标的是「实体数多时提性能，⚪ 按需」，目前游戏逻辑仍然不用它。

#### ❌ 待安装

| 项 | 用途 | 优先级 | 装法 |
|---|---|---|---|
| **Wireshark** | 抓包验证（毕设必备） | 🔴 必须 | **图形界面，需手动安装** |
| `djangorestframework` | HTTP 接口层（D-005） | 🔴 必须 | pip |
| `pytest` | 单元测试 | 🟡 可选 | **暂不装**：已用标准库 `unittest`（现有 153 个用例） |
| ~~`matplotlib`~~ | ~~论文出 19 张图~~ | ✅ **已装 2026-10-24** | 3.11.2 |
| ~~`psutil`~~ | ~~实验采集 CPU / 内存~~ | ✅ **已装 2026-10-24** | 7.2.2 |
| ~~`numpy`~~ | ~~实体数多时提性能~~ | ⚪ **已随 matplotlib 装入** | 2.5.4（**未主动使用**） |

> **E9 开始前仍需**：装 **Wireshark**（E7 抓包用，图形界面需手动装）。
> `djangorestframework` 是第 10 步（HTTP 层）的事，不急。

**一键安装命令（原样保留，现在只剩 djangorestframework 待装）：**
```
E:\PythonProject\.venv\Scripts\python.exe -m pip install djangorestframework -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir --progress-bar off
```

**已验证可用的安装命令（2026-10-24 实际执行）**：
```
E:\PythonProject\.venv\Scripts\python.exe -m pip install matplotlib psutil -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir --progress-bar off
```

#### ⚠️ 明确**不需要**的（避免以后误装）

| 项 | 原因 |
|---|---|
| `django-redis` | 我们用 `redis` 包直接操作 ZSET，**不走 Django 缓存框架** |
| `mysqlclient` | 已定用 PyMySQL（见 D-001） |
| `pyinstaller` | 不打包分发 |
| `pygame-menu` | 用几何绘制自绘 UI |
| `clients` / `channels` | 实时数据走**自定义 TCP**，不用 WebSocket |

#### 其他待办

- [ ] **启动 Redis**（双击或命令行跑 `D:\Tools\Redis\redis-server.exe`，需手动，没设成服务）
- [ ] 建 `requirements.txt`（把上面已装的 16 个包固化下来）
- [ ] 建 `README.md`（怎么启动）
- [ ] 建 `docs\BACKLOG.md`（其他文档引用了它，但还没建）
- [ ] 把原飞机大战代码移入 `legacy_game\`

---

## 2. 已完成

### 2.1 工具与环境

| 组件 | 版本 | 位置 | 状态 |
|---|---|---|---|
| Git | 2.47.1.windows.2 | 系统 | 已装 |
| Python | 3.13.3 | 系统 + `.venv` | 已装 |
| pygame | 2.6.1 | `.venv` | 已装 |
| Django | **5.2.18 LTS** | `.venv` | 已装 |
| PyMySQL | 1.2.3 | `.venv` | 已装 |
| cryptography | 50.0.2 | `.venv` | 已装 |
| redis（Python 客户端） | 8.1.0 | `.venv` | 已装 |
| requests | 2.34.2 | `.venv` | 已装 |
| MySQL Server | 8.0.41 | 系统服务 `MySQL80` | 运行中 |
| Redis Server | 5.0.14.1 | `D:\Tools\Redis` | 已解压，需手动启动 |
| Apifox | 2.8.50 | `D:\Apps\Apifox` | 已安装 |

**venv 依赖现状**：asgiref 3.12.1、certifi、cffi 2.1.1、charset-normalizer、Django 5.2.18、idna、pygame 2.6.1、PyMySQL 1.2.3、pycparser、redis 8.1.0、requests 2.34.2、sqlparse、tzdata、urllib3、cryptography 50.0.2、pip 26.2.1

### 2.2 MySQL

| 项 | 值 |
|---|---|
| 数据库 | `myproject` |
| 字符集 / 排序规则 | `utf8mb4` / `utf8mb4_unicode_ci` |
| 应用用户 | `django_user@localhost` |
| 用户密码 | `123456`（本地开发用，**上线前必须改**） |
| 权限 | `GRANT ALL PRIVILEGES ON myproject.* TO django_user@localhost` |
| root 密码 | `123456` |
| 认证插件 | `caching_sha2_password` |
| `validate_password` | 未启用 |

**已验证**：Django 5.2.18 → PyMySQL → MySQL 8.0.41 全链路连通。

### 2.3 Git 仓库

- 位置：`E:\PythonProject\.git`
- 分支：`master`
- 首次提交：`31f881d chore: 初始化仓库，加入 pygame 飞机游戏源码与素材`
- 已跟踪 49 个文件（代码 + 文档 + 素材）
- 远端：无（纯本地）
- `.gitignore` 内容：`.venv/`、`__pycache__/`、`.idea/`、`*.pyc`

### 2.4 现有游戏代码（**未做任何改动**）

```
plane-game.py   主循环 / 入口
player.py       HeroPlane 玩家机
enemy.py        EnemyPlane 敌机
bullet.py       Bullet / EnemyBullet
collision.py    碰撞检测
control.py      键盘控制
http_test.py    与游戏无关的 requests 测试
```

素材：`hero.png`(40×50)、`enemy0.png`(20×15)、`bullet.png`、背景 `1a48eaddc6dbe8c80b3c0ac45fac0592.jpg`、音乐 `冒险岛游戏 - 天空之城.mp3`

### 2.5 本文件所在目录

`E:\PythonProject\docs\` —— `PROGRESS.md`（本文件）、`DECISIONS.md`、
`01-系统架构.md` ~ `04-API接口设计.md`、`BACKLOG.md`、`notes\`（人话笔记，见 §4.5）

### 2.6 阶段 1 · 第 1 步：回声服务器（2026-10-19）

| 文件 | 说明 |
|---|---|
| `server\echo_server.py` | 阻塞式单客户端回声服务器，监听 `0.0.0.0:9000` |
| `client\echo_client.py` | 命令行回声客户端，打印回显、字节数与 RTT |

**验证记录**：

- `127.0.0.1` 与 `10.140.71.127` 均可连通，中英文（UTF-8）回显正确
- 发送 1100 B 时，客户端一次 `recv(1024)` 只拿到 1024 B → **证明 TCP 是字节流，没有消息边界**
- 客户端强制断开时，服务端捕获 `ConnectionResetError`，进程继续服务下一个连接
- 回环 RTT 约 **0.03~0.14 ms**

### 2.7 阶段 1 · 第 2 步：长度前缀（2026-10-19）

| 文件 | 状态 | 说明 |
|---|---|---|
| `protocol\framing.py` | 🆕 新增 | 4 字节大端长度 + 载荷；`pack_frame` / `send_frame` / `recv_exact` / `recv_frame` |
| `protocol\__init__.py` | 🆕 新增 | 协议包 |
| `server\__init__.py` | 🆕 新增 | 服务端包（配合 `python -m`） |
| `client\__init__.py` | 🆕 新增 | 客户端包（配合 `python -m`） |
| `server\echo_server.py` | ✏️ 修改 | 改用帧收发；协议错误时断开该连接 |
| `client\echo_client.py` | ✏️ 修改 | 收发都按帧；1100 B 消息不再截断 |

**帧格式（本步）**：

```
+--------+---------------------------+
| length |          payload          |
| uint32 |       length bytes        |
+--------+---------------------------+
  length 只算载荷，不含自己这 4 字节；MAX_PAYLOAD = 64 KiB
```

**验证记录**：

- **粘包**：两条帧一次 `sendall` → 服务端正确拆成 `b'one'` / `b'two'`
- **半包**：先发帧头，隔 0.3 s 再发载荷 → 正确还原 `b'hello-half'`
- **空载荷**：`length=0` → 正常回显 `b''`
- **超大包**：声明 1,000,000 B > 64 KiB → 服务端抛 `ProtocolError` 并断开，客户端收到 EOF
- **大消息**：1100 B 完整回显（第 1 步只收到 1024 B）
- **中文**：UTF-8 载荷 12 B 原样往返

**运行方式（改为模块方式）**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.echo_server 9000
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.echo_client 127.0.0.1 9000
```

> `-X utf8` 只影响当前 Python 进程的编码，不是环境变量；不写也能跑，但中文日志在管道/后台输出时可能乱码。

### 2.8 阶段 1 · 第 3 步：帧边界单元测试（2026-10-19）

| 文件 | 说明 |
|---|---|
| `tests\test_framing.py` | 15 个用例，覆盖半包 / 粘包 / 边界 / 超大包 / 空载荷 / 截断 / EOF |
| `tests\__init__.py` | 测试包 |

**测试方法**：

- `FakeSocket` 精确控制每次 `recv(n)` 返回多少字节，不依赖真实网络的到达方式
- 另有一个 `socket.socketpair()` 用例，验证 `send_frame` 与 `recv_frame` 在**真实 socket** 上能对接

**覆盖矩阵**：

| 场景 | 对应用例 |
|---|---|
| 半包（帧头 / 载荷被拆） | `test_split_at_every_byte`（每个字节位置切）、`test_one_byte_at_a_time` |
| 粘包（一次收到 N 条） | `test_sticky_two_frames`、`test_five_frames_in_one_chunk` |
| 边界（长度恰好） | `test_max_payload_accepted` |
| 超大包 | `test_oversized_length_rejected_before_payload`、`test_pack_too_large_rejected` |
| 空载荷 | `test_empty_payload` |
| 截断 / EOF | `test_truncated_header_raises`、`test_truncated_payload_raises`、`test_clean_eof_returns_none` |
| 二进制安全 | `test_round_trip_binary_safe`（载荷含 `\n` / `\x00`） |
| 真实 socket | `test_send_frame_over_real_socketpair` |

**运行**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -t . -v
```

**结果**：`Ran 15 tests in 0.002s — OK`。

> `越界坐标` 属于编解码层，等第 4 步 `codec.py` 实现后再测。

### 2.9 阶段 1 · 第 4 步：12 字节帧头（2026-10-19）

| 文件 | 状态 | 说明 |
|---|---|---|
| `protocol\framing.py` | ✏️ 修改 | 4 B 长度 → 12 B 帧头；`recv_frame()` 返回 `Frame` |
| `protocol\messages.py` | 🆕 新增 | 阶段 1 临时回声类型 `ECHO = 0x7F` |
| `server\echo_server.py` | ✏️ 修改 | 打印 type/seq；回声固定 `type=ECHO`、`seq` 原样返回 |
| `client\echo_client.py` | ✏️ 修改 | 每条消息 `seq + 1`；校验响应的 type/seq |
| `tests\test_framing.py` | ✏️ 修改 | 按 12 B 帧头重写，**19 个用例** |
| `docs\notes\02-12byte-header-人话版.md` | 🆕 新增 | 人话笔记（按 2026-10-19 制度） |

**帧头（所有多字节字段为大端）**：

| 偏移 | 长度 | 字段 | 类型 | 值 / 说明 |
|---|---|---|---|---|
| 0 | 2 | `magic` | uint16 | `0x4A59` |
| 2 | 1 | `version` | uint8 | `1` |
| 3 | 1 | `type` | uint8 | 消息类型；阶段 1 用 `ECHO=0x7F` |
| 4 | 4 | `seq` | uint32 | 发送方递增序号 |
| 8 | 4 | `length` | uint32 | 载荷字节数（不含帧头） |
| 12 | N | `payload` | bytes | 载荷 |

**验证记录**：

- 19 个单元测试全部通过（`0.002 s`）
- 端到端：`seq=1/2` 正确回显，`type=0x7F`；1100 B 完整；中文 UTF-8 正确
- 覆盖 magic / version 错误、type/seq 越界、超大包、截断、空载荷、粘包、半包

### 2.10 阶段 1 · 第 5 步：asyncio + 20 Hz tick + 广播（2026-10-21）

| 文件 | 状态 | 说明 |
|---|---|---|
| `server\main.py` | 🆕 新增 | asyncio 服务端；多客户端；20 Hz tick；广播 `S_SNAPSHOT` |
| `client\console.py` | 🆕 新增 | 控制台占位客户端（第 6 步从 `client/main.py` 移出） |
| `protocol\snapshot.py` | 🆕 新增 | 快照头（13 B）+ 玩家条目（11 B）编解码 |
| `protocol\framing.py` | ✏️ 修改 | 新增 `parse_header`、`recv_frame_async`、`send_frame_async` |
| `protocol\messages.py` | ✏️ 修改 | 新增 `S_WELCOME=0x7C`、`S_SNAPSHOT=0x84`、`WELCOME` |
| `tests\test_framing_async.py` | 🆕 新增 | asyncio 接收的 5 个用例 |
| `tests\test_snapshot.py` | 🆕 新增 | 快照编解码的 7 个用例 |
| `docs\notes\03-tick-broadcast-人话版.md` | 🆕 新增 | 人话笔记 |

**本步范围**：

- 客户端连上 → 服务端分配 `player_id` / `color`（`S_WELCOME` 临时消息）
- 每 50 ms tick：占位玩家左右摆动 → 向所有客户端广播 `S_SNAPSHOT`
- 快照只带玩家；敌机 / 子弹 / 道具计数为 0
- **不做**房间、客户端输入、渲染 / 插值

**验证记录**：

- 31 个单元测试全部通过（`0.156 s`）
- 两个客户端同时连接：`player 1/2` 都收到同一份快照，能看到彼此坐标在变
- 客户端断开后服务端清理，不残留玩家

**运行**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.console Alice
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.console Bob
```

### 2.11 阶段 1 · 第 6 步：pygame 渲染 + 插值（2026-10-21）

| 文件 | 状态 | 说明 |
|---|---|---|
| `client\main.py` | ✏️ 重写 | pygame 720×960 占位客户端；非阻塞轮询 + 一帧线性插值 + HUD |
| `client\net.py` | 🆕 新增 | 非阻塞 TCP 客户端；每帧 `poll()` 一次 |
| `client\console.py` | 🆕 新增 | 原控制台客户端，保留用于调试 |
| `protocol\framing.py` | ✏️ 修改 | 新增 `FrameParser`（非阻塞拼帧） |
| `tests\test_frame_parser.py` | 🆕 新增 | 8 个非阻塞拼帧用例 |
| `docs\notes\04-render-interpolation-人话版.md` | 🆕 新增 | 人话笔记 |

**本步范围**：

- 非阻塞 socket + 每帧轮询（D-007），主循环不会卡在 `recv`
- 20 Hz 快照 → 前后两帧线性插值 → 60 fps 渲染
- 720×960 竖版窗口；桌面高度 < 1000 px 时自动降为 600×800
- 占位方块 + 网格 + HUD（tick / 人数 / FPS / 连接状态）
- **不做**键盘输入、房间、游戏内容

**验证记录**：

- 39 个单元测试全部通过（`0.100 s`）
- pygame 客户端启动，窗口 `720×960`，能连上服务端并保持渲染
- 控制台客户端同时连入：`P1/P2` 在同一 tick 的坐标一致
- 屏幕尺寸降级、断线提示代码已写；未专门在小于 1000 px 的屏幕上验证

**运行**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.console Bob 10
```

> 想看两个方块：开两个 `client.main` 窗口，或一个 `client.main` + 一个 `client.console`。

### 2.12 阶段 1 · 第 7 步 7a：观察者机器人（2026-10-22）

| 文件 | 状态 | 说明 |
|---|---|---|
| `bot\main.py` | 🆕 新增 | asyncio 机器人农场；N 个连接；ramp-up；指标汇总 |
| `bot\__init__.py` | 🆕 新增 | 机器人包 |
| `tests\test_bot_metrics.py` | 🆕 新增 | 3 个指标汇总用例 |
| `server\main.py` | ✏️ 修改 | 客户端断开不再打印 error，只保留 joined / left |
| `docs\notes\05-bot-farm-人话版.md` | 🆕 新增 | 人话笔记 |

**7a 范围**：

- 一个进程开 N 个观察者 bot：连接 → 收 welcome → 收 snapshot
- CLI：`--clients` / `--duration` / `--ramp` / `--out`
- 指标：连接数、快照数、字节数、间隔 p50 / p95、错误数
- **不发输入、不改服务端协议**；7b 再加 `C_INPUT` + heartbeat

**验证记录**：

- 42 个单元测试全部通过（`0.141 s`）
- 20 bots / 5 s / ramp 10：**20/20**，1996 快照，p50 47.3 ms，p95 62.9 ms，errors 0
- 50 bots / 5 s / ramp 20：**50/50**，4988 快照，p50 47.5 ms，p95 63.1 ms，errors 0
- 10 bots 快速回归：598 快照，errors 0；服务端日志只有 joined / left
- ⚠️ 以上是本机 loopback 数据，**不是最终网络实验数据**（D-016）

**运行**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --ramp 5
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 50 --duration 5 --ramp 20 --out bot_50.json
```

### 2.13 阶段 1 · 第 7 步 7b：输入 + heartbeat（2026-10-23）

| 文件 | 状态 | 说明 |
|---|---|---|
| `protocol\world.py` | 🆕 新增 | 世界尺寸 720×960 / 边距 20（服务端边界与客户端缩放共用一份） |
| `server\movement.py` | 🆕 新增 | 运动学纯函数：`keys_to_dx` / `clamp_x` / `apply_input` |
| `server\stats.py` | 🆕 新增 | `TickStats`：tick 耗时 p50 / p95 + 每秒输入帧数 |
| `bot\agent.py` | 🆕 新增 | 单个机器人：3 协程（收 / 输入 / 心跳）+ `BotConfig` / `BotResult` |
| `protocol\messages.py` | ✏️ 修改 | `C_INPUT=0x06` / `C_HEARTBEAT=0x07` / `S_HEARTBEAT_ACK=0x87` + struct + `now_ms` / `rtt_ms` |
| `server\main.py` | ✏️ 修改 | `dispatch` 分发、输入保质期、超时清理、tick 打点、argparse；**删掉 `sin` 占位摆动** |
| `bot\main.py` | ✏️ 修改 | 新 CLI（`--input-hz` / `--heartbeat` / `--key-hold` / `--seed`）+ 新指标 |
| `client\net.py` | ✏️ 修改 | `send()` / `flush()` 发送队列 + `MAX_OUTBOX`（7a 遗留 TODO） |
| `client\main.py` | ✏️ 修改 | 键盘 → `C_INPUT`、心跳、HUD 显示 RTT / keys |
| `client\console.py` | ✏️ 修改 | 加心跳（不加会被 15 s 超时踢）+ 打印 RTT |
| `tests\test_input.py` | 🆕 新增 | 12 个用例：keys 编解码、保留位、输入保质期 |
| `tests\test_heartbeat.py` | 🆕 新增 | 14 个用例：心跳编解码、32 位回绕 RTT、超时判定 |
| `tests\test_movement.py` | 🆕 新增 | 11 个用例：左 / 右 / 同按 / 边界 / 确定性 |
| `tests\test_tick_stats.py` | 🆕 新增 | 7 个用例：分位数、窗口重置 |
| `tests\test_bot_metrics.py` | ✏️ 修改 | 覆盖新增的输入 / 心跳 / RTT 指标 |
| `docs\notes\06-input-heartbeat-人话版.md` | 🆕 新增 | 人话笔记 |

**7b 范围**：

- 上行链路接通：`C_INPUT`（1 字节位掩码，**只发意图不发坐标**，D-006）
- 服务端权威运动学：**整数 15 px/tick**（300 px/s）、左右同按抵消、边界钳制
- **输入保质期 0.5 s**：太久没收到新输入即视为松手，防「幽灵移动」
- 心跳：`C_HEARTBEAT` → `S_HEARTBEAT_ACK`，**原样回显 `client_time`**（RTT 不依赖两端对表）
- 超时：15 s（3 × 心跳间隔），**每秒检查一次**；判定 / 关闭 / 清理三段分离
- 机器人：`--input-hz 0` 就是 7a 的观察者；默认发心跳（否则会被踢）
- 服务端每秒打印 tick 耗时 + 输入帧速率（E9 的数据源）
- **不做**：房间、认证、防洪、`S_PLAYER_LEAVE`（D-012 全量真相已覆盖）、批量合并发送

**验证记录**：

- **88 个单元测试全部通过**（0.10 s；7a 时是 42 个）
- 10 输入 bot / 8 s：**10/10**，1600 快照、1600 输入、20/20 心跳 ack，
  间隔 p50 47.3 / p95 62.9 ms，RTT p50 0.0 / p95 1.0 ms，errors 0
- 5 观察 bot（`--input-hz 0`）/ 6 s：598 快照、**0 输入**、10/10 ack，errors 0
- 服务端 tick：空载 **0.005 ms**；5 观察 bot **0.256 ms**；10 输入 bot **0.33~0.38 ms**（p95 ≤ 0.47）
- 服务端输入速率：10 bot × 20 Hz → **`in 198~203/s`**；观察者 `in 0/s`（对照成立）
- **位移验证**：按左 1 s 位移 **−285 px**、按右 **+285 px**、左右同按 **0**、松手后连续 8 帧**完全静止**
- **超时验证**：`--timeout 5` 下心跳 2 s → 活满 12 s；什么都不发 → 约 6 s 被踢
- pygame 客户端（无头运行）：服务端统计 **`in 20/s`**，与设计一致
- ⚠️ 以上是本机 loopback 数据，**不是最终网络实验数据**（D-016）

**运行**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m client.main
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --ramp 5
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 20 --duration 10 --input-hz 0
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main 9527 --timeout 5
```

> 想看两个方块都在动：开两个 `client.main` 窗口，各自按 ←/→。
> 想复现 7a 的「纯广播基线」：服务端 `--timeout 0` + 机器人 `--input-hz 0 --heartbeat 0`。

### 2.14 阶段 1 · 第 8 步 8a：占位实体 + 指标落盘（2026-10-24）

> **为什么叫 8a**：第 8 步原计划是「数据采集 + 压测实验」，但开工前发现
> **E9 的自变量根本不存在** —— 服务端只有玩家方块，敌机/子弹连数据结构都没有
> （`unpack_snapshot()` 还会主动拒绝非 0 的敌机计数）。所以拆成
> **8a（造实体 + 修通采集链路，本次）** 和 **8b（跑 E9 六档位出图，下次）**，
> 和 7a/7b 一样先隔离变量。详见 D-024。

| 文件 | 状态 | 说明 |
|---|---|---|
| `server\entities.py` | 🆕 新增 | 占位实体 World：8 方向整数表、移动 / 出屏剔除 / **补足到目标数量** |
| `server\metrics.py` | 🆕 新增 | 指标落盘 CSV + `cpu_percent_from_deltas`（单核占用） |
| `tools\plot.py` | 🆕 新增 | 出图 6-17 / 6-18 / 6-19 |
| `protocol\snapshot.py` | ✏️ 修改 | 补齐敌机(9 B) / 子弹(8 B) / 道具(7 B) 条目；`boss_present` 改为**推导** |
| `protocol\messages.py` | ✏️ 修改 | 实体类型常量 + 角度基准常量 |
| `server\stats.py` | ✏️ 修改 | 新增收发流量、快照体积统计 |
| `server\main.py` | ✏️ 修改 | `--enemies` / `--bullets` / `--seed` / `--scenario` / `--metrics`；接入 World 与采集 |
| `client\main.py` | ✏️ 修改 | 渲染敌机与子弹；HUD 显示 `e/b` |
| `tests\test_snapshot.py` | ✏️ 重写 | 20 个用例：四类条目字节数、计数上限、BOSS 推导、尾部垃圾 |
| `tests\test_entities.py` | 🆕 新增 | 25 个用例：角度换算、剔除、**数量恒定**、ID 回绕、可复现 |
| `tests\test_metrics.py` | 🆕 新增 | 19 个用例：CSV 追加写、表头唯一、CPU 量纲、psutil 缺失降级 |
| `tests\test_plot.py` | 🆕 新增 | 13 个用例：解析、按场景切分、丢热身窗口、三图冒烟 |
| `tests\test_tick_stats.py` | ✏️ 修改 | 覆盖新增的流量 / 快照体积字段 |
| `docs\02-协议设计.md` | ✏️ 修改 | 补 **0° = 正上、顺时针** 的角度基准（此前**未定义**）；四类条目与快照体积补实测 |
| `docs\notes\07-placeholder-entities-人话版.md` | 🆕 新增 | 人话笔记 |
| `.gitignore` | ✏️ 修改 | 忽略 `data/`（实验数据）与 `.cache/`（matplotlib 缓存） |

**8a 范围**：

- 四类快照条目**全部实现**，字节数与 `02 §6.2` 逐字节对齐
- **占位实体**：无 AI、匀速直线（敌机 3 px/tick 向下；子弹 12 px/tick 按 angle 飞）
- **出屏即剔除**（D-012 的落地，同时杜绝负坐标进 `uint16`）
- **数量恒定**：出屏/被清除后立即补足 → E9 自变量稳定
- **每秒一行** CSV：tick 耗时、快照体积、收发流量、CPU、内存
- `tools/plot.py` 出图 6-17 / 6-18 / 6-19（含中文字体与 matplotlib 缓存目录处理）
- **不做的**：敌机 AI / 碰撞 / 伤害 / 掉落 / 波次 / BOSS（第 11 步）

**验证记录**：

- **153 个单元测试全部通过**（0.63 s；7b 时是 88 个）
- 冒烟跑（**不是 E9 正式数据**：每档只跑约 20 秒、只跑了两档）：

  | 场景 | 实体 | tick_ms | 快照 | 下行/客户端 | CPU |
  |---|---|---|---|---|---|
  | 30 敌机 + 200 子弹 | 234 | 0.560 ms | **1926 B** | **38.7 KB/s** | 0.2 % |
  | 100 敌机 + 800 子弹 | 904 | 1.396 ms | **7356 B** | **148.6 KB/s** | 1.7 % |

- **逐字节核对通过**：`13 + 4×11 + 30×9 + 200×8 = 1927 B`（实测 1927）；
  `13 + 4×11 + 100×9 + 800×8 = 7357 B`（实测 7357）✅
- **带宽线性度**：实体数 3.86 倍 → 下行带宽 3.84 倍 ✅
- **CPU 量纲已校验**：忙等 0.5 s/秒 → 读 **49.95%**；忙等 0.1 s/秒 → **9.37%**；空闲 → **0.0%**
- 三张图已产出到 `docs\figures\`，中文标题正常（非方块）
- ⚠️ 仍是本机 loopback，**不是最终网络实验数据**（D-016）

**⚠️ 8b 开工前必须先拍板的一件事：E9 的 CPU 曲线要不要弯？**

占位实体**没有碰撞检测**，而 `01 §7.1` 那份基准（100 敌机 + 800 子弹 = 4.37 ms/tick、87.3% 单核）
**包含了「朴素 O(子弹×敌机) 碰撞检测」= 每 tick 8 万次判定**，那才是 CPU 大头。
我们实测同规模只有 1.396 ms / 1.7%。

| 方案 | 结果 | 代价 |
|---|---|---|
| **A. 只测通信层开销**（现状） | 图 6-18 很强；图 6-17/6-19 很平。论文结论：「通信层不是瓶颈，瓶颈在游戏逻辑」 | 无 |
| **B. 加一个 O(子弹×敌机) 的占位碰撞判定** | 复现 §7.1 的算力剖面，三张图都能出拐点 | 写一段第 11 步会被替换掉的临时逻辑 |

> 两个结论都成立、都能写进论文，但**图 6-19 的"50% 舒适线"只有 B 才碰得到**。
> D-011 的「敌机 ≤ 30、子弹 ≤ 300」是**基于 B 那份基准**定的 ——
> 如果走 A，那条约束在论文里的论证链会断一半。**建议 B**，但要你点头。

**运行**：

```powershell
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m server.main --enemies 30 --bullets 200 --scenario E9-e30-b200-01
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m bot.main --clients 4 --duration 180
E:\PythonProject\.venv\Scripts\python.exe -X utf8 -m tools.plot --csv data/server_metrics.csv --out docs/figures
```

> 指标默认写到 `data\server_metrics.csv`（**默认开启**，怕忘了采数据）；
> 随手试玩不想留数据就加 `--no-metrics`。场景信息另写 `data\server_scenario.csv`。

---

## 3. 已踩过的坑（重要，别再踩）

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | `Activate.ps1` 报「禁止运行脚本」 | ExecutionPolicy 全 Undefined（默认 Restricted） | 不激活，直接调 `.venv\Scripts\python.exe`；或 cmd 里用 `activate.bat` |
| 2 | pip 安装卡死、无输出 | 默认 PyPI 路由不通 + 被中断的 pip 进程残留 + 管道块缓冲 | ① 换清华镜像 `-i` ② 清掉残留 python 进程 ③ 加 `--no-cache-dir --progress-bar off` |
| 3 | Django 6.1.2 报 `MySQL 8.4 or later is required` | Django 6.1 把 MySQL 最低版本提到 8.4，本机是 8.0.41 | 降 Django 到 5.2 LTS（详见 DECISIONS.md D-002） |
| 4 | PyMySQL 连 MySQL 8 可能报 cryptography 缺失 | MySQL 8 默认 `caching_sha2_password` 认证 | 在 venv 装 `cryptography` |
| 5 | GitHub 无法访问 | 网络层封锁，`github.com:443` 超时 | 开加速器后用 `curl --ssl-no-revoke`（schannel 吊销检查不可达） |
| 6 | `mysql` 命令找不到 | MySQL `bin` 目录不在 PATH（按要求未改环境变量） | 用全路径调用 |
| 7 | 连**本机局域网 IP**，RTT 仍 < 1 ms、传输速度 1000+ MB/s | Windows 把发往本机地址的流量**短路到回环**，不经过网卡 | 用网卡计数器验证：传 16 MB 后 WLAN 收发增量≈0；真实网络实验需虚拟机/第二台设备（见 D-016） |
| 8 | `python server\echo_server.py` 报 `ModuleNotFoundError: No module named 'protocol'` | 直接跑脚本时 `sys.path[0]` 是脚本目录（`server\`），不是项目根 | 从项目根用 `python -m server.echo_server` 运行 |
| 9 | 后台 / 管道运行服务端时，`print` 的日志迟迟看不到 | Python 的 stdout 在**非终端**下是块缓冲（攒满才刷）；日志量小就一直不刷 | 加 `-u`（`python -X utf8 -u -m server.main`）；这也是 §2.7 提过 `-X utf8` 要配合的场景 |
| 10 | 写验证脚本时「等 0.1 s 没有数据就算读干净」**死循环** | 快照每 50 ms 一帧，**永远不会有 100 ms 静默** | 判断「流停了」不能用「静默超时」；改成固定时长（如读 0.7 s 再丢弃），或按 tick 号判断 |
| 11 | 跑完测试，**仓库根目录冒出一个 `matplotlib-xxxx/`** | matplotlib 默认把字体缓存写到 `C:\Users\<用户>\AppData\Local\matplotlib`；那个目录不可写时，它**退而在当前工作目录建临时目录** | 在 `import matplotlib` **之前**设 `MPLCONFIGDIR` 指向项目内 `.cache/matplotlib`（`tools/plot.py` 已处理），并把 `.cache/` 加进 `.gitignore` |
| 12 | 出图时中文标题全变成**方块** | matplotlib 默认字体不含中文 | `plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", ...]`，并关掉 `axes.unicode_minus`（负号也会变方块） |
| 13 | 一次性实验脚本跑完，**仓库根目录多出一个 `tmpXXXXXXXX/`** | `tempfile.mkdtemp()` 在 `TMPDIR` / `TEMP` / `TMP` 都取不到时，会退而使用**当前工作目录** | 写实验脚本时 `tempfile.mkdtemp(dir=...)` 显式指定目录，别依赖环境变量（和坑 #11 是同一类"临时目录落到仓库里"的问题） |

---

## 4. 下一步计划

### 4.0 设计阶段（当前）

| 文档 | 状态 |
|---|---|
| `01-系统架构.md` | ✅ 已定稿（**竖版飞机大战**，含实测性能约束） |
| `02-协议设计.md` | ✅ 已定稿（敌机 / 子弹 / 道具 / 关卡 / BOSS 相关消息） |
| `03-实验清单.md` | ✅ 已定稿（**9 个实验 + 19 张图**） |
| `04-API接口设计.md` | ✅ 已定稿（**3 个路由 / 2 组功能**） |
| `BACKLOG.md` | ✅ 已建立 |

**约定：四份文档全部定稿后才动代码。**

**已定稿的关键设计**：

```
C/S 架构 · 服务端权威同步 · 长短连接分层
竖版飞机大战 · 几何绘制零素材 · 720×960
3 种敌机 · 3 种弹幕 · 5 级火力 · 拾取道具
2 关 × 5 波 · 1 个三阶段 BOSS
实测约束：同屏敌机 ≤ 30，子弹 ≤ 300
```

### 4.1 前置动作（动代码前）

**依赖安装清单以 §1.2 为权威**，这里只列动作：

- [ ] 装 `matplotlib` / `psutil` / `djangorestframework` / `pytest`（命令见 §1.2）
- [ ] 安装 **Wireshark**（图形界面，手动装）
- [ ] 把原飞机大战代码移入 `legacy_game\`（独立提交，便于回溯）
- [ ] 建立 `requirements.txt` 与 `README.md`
- [ ] 建立 `docs\BACKLOG.md`

### 4.2 Django / HTTP 层（D-005 定为主线）

> 接口已**砍到 2 组**（见 `04-API接口设计.md §3`）

- [ ] 创建 Django 项目与 app
- [ ] 用户模型 + **注册 / 登录**接口
- [ ] **排行榜**接口（Redis ZSET 缓存）
- [ ] 客户端 HTTP 调用封装（**不得阻塞主循环**）
- [ ] ❌ ~~玩家战绩接口~~（已取消）
- [ ] ❌ ~~客户端上报成绩~~（已取消，改**服务端直接写分**）

### 4.3 TCP 通信系统（毕设核心）

- [x] 协议编解码 + 粘包拆包（含单元测试）—— 帧 + **玩家/敌机/子弹/道具四类条目全部实现**
- [x] asyncio TCP 服务端骨架 —— `server/main.py`
- [ ] 房间系统
- [x] 机器人客户端 —— 7a 观察者 + **7b 输入 / 心跳版**均完成
- [x] **占位对象同步** —— 服务端广播 + 客户端渲染均已完成；**8a 起带占位敌机 / 子弹**
- [x] 状态同步 + 客户端插值 —— 基础版：前后两帧线性插值（一帧滞后）；完整快照缓冲后续
- [x] **上行链路：输入 + 心跳** —— 7b 完成（`C_INPUT` / `C_HEARTBEAT` / 15 s 超时，见 D-023）
- [x] **数据采集链路** —— 8a 完成：占位实体（数量可配）+ 每秒 CSV + `tools/plot.py` 出图（D-024）
- [ ] **跑 E9 六档位并出图** —— 8b；⚠️ 开工前先拍板「CPU 曲线要不要弯」（见 §2.14）
- [ ] 其余对比实验（编码 E1 / IO 模型 E3 / 网络损伤 E4-E5 / 同步频率 E5）
- [ ] Wireshark 抓包验证

### 4.4 待解决问题 ⚠️

- [x] ~~排行榜 / 关卡进度缺少数据来源~~ → **已解决**：飞机大战自带分数与关卡（D-009）
- [x] ~~成绩伪造~~ → **已解决**：取消客户端上报，**服务端直接写分**（D-009 / `04 §3.1`）
- [x] **网络实验数据来源** —— **已实测（2026-10-19）：本机自连局域网 IP 拿不到真实网络指标**
  - `ping 127.0.0.1` 与 `ping 10.140.71.127` 均 < 1 ms；回声 RTT **0.03~0.14 ms**
  - 向 `10.140.71.127` 传 16 MB：**1145.8 MB/s**，WLAN 网卡收发增量仅 **0.001 / 0.012 MB** → 流量没走网卡
  - **结论**：协议 / 并发 / 逻辑验证可继续用本机多进程；**RTT / 抖动 / 丢包 / 网络损伤实验必须用虚拟机（独立虚拟网络，优先 Host-Only / Internal Switch）或第二台设备**（触发 `01 §11.2` 的兜底，见 D-016）
- [x] **独立网络栈方案已定（2026-10-19）**：现有 **VMware Workstation + Ubuntu Desktop + VMnet1 仅主机模式**；**不装 VirtualBox、不重装 Ubuntu Server**
  - 桥接 WiFi 已实测否决：校园网 `GDPZ-student-5G` 拒绝虚拟机 MAC（拿不到 IPv4）；手机热点下 VM 拿到 `10.152.181.161/24`、能 ping，但 **host→VM 20/20 次 RTT 均为 0.00 ms**；同时 host→网关 `10.152.181.188` 为 **4.67 ms（1~6 ms）**、8000 B 包 **9.60 ms**，证明 ping 有精度，VM 的 0 ms 是真 0
  - 加静态路由强制走网关（`route add 10.152.181.161 mask 255.255.255.255 10.152.181.188`）后仍 0 ms → **VMware 桥接在 L2 直接截获，L3 路由绕不过**；该路由已删除，网络已改回 NAT
  - 最终用法：VM 只用 **VMnet1 仅主机模式**跑服务端；**E4/E5 延迟/丢包用 `tc netem` 注入**；**E7 抓包用 Npcap 回环适配器或 Ubuntu 内 `tcpdump` 导出 pcap**
  - 已否决：VirtualBox / Hyper-V（引入第二平台）、桥接 WiFi（实测 0 ms）、借设备主线（不可重复）
  - 借设备 + 手机热点：**可选**，只做真实性交叉验证，不列入主线
- [ ] **配置并验证 VMnet1 + netem** —— 第 13 周性能测试前完成（VMware / Ubuntu 已有，待切换 / 验证）
- [ ] **窗口尺寸是否放得下** —— 720×960 需屏幕高度 ≥ 1000 px，开工时实测；放不下降到 600×800
- [ ] 待装依赖与文件**见 §1.2 权威清单**（不要再在本节重复维护）

### 4.5 开工指南（⭐ 新会话务必先看这一节）

#### 实施顺序：从小到大，**不要一上来给完整系统**

| 步骤 | 做什么 | 目标 | 规模 |
|---|---|---|---|
| **1** | **回声服务器**：客户端发什么，服务端回什么 | 搞懂 `socket` 怎么收发 | ~30 行 |
| **2** | 加上**长度前缀**，让消息有边界 | 粘包拆包的核心逻辑 | ~10 行核心 |
| **3** | 写测试：半包 / 粘包 / 超大包 / 越界坐标 | 验证边界情况 | 测试为主 |
| **4** | 接入真正的协议（认证、房间、快照） | 按 `02-协议设计.md` 实现 | 逐步扩展 |
| **5** | 服务端 20 Hz tick + 广播 | 端到端跑通 | |
| **6** | 客户端渲染 + 插值（**占位方块**） | 能看到别人在动 | |
| **7** | 机器人客户端 | 使能压测与实验 | |
| **8** | 数据采集 + 压测实验（**E9 是核心**） | 出图出数据 | |
| **9** | 抓包验证 | Wireshark 逐字段核对 | |
| **10** | Django HTTP 层 | 登录 / 排行榜（2 组） | |
| **11** | **游戏内容**：敌机 → 弹幕 → 火力 → 道具 → 关卡 → BOSS | **可砍** | |

> **注意步骤 6 与 11 的分离**：先用**占位方块**跑通通信（步骤 6），
> 游戏内容（步骤 11）排在最后。详见 `01-系统架构.md §3.4` 与 D-010。
>
> **进度**：第 1 步 ✅（回声服务器）；第 2 步 ✅（长度前缀）；第 3 步 ✅（帧边界测试）；
> 第 4 步 ✅（12 字节帧头）；第 5 步 ✅（asyncio + 20 Hz tick + 广播）；
> 第 6 步 ✅ 2026-10-21（pygame 渲染 + 一帧线性插值，39 个测试）；
> 第 7 步 7a ✅ 2026-10-22（观察者机器人：20/50 连接、42 个测试）；
> 第 7 步 7b ✅ 2026-10-23（输入 + 心跳 + 超时 + 机器人输入版，88 个测试，见 D-023）；
> 第 8 步 8a ✅ 2026-10-24（占位实体 + 指标落盘 + 出图工具，**153 个测试**，见 D-024）；
> **第 8 步 8b「跑 E9」等你拍板 §2.14 末尾那件事（CPU 曲线要不要弯）后再开始。**

#### 教学原则（重要）

- **从最小可运行的代码开始**，不要一次性丢几百行
- 每完成一块，解释三件事：**为什么这么设计 / 有什么替代方案 / 为什么没选**
- **这些解释就是答辩答案** —— 要同步记进 `DECISIONS.md`
- 学员 Python 有基础，但**没用过 `socket` / `asyncio` / `struct`**，需要边做边讲

#### ⭐ 人话笔记制度（2026-10-19 新增，**必须执行**）

**每完成一步代码，必须同时产出 `docs/notes/NN-<步骤>-人话版.md`，否则不许进下一步。**

每份笔记必须包含：

| 内容 | 要求 |
|---|---|
| 这步解决什么问题 | 用生活化比喻，不用术语开头 |
| 核心逻辑 | 逐行讲，标明「必须懂」的最小集合 |
| 防御性代码 | 单独列出来，说明「防的是什么」 |
| **可以跳过的语法** | 明确列出，让学员放心跳过 |
| 自测题 | 5 道左右，附答案；能用自己的话说出来才算过 |
| 答辩话术 | 一段可直接背的模板 |

**放行标准**：**用户确认看懂了**，才进入下一步。

> **起因**：2026-10-19，学员在第 3 步（`protocol/framing.py` + 测试）出现明显看不懂，
> 明确说出「我好像有点看不懂代码了」。
>
> 这是毕设最常见的死法 —— 硬撑到第 15 周才崩就救不回来了。
> **第 3 步发现、还有 17 周可修，是最好的时机。**

**已有笔记**（`docs/notes/`）：

| 笔记 | 对应步骤 |
|---|---|
| `00-答辩速查.md` | 答辩前速查 |
| `01-framing-人话版.md` | 第 2~3 步 · 长度前缀 + 帧边界测试 |
| `02-12byte-header-人话版.md` | 第 4 步 · 12 字节帧头 |
| `03-tick-broadcast-人话版.md` | 第 5 步 · asyncio + 20 Hz tick + 广播 |
| `04-render-interpolation-人话版.md` | 第 6 步 · pygame 渲染 + 插值 |
| `05-bot-farm-人话版.md` | 第 7 步 7a · 观察者机器人 |
| `06-input-heartbeat-人话版.md` | 第 7 步 7b · 输入 + 心跳 |
| `07-placeholder-entities-人话版.md` | 第 8 步 8a · 占位实体 + 指标落盘 |

**为什么这条规矩能救命**：答辩前要复习，看的是这些笔记，不是 3000 行代码。

#### 优先级梯队（进度紧张时按此砍）

> 权威定义见 `01-系统架构.md §1.4` 与 D-013

| 梯队 | 内容 |
|---|---|
| 🔴 **第一梯队（命脉）** | 自定义协议 + 粘包拆包 · asyncio 服务端并发 · 状态同步 + 插值 · 机器人客户端 · 数据采集与压测实验 · Wireshark 抓包 |
| 🟡 **第二梯队（加分）** | 房间系统 · 编码对比实验 · Django 登录 + 排行榜 · **游戏内容（敌机/弹幕/火力/道具/关卡/BOSS）** |
| ⚪ **第三梯队（有余力）** | 客户端预测 · E3 IO 模型对比实现 · E6 增量 / 确定性快照 |

#### 纪律

- 预算 **200 h / 20 周**；当前估算约 **222 h** → **已超支约 10%，不得再加新功能**
- **进度落后就砍功能，不延期**
- **游戏内容排最后，超时第一个砍**（砍 BOSS 或砍到 1 关，论文不受影响）
- 想加的东西记进 `BACKLOG.md`，主体跑通前不碰

#### 心态提醒

- 难度**集中在通信系统**，不在游戏。游戏内容排在最后正是为此
- **复杂的是总量，不是每一步** —— 每次只做一个小目标
- 学员在 2026-10-10 首次了解真实量级时有明显落差感，**需要从最小步骤开始重建信心**

---

## 5. 待办 / 备忘

> 依赖与环境相关的一切，**统一看 §1.2**，本节不再重复。

- [ ] 游戏画面走**几何极简风**（统一风格 + 加特效反馈），避免「廉价感」
- [ ] 已知代码问题（暂不改，改造时一并处理）：
  - `enemy0.png` 是 20×15，被 `scale` 到 (30,30)，**比例失真**
  - `hero.png` 宽 40，但 `moveright()` 边界按 48 计算（`x < 376`）
  - `plane-game.py` 与 `control.py` 重复消费事件队列，`control.py` 里的 QUIT 分支是死代码

---

## 6. 本文件维护约定

每次会话结束前更新：

- 做完的事 → 移进「2. 已完成」并打勾
- 新踩的坑 → 加进「3. 已踩过的坑」
- 计划变化 → 更新「4. 下一步计划」
- 顶部「最后更新」改成当天日期

---

## 7. 操作安全规则（⭐ 不可违反）

> 以下是项目所有者的**明确要求**。任何会话、任何情况下都必须遵守。
> 违反这些规则的"便利"是假便利，代价是系统被搞坏。

### 7.1 系统级禁令

| # | 规则 |
|---|---|
| 1 | **不修改注册表**（任何键值） |
| 2 | **不修改环境变量 / PATH** —— 需要调命令就用**全路径**（例如 MySQL 客户端） |
| 3 | **不安装 / 不修改 / 不停启系统服务** |
| 4 | **不改动 C 盘的系统配置**；依赖装进 `E:\PythonProject\.venv`，工具装到 `D:\` |
| 5 | **不修改 `ExecutionPolicy`**（`Activate.ps1` 无法用就直接调 `.venv\Scripts\python.exe`） |

**已经被遵守的例子**：MySQL 的 `bin` 没加进 PATH（全程用全路径调用）。

### 7.2 文件操作

| # | 规则 |
|---|---|
| 6 | **删除 / 移动前必须核对解析后的绝对路径**，并确认目标正确 |
| 7 | 所有**下载、解压只在 `D:\Tools`** 下进行 |
| 8 | `legacy_game\` 是**只读存档**，不参与新系统，**不要改里面的文件** |
| 9 | 覆盖已存在的文件前，**先读再写** |

### 7.3 软件安装

| # | 规则 |
|---|---|
| 10 | **图形界面软件只下载，不自动安装** —— 由用户手动装（Wireshark、Apifox 都是这样处理的） |
| 11 | pip 装包**必须带清华镜像**，并加 `--no-cache-dir --progress-bar off` |

### 7.4 协作方式

| # | 规则 |
|---|---|
| 12 | **危险操作（删除、覆盖、大改）前先说明，等用户确认** |
| 13 | **每步先说明再执行**，不要一气呵成做十件事 |
| 14 | 数据库密码 `123456` **仅限本地开发**，不得用于任何对外服务 |

### 7.5 如果规则冲突

**以本节为准。** 如果某个做法更方便但违反上述任何一条 → **不做，用合规的替代方案。**

