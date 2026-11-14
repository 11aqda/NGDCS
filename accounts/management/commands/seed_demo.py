"""生成演示数据：1 个 demo 管理员 + 5 个玩家 + 35 条对局记录。

## 用途

云服务器 / 本地演示环境里，看板不能是空的。这个命令把"看着像真的"的
最小数据集造出来：**演示数据，不参与论文实验统计**。

## 三条硬约束

1. **密码不写死**：从环境变量 `DEMO_PASSWORD` 读；没设置就直接报错退出，
   绝不落盘、绝不打印。
2. **幂等**：`demo` 与 `demo_*` 用户 `get_or_create`；每次运行先删掉
   demo 玩家的成绩再重建，重复跑结果一致（不会越跑越多）。
3. **一眼能认出是演示数据**：玩家用户名统一 `demo_` 前缀，命令输出里标注 DEMO。

## 用法

```powershell
$env:DEMO_PASSWORD = "自己设一个"
E:\\PythonProject\\.venv\\Scripts\\python.exe -X utf8 manage.py seed_demo
```

容器里：

```bash
docker compose exec web python manage.py seed_demo
```
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from accounts.models import ScoreRecord
from accounts.scoring import record_result

# 演示玩家：用户名带 demo_ 前缀，分数从高到低（Top 10 图有层次）
DEMO_PLAYERS = [
    ("demo_aster", 1250),
    ("demo_blaze", 980),
    ("demo_comet", 760),
    ("demo_drift", 540),
    ("demo_ember", 320),
]

# 每人 7 局 → 共 35 条（要求 30~50）
RECORDS_PER_PLAYER = 7

# 每局相对基准分的偏移，让曲线不是一条直线（确定性，不用随机数）
SCORE_OFFSETS = [0, -40, 25, -15, 10, -60, 5]

LEVELS = [1, 2, 1, 3, 2, 1, 2]


class Command(BaseCommand):
    help = "生成演示数据（demo 管理员 + 5 个玩家 + 35 条成绩）；密码从 DEMO_PASSWORD 读"

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD", "").strip()
        if not password:
            raise CommandError(
                "没有设置 DEMO_PASSWORD。请先：\n"
                '  $env:DEMO_PASSWORD = "自己设一个"\n'
                "密码不会写进代码或日志。"
            )

        # ① demo 管理员（staff，能进 /dashboard/ 和 /api/v2/runs/）
        admin, created = User.objects.get_or_create(username="demo")
        admin.is_staff = True
        admin.is_active = True
        admin.set_password(password)
        admin.save()
        self.stdout.write(
            f"[seed_demo] 管理员 demo {'创建' if created else '更新'}（staff，密码来自 DEMO_PASSWORD）"
        )

        # ② 演示玩家（不能登录：给不可用密码）
        players = []
        for username, base_score in DEMO_PLAYERS:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_unusable_password()
            user.save()
            players.append((user, base_score))

        # ③ 清掉旧演示成绩（只动 demo_ 用户，不碰真实数据）
        old, _ = ScoreRecord.objects.filter(
            user__username__in=[name for name, _ in DEMO_PLAYERS]
        ).delete()
        if old:
            self.stdout.write(f"[seed_demo] 清理旧演示成绩 {old} 条")

        # ZSET 里的旧分数也清掉，避免"改了基准分但榜上是旧值"
        self._drop_leaderboard_cache([user.id for user, _ in players])

        # ④ 重建成绩：时间铺满最近 7 天，让趋势图有内容
        now = datetime.now()
        total = 0
        for user, base_score in players:
            for index in range(RECORDS_PER_PLAYER):
                score = max(1, base_score + SCORE_OFFSETS[index % len(SCORE_OFFSETS)])
                level = LEVELS[index % len(LEVELS)]
                kills = max(0, score // 10)
                record = record_result(
                    user.id, score, level=level, kills=kills
                )
                created_at = now - timedelta(
                    days=(RECORDS_PER_PLAYER - 1 - index),
                    minutes=index * 13,
                )
                # auto_now_add 会强制写"现在"，所以落库后再改成演示时间
                ScoreRecord.objects.filter(id=record.id).update(
                    created_at=created_at
                )
                total += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[seed_demo] DEMO DATA 已生成：管理员 1 个、玩家 {len(players)} 个、"
                f"对局 {total} 条（时间铺在最近 7 天）"
            )
        )
        self.stdout.write(
            "  登录：demo / 你设置的 DEMO_PASSWORD（密码不打印）\n"
            "  这些是演示数据，用户名统一 demo_ 前缀，重复执行会重建而不是累加。"
        )

    def _drop_leaderboard_cache(self, user_ids: list[int]) -> None:
        """把演示玩家从 Redis 排行榜移除；Redis 不可用就跳过（不影响入库）。"""
        from accounts.scoring import _redis_client

        try:
            client = _redis_client()
            client.zrem(settings.LEADERBOARD_KEY, *[str(uid) for uid in user_ids])
        except Exception:  # noqa: BLE001 - 演示环境没有 Redis 也要能跑
            pass
