# 04 · API 接口设计

> 本文档定义 **HTTP 短连接层**（Django）的接口：登录、排行榜、玩家档案。
> 实时游戏数据走 TCP 长连接，见 `02-协议设计.md`。
>
> - **状态**：🟡 草稿，待确认
> - **最后更新**：2026-10-10
> - **上游文档**：`01-系统架构.md`（D-005 决定本层为主线）

---

## 1. 为什么需要这一层

`01-系统架构.md §4.4` 定下的核心论点是：

> **按数据类型选择通信方式，而不是一套打天下。**

| 数据类型 | 特征 | 传输方式 |
|---|---|---|
| 实时游戏数据 | 高频（20 Hz）、低延迟、小包 | **TCP 长连接 + 自定义二进制协议** |
| 账号 / 排行榜 / 档案 | 低频、请求-响应、可容忍延迟 | **HTTP 短连接 + JSON** |

**用 TCP 做登录是不划算的**：需要自己处理超时、重试、幂等、事务；
而 HTTP 天然具备这些语义，且有成熟的框架支持。

---

## 2. 技术约定

| 项 | 选择 | 说明 |
|---|---|---|
| 框架 | Django 5.2.18 | 已安装 |
| API 层 | **Django REST Framework** | ⬜ **待安装** |
| 认证 | **DRF TokenAuthentication** | 简单、够用；不用 JWT |
| 数据格式 | JSON | |
| 数据库 | MySQL 8.0.41（库 `myproject`） | 已配置 |
| 缓存 | Redis（排行榜） | 已安装 |
| 基础路径 | `/api/` | |
| 服务端口 | 暂定 **8000** | |

### 2.1 为什么用 DRF

| 理由 | 说明 |
|---|---|
| 省代码 | 序列化、参数校验、认证、分页都是现成的 |
| 规范化 | 状态码、错误格式统一，便于写文档 |
| 成本低 | 一个 pip 包 + 少量配置 |

---

## 3. 接口清单

> **2026-10-10 决定**：时间预算超支，接口**砍到 2 组**（认证 + 排行榜）。
> 删除了 `/api/profile`（玩家档案）与 `/api/scores`（客户端上报成绩）。

| # | 方法 | 路径 | 认证 | 说明 | 优先级 |
|---|---|---|---|---|---|
| 1 | POST | `/api/auth/register` | 否 | 注册 | 必须 |
| 2 | POST | `/api/auth/login` | 否 | 登录，返回 token | 必须 |
| 3 | GET | `/api/leaderboard` | 否 | 排行榜 | 必须 |
| ~~4~~ | ~~POST~~ | ~~`/api/scores`~~ | — | ~~客户端上报成绩~~ | ❌ **已取消** |
| ~~5~~ | ~~GET~~ | ~~`/api/profile`~~ | — | ~~玩家档案~~ | ❌ **已取消** |
| ~~6~~ | ~~POST~~ | ~~`/api/auth/logout`~~ | — | ~~注销~~ | ❌ **已取消** |

**实际 3 个路由，2 组功能**（注册与登录同属「认证」一组，工作量约等于 2 个接口）。

**如果要严格砍到 2 个路由**：可去掉注册，改用 Django admin 手动建号 —— 但演示时不方便，**不建议**。

### 3.1 为什么取消 `/api/scores`（重要）

原本设计由**客户端**上报本局成绩，存在**刷榜漏洞**（改一下请求就能伪造分数）。

**改为服务端直接写分**：

```
TCP 服务端本来就知道每个玩家到达了第几关、得了多少分
→ 本局结束时，服务端直接把分数写入数据库
→ 客户端根本不参与，无法伪造
```

> **这是「服务端权威」原则从游戏状态延伸到成绩记录的体现** —— 一个很好的论文论点。

### 3.2 为什么取消 `/api/profile`

玩家档案（总场次、最高分、累计时长）对毕设**没有技术价值**，只是排行榜的附属展示。
排行榜接口里已经能返回最高分。**省下约 4~5 小时。**

---

## 4. 接口详细定义

> ⚠️ **注意**：`4.3 注销`、`4.5 玩家档案`、`4.6 上报成绩` 三个小节**已取消**（见 §3）。
> 内容保留仅作设计思路记录，**不要实现**。

### 4.1 `POST /api/auth/register`

**请求**
```json
{ "username": "anria", "password": "********" }
```

**响应 201**
```json
{ "user_id": 42, "username": "anria" }
```

**错误**
| 状态码 | 场景 |
|---|---|
| 400 | 用户名或密码不合规（长度、字符集） |
| 409 | 用户名已存在 |

> 密码由 Django 内置 `set_password()` 做 PBKDF2 哈希，**数据库不存明文**。

---

### 4.2 `POST /api/auth/login`

**请求**
```json
{ "username": "anria", "password": "********" }
```

**响应 200**
```json
{
  "token": "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a",
  "user_id": 42,
  "username": "anria"
}
```

**错误**
| 状态码 | 场景 |
|---|---|
| 400 | 参数缺失 |
| 401 | 用户名或密码错误 |

> **这个 `token` 同时用于两处**：
> 1. HTTP 请求头 `Authorization: Token <token>`
> 2. TCP 连接的 `C_AUTH` 消息（见 `02-协议设计.md §6`）
>
> **这是长短连接两层唯一的衔接点。**

---

### 4.3 `POST /api/auth/logout`（可选）

**请求头**：`Authorization: Token <token>`
**响应 204**：无内容

---

### 4.4 `GET /api/leaderboard`

**查询参数**

| 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | 20 | 返回条数，最大 100 |
| `offset` | 0 | 分页偏移 |

**响应 200**
```json
{
  "total": 137,
  "entries": [
    { "rank": 1, "username": "anria",    "best_phase": 12, "best_survive_seconds": 421 },
    { "rank": 2, "username": "眉姨阁诗人", "best_phase": 11, "best_survive_seconds": 388 }
  ]
}
```

**缓存策略**

```
读请求 → 查 Redis ZSET "lb:best_phase"
           ├─ 命中 → 直接组装返回
           └─ 未命中 → 查 MySQL 重建 ZSET → 再读
```

| 项 | 值 |
|---|---|
| Redis 结构 | `ZSET` |
| key | `lb:best_phase` |
| member | `user_id` |
| score | `best_phase` |
| TTL | 无（写成绩时增量更新，不做整体过期） |

---

### 4.5 `GET /api/profile`

**请求头**：`Authorization: Token <token>`

**响应 200**
```json
{
  "user_id": 42,
  "username": "anria",
  "created_at": "2026-10-10T19:56:00+08:00",
  "best_phase": 12,
  "best_survive_seconds": 421,
  "total_games": 37,
  "total_survive_seconds": 8320,
  "last_played_at": "2026-10-10T20:10:00+08:00"
}
```

> **注意**：需求里原本写的是「**关卡进度**」。因为游戏采用**缩圈关卡**机制（见 `01-系统架构.md`），
> 所以对应字段是 `best_phase`（到达的最高阶段）与 `best_survive_seconds`（最长存活时长）。
> **建议对外统一称「玩家档案」，不要用「关卡进度」这个说法。**

---

### 4.6 `POST /api/scores`

**请求头**：`Authorization: Token <token>`

**请求**
```json
{
  "max_phase": 12,
  "survive_seconds": 421,
  "room_code": "LC5WTF"
}
```

**响应 201**
```json
{ "record_id": 1024, "is_new_best": true }
```

**服务端处理流程**

```
1. 校验 token
2. 参数合法性检查（max_phase 0~999, survive_seconds 0~86400）
3. 写入 score_record 表
4. 更新 Redis ZSET：ZADD GT lb:best_phase <max_phase> <user_id>
5. 若刷新了个人最好成绩 → 更新 player_profile
6. 返回 is_new_best
```

> `ZADD GT` 保证只在分数更高时更新，天然幂等 —— **重复上报不会污染排行榜**。

**错误**
| 状态码 | 场景 |
|---|---|
| 400 | 参数越界 |
| 401 | token 无效 |
| 429 | 上报过于频繁（限流） |

---

## 5. 数据库设计

### 5.1 表结构

```sql
-- 账号由 Django 内置 auth_user 表管理

-- 玩家档案（汇总数据）
CREATE TABLE player_profile (
    id                   BIGINT   PRIMARY KEY AUTO_INCREMENT,
    user_id              INT      NOT NULL UNIQUE,
    nickname             VARCHAR(32),
    best_phase           SMALLINT NOT NULL DEFAULT 0,
    best_survive_seconds INT      NOT NULL DEFAULT 0,
    total_games          INT      NOT NULL DEFAULT 0,
    total_survive_seconds BIGINT  NOT NULL DEFAULT 0,
    created_at           DATETIME NOT NULL,
    last_played_at       DATETIME,
    FOREIGN KEY (user_id) REFERENCES auth_user(id)
);

-- 每局成绩明细
CREATE TABLE score_record (
    id              BIGINT   PRIMARY KEY AUTO_INCREMENT,
    user_id         INT      NOT NULL,
    max_phase       SMALLINT NOT NULL,
    survive_seconds INT      NOT NULL,
    room_code       VARCHAR(8),
    played_at       DATETIME NOT NULL,
    INDEX idx_user_played (user_id, played_at DESC),
    INDEX idx_phase (max_phase DESC),
    FOREIGN KEY (user_id) REFERENCES auth_user(id)
);
```

> Django 会用 ORM 自动建表（`makemigrations` + `migrate`），上面的 SQL 仅作说明。

### 5.2 Redis 结构

| 用途 | 结构 | key | 说明 |
|---|---|---|---|
| 排行榜 | ZSET | `lb:best_phase` | member=user_id, score=best_phase |
| 档案缓存（可选） | HASH | `profile:{user_id}` | 减少高频读取的数据库压力 |

**为什么用 Redis 做排行榜**：ZSET 的 `ZREVRANGE` 是 O(log N)，比 MySQL 的 `ORDER BY ... LIMIT` 快得多，且能天然处理并列排名。**这正是 Redis 在本项目中的价值所在**，也是 `01-系统架构.md` 里把它列入技术栈的理由。

---

## 6. 客户端调用方式

### 6.1 关键约束：**不能阻塞游戏主循环**

| 调用时机 | 是否在主循环内 | 处理方式 |
|---|---|---|
| 登录 / 注册 | ❌ 在登录界面 | 直接同步调用即可 |
| 拉取排行榜 | ❌ 在排行榜界面 | 直接同步调用即可 |
| 上报成绩 | ❌ 在结算界面 | 直接同步调用即可 |

**结论：所有 HTTP 调用都发生在游戏循环之外，天然不存在阻塞问题。**

### 6.2 但仍需注意

- **设置超时**：所有请求必须带 `timeout`（建议 5 s），否则网络异常时会长时间卡住界面
- **失败要可见**：登录失败、上报失败必须有明确提示，不能静默吞掉
- **不要在游戏进行中调用**：如果将来要在局内刷新排行榜，必须放到后台线程

### 6.3 依赖

```
requests 2.34.2   ← 已安装
```

---

## 7. 安全考虑

| 项 | 措施 | 说明 |
|---|---|---|
| 密码存储 | Django `set_password()`（PBKDF2 + salt） | 不存明文 |
| 传输加密 | **局域网明文 HTTP** | ⚠️ 已知局限，论文中要说明；生产环境应上 HTTPS |
| 认证 | Token（40 字节随机串） | 存于 `authtoken_token` 表 |
| SQL 注入 | Django ORM 参数化查询 | 天然免疫 |
| 限流 | DRF `Throttle` | 重点保护 `/api/scores` 与 `/api/auth/login` |
| 成绩伪造 | ⚠️ **当前无法防** | 客户端直接上报 `max_phase`，可被篡改 |

### 7.1 关于成绩伪造（论文中要诚实讨论）

**问题**：`POST /api/scores` 信任客户端上报的数值，改一下请求就能刷榜。

**可选缓解措施**（按成本排序）：

| 措施 | 成本 | 效果 |
|---|---|---|
| 服务端记录对局过程，结算时由服务端上报 | 中 | ✅ 根治 |
| 对局开始/结束时服务端各记一次，校验时长合理性 | 低 | 🟡 挡掉明显异常值 |
| 限制上报频率 + 数值上限 | 极低 | 🟡 挡掉脚本刷榜 |

**建议**：采用第二项（服务端侧记录 `max_phase`，不信任客户端上报值）——
TCP 服务端本来就知道每个玩家到达了第几阶段，**结算时直接由服务端写入，客户端根本不参与**。

> 这样 `/api/scores` 可以取消，改为**服务端内部调用**。
> 这本身就是论文里一个很好的论点：**服务端权威不仅用于游戏状态，也用于成绩记录。**

---

## 8. 待确认事项

| # | 事项 | 决定 / 建议 |
|---|---|---|
| 1 | 是否安装 Django REST Framework | ✅ **装**，省代码 |
| 2 | 是否取消 `/api/scores` | ✅ **已取消**（见 §3.1），改服务端直接写分 |
| 3 | 是否取消 `/api/profile` | ✅ **已取消**（见 §3.2） |
| 4 | 服务端口 | 暂定 **8000** |
| 5 | 是否启用 DRF 限流 | ✅ 建议对 `/api/auth/login` 开启 |
| 6 | `player_profile` 还需不需要 | ⚠️ 取消 `/api/profile` 后，该表仅用于排行榜聚合，**可简化为直接从 `score_record` 聚合** |

### 8.1 接口数量最终结论

```
认证组：POST /api/auth/register
        POST /api/auth/login
排行组：GET  /api/leaderboard

共 3 个路由 / 2 组功能，均为必须
```

**这是时间预算压力下能保证完整功能的最小集合。**
