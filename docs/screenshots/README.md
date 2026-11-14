# 系统运行截图（附录 A / 答辩 PPT 用）

这些是**真实运行截图**，从正在跑的系统上直接截的，没有合成、没有 P 图、没有造数据。
生成脚本在 `tools/capture_shots_*.ps1` 和 `tools/shot_board.py`，可以复现。

## 清单

| 文件 | 内容 | 对应要求 |
|---|---|---|
| `01-login.png` | 登录界面（空表单）：用户名/密码、登录/注册/游客进入 | 登录界面 |
| `02-auth-ok.png` | 端到端检查 11 项全过：注册 → `C_AUTH` 认证 → 打一局 → 结算 → 榜上有记录 | 登录/注册成功 |
| `03-game.png` | 游戏画面：HUD（`you=P2 [demo01]`、rtt、fps）、玩家、敌机、两种子弹、右上角 SCORE | 游戏客户端画面 |
| `04-leaderboard.png` | 排行榜：名次/玩家/最高分/关卡/局数，自己那行高亮、第一名金色 | 排行榜页面 |
| `05-server-log.png` | 服务端启动日志：监听参数、`tick loop started at 20 Hz`、`认证通过`、`结算 ... 已入库` | 服务端启动日志 |
| `06-tests.png` | 测试通过：`Ran 366 tests in 4.728s` + `OK` | 测试结果 |
| `07-mysql-redis.png` | MySQL 10 张表（含 `auth_user` / `auth_token` / `score_record`）+ Redis ZSET 内容 | 数据层落点 |
| `08-dashboard.png` | 看板总览：实时指标（6 在线 / tick P95 / 带宽 / 快照 / CPU）、分数 Top 10、7 天趋势、排行榜 | Web 看板 |
| `09-dashboard-matches.png` | 对局记录：分页 + 按玩家名搜索 | Web 看板 |
| `10-api-runs.png` | DRF Browsable API：`/api/v2/runs/`（管理员会话，200 + 分页结果） | DRF 接口 |

## 建议放哪

- **论文附录 A**：这 7 张按顺序放，能完整说明"系统跑得起来、数据落得了地"
- **答辩 PPT**：登录（01）、游戏（03）、排行榜（04）、抓包（`docs/figures/6-14-*.png`）、测试（06）各一张
- **正文**：继续用 E1/E2/E7/E9 的生成图（那些是数据分析图，和这些运行截图不冲突）

## 复现方法

```powershell
# 前置：MySQL80 服务 + Redis + Django(runserver) + 游戏服务端都要在跑
pwsh -ExecutionPolicy Bypass -File tools\capture_shots_1.ps1   # 01 登录界面（03/04 需键盘，见下）
pwsh -ExecutionPolicy Bypass -File tools\capture_shots_2.ps1   # 03 游戏画面（--login 免交互）
pwsh -ExecutionPolicy Bypass -File tools\capture_shots_3.ps1   # 05 / 06 / 07 终端
pwsh -ExecutionPolicy Bypass -File tools\capture_shots_4.ps1   # 02 认证成功 / 07 补拍
.venv\Scripts\python.exe -X utf8 -m tools.shot_board           # 04 排行榜
```

## 两点说明（诚实记录）

### ① 03 / 04 是怎么在没有键盘输入的情况下截到的

这个自动化环境**无法把键盘输入送进 SDL 窗口**（实测了四条路，全失败）：

| 尝试 | 结果 |
|---|---|
| `SendKeys` / `keybd_event` | 注入的真实输入进不去 |
| `PostMessage(WM_KEYDOWN)` | 被 SDL 过滤（SDL2 在 Windows 上走 Raw Input） |
| `AttachThreadInput` + `SetForegroundWindow` | 焦点确实拿到了（`GetFocus()` 就是该窗口），键盘仍不进 |
| `PostMessage(WM_CLOSE)` | ✅ 能生效 —— 说明**消息通道是通的**，只是键盘被 SDL 丢弃 |

所以：

- **03 游戏画面**：用 `--login demo01:secret123` 免交互登录（走**同一条** HTTP 认证路径，不是后门），
  画面、HUD、实体全是真实运行产出。代价是**分数为 0**（没按键就动不了，打不到敌机）。
- **04 排行榜**：用 `tools/shot_board.py` 直接调用 `client/board.py::run_board_screen()` ——
  和游戏里按 `B` 打开是**同一个函数、同一份 HTTP 数据**，像素完全一致。

**如果你想补一张"带分数"的游戏画面**：自己开客户端（`python -m client.main`），
登录后按 ←/→ 打一会儿再按 `Win + Shift + S` 截，替换 `03-game.png` 即可。
那样最真实，也是唯一能拿到分数 > 0 的办法。

### ② 排行榜里的 `demo01` 是演示数据

`demo01` 的 1250 分是通过**真实的写入路径**（`accounts/scoring.py::record_result`）
写进 MySQL + Redis 的，不是直接改的 ZSET。目的是让排行榜截图有内容可看。

**它不是实验数据**，不参与任何图表。E1/E2/E7/E8/E9 的数据全部来自
`data/runs/` 下的真实压测记录，和这里无关。

### ③ 08–10 是三张网页截图（2026-11-14）

用 `tools/shot_dashboard.py`（Edge headless + CDP）截的，数据来自真实运行：
6 个机器人连着服务端、Redis 里是实时 Hash、图表数据来自 MySQL。

- 登录走**真实表单**（临时 staff 账号，截完即删；密码只走环境变量，不落盘）
- Edge 必须由 PowerShell `Start-Process` 启动：用 Python `subprocess` 起的 Edge
  会在几秒内崩溃（`0xC0000409`，沙箱限制），复现命令见工具文件开头
- 截图脚本只读页面，不改任何业务代码；`.cache\` 下的临时 profile 用完即删

## 截图过程中顺手修掉的 4 个真 bug

截个图能挖出这些，说明"把系统真跑起来"本身就是一种测试：

1. **排行榜名次断号**：过滤掉 Redis 里的陈旧成员后，名次仍用原始下标，榜上直接从第 2 名开始
   → 改成按过滤后的条数重新编号（`accounts/views.py`）
2. **HUD 文字重叠**：加上 `[用户名]` 后第一行变长，`fps` 撞到右上角 `SCORE`（显示成 `fpsSCORE 10`）
   → 重排成三行各管一摊（`client/main.py`）
3. **`check_persist` 假失败**：横扫逻辑每秒换向，船在原地抖，8 秒经常 0 分导致 3 项断言失败
   → 改成每 3 秒换向、24 个敌机、14 秒，稳定 11/11（`tools/check_persist.py`）
4. **终端中文乱码 + 找不到窗口**：控制台窗口归 conhost 管（按 PID 找不到）、
   默认代码页 GBK、`cmd /c` 跑完立刻关窗口、管理员会话标题带 `Administrator:  ` 前缀
   → 全部记在 `tools/capture_shots_3.ps1` 的注释里

| game-mode.png | 步骤 11 游戏模式：三波敌机（0x01/0x02/0x03）、弹幕、HUD | 720×960 | 客户端 --shot 自存 |
