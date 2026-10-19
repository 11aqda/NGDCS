# 项目进度

> **新会话请先读这份文件**，再读 `DECISIONS.md`，即可接上全部上下文。
> 维护约定：每次会话结束前更新本文件。

最后更新：2026-10-19
当前阶段：**阶段 1：第 3 步「帧边界单元测试」完成 → 下一步：第 4 步接入真正的 12 字节帧头与消息类型**

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
| 仓库 | Git | `master` 分支，已提交 13 次 |

**venv 已装 16 个包：**
```
asgiref 3.12.1 · certifi · cffi 2.1.1 · charset-normalizer 3.5.1 · cryptography 50.0.2
Django 5.2.18 · idna 3.20 · pip 26.2.1 · pycparser 3.11 · pygame 2.6.1
PyMySQL 1.2.3 · redis 8.1.0 · requests 2.34.2 · sqlparse 0.6.0 · tzdata 2026.5 · urllib3 2.8.0
```

#### ❌ 待安装

| 项 | 用途 | 优先级 | 装法 |
|---|---|---|---|
| **Wireshark** | 抓包验证（毕设必备） | 🔴 必须 | **图形界面，需手动安装** |
| `matplotlib` | 论文出 16 张图 | 🔴 必须 | pip |
| `psutil` | 实验采集 CPU / 内存 | 🔴 必须 | pip |
| `djangorestframework` | HTTP 接口层（D-005） | 🔴 必须 | pip |
| `pytest` | 单元测试 | 🟡 可选 | **暂不装**：已用标准库 `unittest`（`tests\test_framing.py`） |
| `numpy` | 实体数多时提性能 | ⚪ 按需 | pip（**当前玩法实体少，暂不需要**） |

**一键安装命令：**
```
E:\PythonProject\.venv\Scripts\python.exe -m pip install matplotlib psutil djangorestframework pytest -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir --progress-bar off
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
- 已跟踪 22 个文件（代码 + 文档 + 素材）
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

`E:\PythonProject\docs\` —— `PROGRESS.md`（本文件）、`DECISIONS.md`

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

- [ ] 协议编解码 + 粘包拆包（含单元测试）
- [ ] asyncio TCP 服务端骨架
- [ ] 房间系统
- [ ] 机器人客户端
- [ ] **占位对象同步**（几个方块，先跑通通信）
- [ ] 状态同步 + 客户端插值
- [ ] 压测 + 对比实验（编码 / IO 模型 / 网络损伤 / **实体数影响 E9**）
- [ ] Wireshark 抓包验证

### 4.4 待解决问题 ⚠️

- [x] ~~排行榜 / 关卡进度缺少数据来源~~ → **已解决**：飞机大战自带分数与关卡（D-009）
- [x] ~~成绩伪造~~ → **已解决**：取消客户端上报，**服务端直接写分**（D-009 / `04 §3.1`）
- [x] **网络实验数据来源** —— **已实测（2026-10-19）：本机自连局域网 IP 拿不到真实网络指标**
  - `ping 127.0.0.1` 与 `ping 10.140.71.127` 均 < 1 ms；回声 RTT **0.03~0.14 ms**
  - 向 `10.140.71.127` 传 16 MB：**1145.8 MB/s**，WLAN 网卡收发增量仅 **0.001 / 0.012 MB** → 流量没走网卡
  - **结论**：协议 / 并发 / 逻辑验证可继续用本机多进程；**RTT / 抖动 / 丢包 / 网络损伤实验必须用虚拟机（桥接）或第二台设备**（触发 `01 §11.2` 的兜底，见 D-016）
- [ ] **落实网络实验环境**（虚拟机桥接 / 第二台设备）—— 第 13 周性能测试前必须就绪
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
> **进度**：第 1 步 ✅ 2026-10-19（回声服务器）；第 2 步 ✅ 2026-10-19（长度前缀，
> `protocol\framing.py`）；第 3 步 ✅ 2026-10-19（15 个帧边界用例，`tests\test_framing.py`）；
> 第 4 步「12 字节帧头 + 消息类型」为下一步。

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

**已有笔记**：`docs/notes/01-framing-人话版.md`（第 2~3 步，已验证 15 个测试全过）

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

