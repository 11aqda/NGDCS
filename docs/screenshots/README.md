# 运行截图

真实运行截图，不是合成图。启动 MySQL、Redis、Django 和游戏服务端后，用 `tools/capture_shots_*.ps1` 与 `tools/shot_board.py` 可复现。

| 文件 | 内容 |
|---|---|
| `01-login.png` | 登录界面 |
| `02-auth-ok.png` | 注册 → 认证 → 对局 → 结算 → 排行榜 |
| `03-game.png` | 游戏客户端：HUD、玩家、敌机、子弹、分数 |
| `04-leaderboard.png` | 排行榜 |
| `05-server-log.png` | 服务端启动与 tick 日志 |
| `06-tests.png` | 测试通过 |
| `07-mysql-redis.png` | MySQL 表与 Redis ZSET |
| `08-dashboard.png` | 看板总览：实时指标、Top 10、7 天趋势 |
| `09-dashboard-matches.png` | 对局记录：分页与搜索 |
| `10-api-runs.png` | DRF 只读接口 `/api/v2/runs/` |
| `game-mode.png` | 游戏模式：三波敌机与弹幕 |
| `game-wave-banner.png` | 波次提示 |

> 截图中的 `demo01`、`demo_*` 是演示数据，通过真实写入路径产生，不参与实验数据。
