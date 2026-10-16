# 项目进度

> **新会话请先读这份文件**，再读 `DECISIONS.md`，即可接上全部上下文。
> 维护约定：每次会话结束前更新本文件。

最后更新：2026-10-10
当前阶段：**设计阶段已定稿（游戏形态改为竖版飞机大战）→ 下一步：前置准备，再开始写代码**

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
| 仓库 | Git | `master` 分支，已提交 7 次 |

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
| `pytest` | 单元测试（粘包拆包必测） | 🟡 建议 | pip（也可用标准库 `unittest` 免装） |
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
- 已跟踪 13 个文件（7 个 `.py` + 5 个素材 + `.gitignore`）
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

---

## 4. 下一步计划

### 4.0 设计阶段（当前）

| 文档 | 状态 |
|---|---|
| `01-系统架构.md` | ✅ 已定稿（含缩圈关卡） |
| `02-协议设计.md` | 🟡 草稿完成（含 zone / 阶段 / 淘汰消息），待确认 |
| `03-实验清单.md` | 🟡 草稿完成（8 个实验 + 16 张图规划），待确认 |
| `04-API接口设计.md` | 🟡 草稿完成（6 个接口 + 表结构 + Redis），待确认 |

**约定：四份文档全部定稿后才动代码。**

**已定稿的关键设计**：C/S 架构 · 服务端权威同步 · 极简多人 · 几何飞船 · 缩圈关卡 · 长短连接分层

### 4.1 前置动作（动代码前）

**依赖安装清单以 §1.2 为权威**，这里只列动作：

- [ ] 装 `matplotlib` / `psutil` / `djangorestframework` / `pytest`（命令见 §1.2）
- [ ] 安装 **Wireshark**（图形界面，手动装）
- [ ] 把原飞机大战代码移入 `legacy_game\`（独立提交，便于回溯）
- [ ] 建立 `requirements.txt` 与 `README.md`
- [ ] 建立 `docs\BACKLOG.md`

### 4.2 Django / HTTP 层（D-005 定为主线）

- [ ] 创建 Django 项目与 app
- [ ] 用户模型 + 注册 / 登录接口
- [ ] 排行榜接口（MySQL 查询 + Redis 缓存）
- [ ] 玩家战绩接口
- [ ] 客户端 HTTP 调用封装（**不得阻塞主循环**）

### 4.3 TCP 通信系统（毕设核心）

- [ ] 协议编解码 + 粘包拆包（含单元测试）
- [ ] asyncio TCP 服务端骨架
- [ ] 房间系统
- [ ] 机器人客户端
- [ ] 状态同步 + 客户端插值
- [ ] 压测 + 对比实验（序列化 / IO 模型 / 网络损伤）
- [ ] Wireshark 抓包验证

### 4.4 待解决问题 ⚠️

- [x] ~~排行榜 / 关卡进度缺少数据来源~~ → **已解决**：采用缩圈关卡（D-008），`max_phase` 与 `survive_seconds` 即为成绩
- [ ] **网络实验数据来源** —— 不装虚拟机、只用本机多进程，**必须在阶段 1 实测**「连本机局域网 IP」能否拿到真实 RTT 与抖动（见 `01-系统架构.md §9.2`、`03-实验清单.md §2.2`）
- [ ] **成绩伪造** —— 建议取消客户端上报，改由服务端直接写分数（见 `04-API接口设计.md §7.1`）
- [ ] 待装依赖与文件**见 §1.2 权威清单**（不要再在本节重复维护）

### 4.5 开工指南（⭐ 新会话务必先看这一节）

#### 实施顺序：从小到大，**不要一上来给完整系统**

| 步骤 | 做什么 | 目标 | 规模 |
|---|---|---|---|
| **1** | **回声服务器**：客户端发什么，服务端回什么 | 搞懂 `socket` 怎么收发 | ~30 行 |
| **2** | 加上**长度前缀**，让消息有边界 | 粘包拆包的核心逻辑 | ~10 行核心 |
| **3** | 写测试：半包 / 粘包 / 超大包 | 验证边界情况 | 测试为主 |
| **4** | 接入真正的协议（认证、房间、快照） | 按 `02-协议设计.md` 实现 | 逐步扩展 |
| **5** | 服务端 20 Hz tick + 广播 | 端到端跑通 | |
| **6** | 客户端渲染 + 插值 | 能看到别人在动 | |
| **7** | 机器人客户端 | 使能压测与实验 | |
| **8** | 数据采集 + 压测实验 | 出图出数据 | |
| **9** | Django HTTP 层 | 登录 / 排行榜 | |
| **10** | 缩圈关卡 | 可砍 | |

#### 教学原则（重要）

- **从最小可运行的代码开始**，不要一次性丢几百行
- 每完成一块，解释三件事：**为什么这么设计 / 有什么替代方案 / 为什么没选**
- **这些解释就是答辩答案** —— 要同步记进 `DECISIONS.md`
- 学员 Python 有基础，但**没用过 `socket` / `asyncio` / `struct`**，需要边做边讲

#### 优先级梯队（进度紧张时按此砍）

| 梯队 | 内容 |
|---|---|
| 🔴 **第一梯队（命脉，不可妥协）** | 自定义协议 + 粘包拆包 · asyncio 服务端并发 · 状态同步 + 插值 · 机器人客户端 · 数据采集与压测实验 · Wireshark 抓包 |
| 🟡 **第二梯队（加分）** | 房间系统 · 序列化对比实验 · Django 登录 + 排行榜（最小版）· 缩圈关卡 |
| ⚪ **第三梯队（有余力再说）** | 客户端预测 · 网络损伤对比 · E3 IO 模型对比实现 · E6 增量快照 |

#### 纪律

- 预算 **200 h / 20 周**；当前估算约 235~250 h → **已超支，不得再加新功能**
- **进度落后就砍功能，不延期**
- 缩圈关卡排最后，**第 12 周时落后超 2 周即砍**
- 想加的东西记进 `BACKLOG.md`，主体跑通前不碰

#### 心态提醒

- 难度**集中在通信系统**，不在游戏。游戏已经被刻意压到最薄
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
