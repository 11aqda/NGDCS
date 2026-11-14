# NGDC S · 多人游戏服务端监控与数据分析平台

> 一个 C/S 实时游戏服务端 + 一个**只读**的监控 / 复盘看板。
> 游戏端证明"能把实时通信写对"，看板证明"能把系统观测、度量、诊断讲清楚"。

![看板总览](docs/screenshots/08-dashboard.png)

---

## 1. 这是什么

| 部分 | 角色 | 技术 |
|---|---|---|
| **游戏服务端 + 客户端** | 被观测对象 | Python 3.13 · asyncio · 自定义二进制协议 · pygame |
| **监控与数据看板** | 观测者 | Django 5.2 · DRF · MySQL 8 · Redis |

服务端 20 Hz 广播全量快照，客户端按输入意图上报、服务端权威计算坐标；
每秒把 tick 耗时、快照体积、流量、CPU 落成一行 CSV。
看板只读这些数据：实时指标（Redis）、对局记录、Top 10、7 天趋势。

**核心论点**：通信层不是瓶颈 ——
E9 实验里通信占比从 73.0%（64 实体）降到 6.7%（2254 实体），
单核 50% 的拐点约在 215 敌机 / 1720 子弹（详见 `docs/experiments/`）。

---

## 2. 架构

![架构图](docs/figures/architecture.svg)

- **长短连接分层**（D-005）：HTTP 负责登录 / 排行榜 / 看板，TCP 负责实时对局。
- **服务端权威**：客户端只发 `C_INPUT`（按键位），坐标由服务端算，防作弊。
- **快照即全量真相**（D-012）：不做事件同步，靠 20 Hz 全量帧 + 客户端插值。
- **看板只读**：不改协议、不改 tick 逻辑，Redis 读不到就回退 CSV。

---

## 3. 功能

### 实时通信（毕设核心）
- 12 字节帧头（magic / version / type / seq / length），解决 TCP 粘包、半包
- asyncio 服务端：20 Hz tick、输入保质期、心跳与 15 s 超时
- 四类快照条目逐字节对齐协议：玩家 / 敌机 / 子弹 / 道具
- 压测机器人：观察者模式、输入模式、指标汇总

### 数据采集与实验
- 每秒一行 CSV：tick 四段（sim / collision / ser / net）、快照体积、收发流量、CPU、内存
- 黄金基线：200 帧 SHA256 与精确坐标锁定默认实验路径
- 实验回归：`tools/check_experiments` 硬校验 13 项 + 软校验 11 项

### 监控看板
- 登录 / 权限（仅 staff）、对局记录分页与搜索
- Top 10、7 天趋势、实时指标（在线人数 / tick P95 / 带宽 / 快照大小 / CPU）
- 实时指标**优先 Redis**（`ngdcs:metrics:live`，TTL 10 s），读不到回退 CSV 最后一行

### 接口
| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/register` | 公开 | 注册并发 token |
| POST | `/api/auth/login` | 公开 | 登录 |
| GET | `/api/leaderboard` | 公开 | 排行榜（Redis 优先，MySQL 兜底） |
| GET | `/api/v2/runs/` | 管理员 | 对局记录：分页 / `search` / `ordering` |
| GET | `/api/v2/runs/<id>/` | 管理员 | 单条对局 |

```text
GET /api/v2/runs/?page=2&page_size=50&search=sakura&ordering=-score
```

---

## 4. 截图

| 看板总览 | 对局记录 |
|---|---|
| ![看板](docs/screenshots/08-dashboard.png) | ![对局记录](docs/screenshots/09-dashboard-matches.png) |

**DRF 只读接口**（管理员会话下的 Browsable API）：

![API](docs/screenshots/10-api-runs.png)

游戏端截图（登录 / 游戏画面 / 排行榜 / 服务端日志 / 测试 / 数据落库）在
[`docs/screenshots/`](docs/screenshots/README.md)。

> 截图来自真实运行：6 个机器人连着服务端，实时指标来自 Redis，图表数据来自 MySQL。

---

## 5. 快速开始（本地）

### 前置
- Python 3.13
- MySQL 8（库 `myproject`，用户 `django_user`）
- Redis 5+（可选：排行榜与实时指标；没有也能跑，看板回退 CSV）

### 步骤

```powershell
cd E:\PythonProject

# 1) 依赖（务必带镜像源）
.\.venv\Scripts\python.exe -m pip install -r requirements.txt `
    -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir --progress-bar off

# 2) 建表
.\.venv\Scripts\python.exe -X utf8 manage.py migrate

# 3) 建管理员（没有现成账号时）
.\.venv\Scripts\python.exe -X utf8 manage.py createsuperuser

# 4) Django（8000 只能有一个）
.\.venv\Scripts\python.exe -X utf8 manage.py runserver 127.0.0.1:8000

# 5) 游戏服务端（另开窗口）
.\.venv\Scripts\python.exe -X utf8 -m server.main --game-mode --persist-scores

# 6) 客户端（另开窗口）
.\.venv\Scripts\python.exe -X utf8 -m client.main
```

打开 <http://127.0.0.1:8000/dashboard/>，用管理员账号登录。

**实时指标**（可选）：Redis 在跑时给服务端加 `--live-metrics`：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m server.main --game-mode --persist-scores --live-metrics
```

> 一键脚本：`tools\start_game.bat`（服务端 + Django + 客户端），
> `tools\start_dashboard.bat`（只起 Django 看板，带 `/dashboard/` 状态码检查）。

### 演示数据（可选）

看板不想是空的就灌一组演示数据（**幂等**，重复跑会重建，不会累加）：

```powershell
$env:DEMO_PASSWORD = "自己设一个"
.\.venv\Scripts\python.exe -X utf8 manage.py seed_demo
```

生成：`demo` 管理员（staff）+ 5 个 `demo_` 玩家 + 35 条对局（铺在最近 7 天）。
密码只从环境变量读，不写死、不打印；演示用户名带 `demo_` 前缀，一眼可辨。

---

## 6. 测试

```powershell
# 主测试（协议 / 服务端 / 机器人 / 实验回归 / 指标）
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests

# Django 测试（账号 / 看板 / DRF 接口）
.\.venv\Scripts\python.exe -X utf8 manage.py test accounts dashboard --noinput

# 黄金基线（SHA 必须不变）
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_golden_baseline

# 实验回归（硬 13 + 软 11）
.\.venv\Scripts\python.exe -X utf8 -m tools.check_experiments
```

当前结果：

```text
主测试        491 passed
Django        46 passed
黄金基线      SHA256 7860bdb9…（默认实验路径未变）
实验回归      24/24
```

---

## 7. 目录结构

```text
protocol/    12 字节帧、快照编解码、编码器（binary / binary_fast / json）
server/      asyncio 服务端、实体、运动学、指标 CSV、实时指标 Redis 发布器
client/      pygame 客户端（渲染 / 插值 / 输入 / 心跳）
bot/         压测机器人（观察者 / 输入 / 心跳）
accounts/    用户、token、成绩、排行榜、DRF 只读接口（api.py）
dashboard/   只读看板（视图 / 模板）
webapp/      Django 配置与路由
tools/       实验跑批、出图、回归检查、截图
tests/       主测试套件（479 → 现 491）
docs/        进度、决策、实验记录、截图、架构图
deploy/      nginx 配置、容器入口脚本
```

---

## 8. 部署（Docker Compose）

```bash
cp .env.example .env      # 改 SECRET_KEY / MySQL 密码
docker compose up -d --build

# 可选：灌演示数据（幂等）
docker compose exec web python manage.py seed_demo
```

服务：MySQL 8、Redis 7、Django（gunicorn）、nginx。
- 对外只暴露 **80**；3306 / 6379 只绑 `127.0.0.1`
- 静态文件由 nginx 从 `collectstatic` 的卷直接提供
- 配置项全部走环境变量（`.env.example` 有清单）
- 详细上线清单见 [`docs/16-部署清单.md`](docs/16-部署清单.md)

> 当前机器没有 Docker，部署文件先做静态校验；Redis 5 → 7 的升级项也在 16 号清单里。

---

## 9. 文档

| 文档 | 内容 |
|---|---|
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | 项目进度、坑表、交接 |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 技术决策（D-001 ~ D-034） |
| [`docs/14-求职与学习-2026-11.md`](docs/14-求职与学习-2026-11.md) | 求职主线与当前状态 |
| [`docs/15-CS与Web项目-面试必须懂.md`](docs/15-CS与Web项目-面试必须懂.md) | 面试口径 |
| [`docs/16-部署清单.md`](docs/16-部署清单.md) | 部署 / Redis 升级检查清单 |
| [`docs/experiments/`](docs/experiments/) | E1 / E9 等实验记录 |
| [`docs/screenshots/README.md`](docs/screenshots/README.md) | 截图清单与复现方法 |

---

## 10. 说明

- 毕设代码冻结在 `thesis-golden`（`35d72d7`），本仓库主线是 `portfolio`。
- 成绩只由服务端写；客户端没有上报接口。
- 截图里的 `demo01` 等是演示数据，通过真实写入路径产生，不参与论文实验数据。
- 管理员密码不进入任何文档或截图说明。
