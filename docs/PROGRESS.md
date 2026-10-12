# 项目进度

> **新会话请先读这份文件**，再读 `DECISIONS.md`，即可接上全部上下文。
> 维护约定：每次会话结束前更新本文件。

最后更新：2026-10-10
当前阶段：**设计阶段 —— 01 已定稿，02 已完成草稿，待写 03 / 04**

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

- [ ] 把原飞机大战代码移入 `legacy_game\`（独立提交，便于回溯）
- [ ] 建立 `requirements.txt` 与 `README.md`
- [ ] 补齐缺失依赖：`numpy`、`matplotlib`
- [ ] 安装 Wireshark

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
- [ ] 待装依赖：`djangorestframework`、`psutil`、`matplotlib`、Wireshark

---

## 5. 待办 / 备忘

- [ ] `requirements.txt` 还没建
- [ ] `README.md`（怎么启动）还没建
- [ ] 屏幕实体数变多后需要装 `numpy`（性能优化）
- [ ] 需要装 `Wireshark`（毕设抓包必备）
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
