# 15 · C/S 与 Web 项目：面试必须懂什么

> 用途：面试前复习、项目讲解、判断哪些代码要深看、哪些可以跳过。
> 当前代码：C/S = `game-dev` 8d55981；Web = `web-demo` 1c07aa2。
> 注意：项目目前**没有使用 DRF**；BOSS/关卡/四字段**还没做**。

---

## 0. 一句话定位

```text
C/S：实时通信系统（TCP + 自定义二进制协议 + asyncio 服务端）
Web：游戏数据监控看板（Django + MySQL + 模板 + 实时指标 CSV）
```

不是“飞机大战”，也不是“商城”。

---

## 1. C/S 项目必须懂

### 1.1 协议

必须能说清 12 字节帧头：

```text
magic | version | type | seq | length
```

- `magic`：协议标识，防止乱连
- `version`：协议版本
- `type`：消息类型
- `seq`：序号，请求/响应配对
- `length`：payload 字节数

必须能解释：

```text
为什么 TCP 会粘包/半包
length 怎么解决边界
FrameParser 怎么缓存不足一帧的数据
非法帧/超长帧怎么处理
```

### 1.2 消息类型

```text
C_INPUT          输入
C_HEARTBEAT      心跳
C_AUTH           TCP 认证
S_WELCOME        欢迎
S_SNAPSHOT       快照
S_HEARTBEAT_ACK  心跳应答
S_AUTH_OK/FAIL   认证结果
```

### 1.3 服务端

必须懂：

```text
asyncio 单线程事件循环
一个连接一个协程
20Hz tick
每 tick 更新世界、构建快照、广播
心跳 5s / 超时 15s
输入 TTL
```

必须能解释：

```text
为什么不能在 tick 里同步查 MySQL
为什么 asyncio 适合 I/O，不适合 CPU 密集
```

### 1.4 快照

```text
13B 头 + 玩家 11B + 敌机 9B + 子弹 8B + 道具 7B
```

能算：

```text
4 玩家 + 30 敌机 + 200 子弹 = 1927 B
20Hz 单客户端约 37.9 KB/s
```

### 1.5 客户端

只需要懂：

```text
非阻塞 socket
每帧 poll
FrameParser 组帧
按实际到达间隔做插值
20Hz 上报输入
```

不用懂 pygame 绘制细节。

### 1.6 持久化与认证

```text
HTTP 登录拿 token
TCP C_AUTH 绑定用户
结算写 score_record
Redis ZSet 排行榜
```

### 1.7 实验与性能

能讲：

```text
E1 二进制 vs JSON
E2 并发上限 255
E4 抖动比恒定延迟更伤
E5 tick 率与带宽
E7 Wireshark 抓包
E9 实体数瓶颈
```

数字只写自己测过的，不要背错。

### 1.8 能跳过的游戏代码

```text
敌机贴图/颜色
pygame 渲染细节
子弹像素碰撞
关卡/BOSS 剧情
每个实体类字段
```

---

## 2. Web 项目必须懂

### 2.1 Django 请求流程

```text
浏览器
→ webapp/urls.py
→ dashboard/urls.py
→ dashboard/views.py
→ ORM 查询
→ 模板渲染
→ HTML
```

### 2.2 ORM

必须懂：

```text
aggregate：整表汇总
values + annotate：分组统计
select_related：FK JOIN，避免 N+1
Paginator：分页
```

能解释看板里的：

```text
用户总数
分数记录数
最高分/平均分
Top10 每个玩家最高分
最近 7 天趋势
```

### 2.3 登录/权限

```text
Django auth_user
SessionMiddleware
AuthenticationMiddleware
LoginView / LogoutView
@login_required
request.user.is_staff
```

必须知道：

```text
LogoutView 只接受 POST
看板只给 staff
普通玩家 403
```

### 2.4 CSRF

```text
登录表单需要 CSRF token
API 客户端没有 Cookie，所以 API 用 @csrf_exempt
浏览器看板不能乱关 CSRF
```

### 2.5 对局记录页

```text
select_related("user")
按 created_at 倒序
按用户名搜索
每页 20 条
PageNumberPagination / Django Paginator
```

### 2.6 实时指标

```text
服务端每秒写 data/server_metrics.csv
Django 读最后一行
超过 5 秒显示“最近数据”
显示 online / tick_p95 / bandwidth / snapshot / CPU
```

当前路径：

```text
E:/PythonProject/data/server_metrics.csv
```

最终合并后改相对路径。

### 2.7 DRF

**目前没有 DRF。**  
计划新增：

```text
GET /api/v2/runs/
```

用：

```text
ModelSerializer
ReadOnlyModelViewSet
DefaultRouter
PageNumberPagination
SearchFilter / OrderingFilter
IsAdminUser + SessionAuthentication
```

面试时不要说自己“项目用了 DRF”，要说“正在加到 v2 接口”。

### 2.8 能跳过的 Web 细节

```text
HTML/CSS 细节
ECharts 具体配置
Bootstrap 布局
复杂前端
```

---

## 3. 项目讲解三版

### 30 秒

> 我做了一个 C/S 实时通信系统：自定义 12 字节二进制协议，解决 TCP 粘包/半包；asyncio 单线程 20Hz 广播快照；Django 做登录和排行榜，MySQL 持久化，Redis ZSet 缓存；另外用 Django 做了一个只读数据看板。

### 5 分钟

```text
背景：实时游戏通信
架构：客户端 / TCP 服务端 / Django / MySQL / Redis
协议：12B 头、消息类型、快照
并发：asyncio、每连接协程、20Hz
客户端：非阻塞、插值
数据：登录 token、结算、排行榜
测试：479 个测试、抓包、压测
```

### 15 分钟深挖

选一个：

```text
粘包/半包怎么处理
20Hz 广播怎么保证不卡
E4 为什么“抖动比延迟更伤”
```

不要试图 15 分钟讲完所有模块。

---

## 4. 高频问题

### C/S

```text
为什么用 TCP 不用 UDP？
粘包/半包怎么解决？
12B 头每个字段干什么？
asyncio 怎么撑并发？
tick 里为什么不能查库？
快照多大？带宽多少？
瓶颈在哪？
出过什么 bug？
```

### Web

```text
Django 请求生命周期？
ORM 怎么避免 N+1？
session 和 JWT 区别？
CSRF 怎么防？
为什么看板只给 staff？
分页怎么实现？
实时指标怎么来的？
为什么不用 DRF？
```

### 通用

```text
MySQL 索引/事务
Redis 缓存/ZSet
HTTP/TCP
Git/Linux
算法
```

---

## 5. 不能吹的

- 不能说“项目用了 DRF”——目前没有
- 不能说“已经部署上线”——目前没有
- 不能说“BOSS/关卡做完了”——还没做
- 不能编测试数字/性能数字
- 不能把管理员密码写进文档

---

## 6. 代码地图

### C/S

```text
protocol/framing.py       帧头/解析
protocol/snapshot.py      快照编码
server/main.py            asyncio/tick/广播
server/entities.py        实体/世界
server/persistence.py     登录/token/结算
client/main.py            客户端主循环
client/net.py             非阻塞 socket
```

### Web

```text
webapp/urls.py            总路由
webapp/settings.py        session/auth/dashboard
dashboard/views.py        统计/趋势/对局/指标
dashboard/urls.py         看板路由
dashboard/templates/      页面
accounts/views.py         登录/排行榜 API
```

---

## 7. 复习顺序

```text
1. 30 秒/5 分钟讲法
2. 协议 + 粘包/半包
3. asyncio + tick/快照
4. Django 请求流程 + ORM
5. 登录/权限/CSRF
6. 指标/分页/搜索
7. 高频问题
```

**目标：不背代码，能画图、能讲取舍、能回答“为什么”。**
