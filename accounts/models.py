"""账号与排行榜的数据模型。

**只加两张表，用户表用 Django 内置的 `auth_user`。**

`auth_user` 的好处：密码哈希（PBKDF2 + salt）、唯一约束、最后登录时间全是现成的，
而且 `set_password()` / `check_password()` 是官方实现 —— **不存明文**这件事由框架保证，
比自己写的更不容易出错（`04 §3` 的要求）。

## 为什么分数单独一张表，而不是塞进 user

一局一个分数，用户是一行 —— 塞进 user 就只能存"最高分"，历史全丢，
而且 `04 §4.4` 的 `games`（总局数）根本没法统计。
"""

from django.conf import settings
from django.db import models


class ScoreRecord(models.Model):
    """一局的成绩。**由 TCP 服务端在结算时直接写入**，客户端没有任何上报接口。

    这是防作弊的关键：分数完全由服务端算（击杀数 × 分值），客户端只负责显示。
    `04 §3.1` 里 `/api/scores` 被取消就是为了这个。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scores"
    )
    score = models.PositiveIntegerField()
    level = models.PositiveSmallIntegerField(default=1)
    kills = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "score_record"
        indexes = [
            # 排行榜聚合要按分数倒序、按用户分组
            models.Index(fields=["-score"], name="idx_score_desc"),
            models.Index(fields=["user", "-score"], name="idx_user_score"),
        ]
        ordering = ["-score", "id"]

    def __str__(self) -> str:  # pragma: no cover - 只在调试里用
        return f"{self.user.username}:{self.score}"


class AuthToken(models.Model):
    """登录后发给客户端的 token。

    **为什么不引第三方包**：只有"发一个随机串、能查回来"这一个需求，
    用 Django 的 session 反而要开 session 中间件和 cookie，与"非浏览器客户端"不匹配。

    客户端拿到 token 后有两个用途：
      1. 调 HTTP 接口（`Authorization: Bearer <token>`）
      2. **在 TCP 连接上发 `C_AUTH` 帧** —— 这是长短连接两层唯一的衔接点（D-005）
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tokens"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_token"

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.user.username}:{self.token[:8]}…"