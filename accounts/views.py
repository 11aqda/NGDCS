"""三个 HTTP 接口：注册 / 登录 / 排行榜。

全部返回 JSON，**不需要 CSRF**（客户端不是浏览器，见 settings 的说明）。

错误一律用 `{"error": "..."}` + 4xx，**不泄漏内部细节** ——
登录失败不区分"用户不存在"和"密码错"，避免被用来枚举账号。
"""

from __future__ import annotations

import json
import secrets
import time

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Count, Max
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.models import AuthToken, ScoreRecord

MAX_BODY = 8 * 1024  # 别让人用超大 body 打我

# 熔断：Redis 连不上之后，这段时间内**直接跳过**，不再尝试
_REDIS_DOWN_UNTIL = 0.0
_REDIS_BREAKER_SECONDS = 5.0

# 排行榜单次请求能容忍的 Redis 开销上限（秒）
_REDIS_TIMEOUT = 0.25


def _json_body(request: HttpRequest) -> dict | None:
    """安全地解析 JSON body。解析失败返回 None（调用方回 400）。"""
    if len(request.body) > MAX_BODY:
        return None
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _issue_token(user: User) -> str:
    token = secrets.token_hex(32)
    AuthToken.objects.create(user=user, token=token)
    return token


@csrf_exempt
@require_http_methods(["POST"])
def register(request: HttpRequest) -> JsonResponse:
    """`POST /api/auth/register` —— 建号并发 token（注册后直接可用，不用再登一次）。"""
    data = _json_body(request)
    if data is None:
        return JsonResponse({"error": "请求体不是合法 JSON"}, status=400)

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not 3 <= len(username) <= 20:
        return JsonResponse({"error": "用户名长度需为 3~20 个字符"}, status=400)
    if len(password) < 6:
        return JsonResponse({"error": "密码至少 6 位"}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": "用户名已被占用"}, status=409)

    user = User.objects.create_user(username=username, password=password)
    return JsonResponse(
        {"token": _issue_token(user), "username": user.username, "user_id": user.id},
        status=201,
    )


@csrf_exempt
@require_http_methods(["POST"])
def login(request: HttpRequest) -> JsonResponse:
    """`POST /api/auth/login` —— 校验密码并发 token。

    **失败一律回复同一句话**：区分"用户不存在"和"密码错误"等于给攻击者一个账号枚举器。
    """
    data = _json_body(request)
    if data is None:
        return JsonResponse({"error": "请求体不是合法 JSON"}, status=400)

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user = authenticate(username=username, password=password)
    if user is None:
        return JsonResponse({"error": "用户名或密码错误"}, status=401)

    return JsonResponse(
        {"token": _issue_token(user), "username": user.username, "user_id": user.id}
    )


def _leaderboard_from_mysql(limit: int, offset: int) -> tuple[int, list[dict]]:
    """从 `score_record` 聚合出排行榜 —— Redis 缓存未命中时用它重建。

    一次查询同时拿到：最高分、最高关卡、总局数。
    `values()` + `annotate()` 就是 SQL 的 `GROUP BY user_id`，
    **不是 N+1**（每行一次查询的写法最容易在这里犯）。
    """
    rows = list(
        ScoreRecord.objects.values("user_id")
        .annotate(best_score=Max("score"), max_level=Max("level"), games=Count("id"))
        .order_by("-best_score", "user_id")[offset : offset + limit]
    )
    if not rows:
        return 0, []

    user_ids = [row["user_id"] for row in rows]
    names = dict(User.objects.filter(id__in=user_ids).values_list("id", "username"))
    entries = [
        {
            "rank": offset + index + 1,
            "username": names.get(row["user_id"], "?"),
            "best_score": row["best_score"],
            "max_level": row["max_level"],
            "games": row["games"],
        }
        for index, row in enumerate(rows)
    ]
    total = ScoreRecord.objects.values("user_id").distinct().count()
    return total, entries


def _redis_client():
    """构造 Redis 客户端：**RESP2** + **禁用内部重试** + 紧超时。

    两个都是实测踩出来的（2026-11-01）：

    ⚠️ **RESP3 不兼容**：本机是 Redis **5.0.14.1**（Windows 老版本），
    而 redis-py 8.x 默认用 RESP3，握手时发 `HELLO 3` → 服务端回
    `unknown command 'HELLO'`，**每次调用都抛异常**。
    必须显式 `protocol=2` 退回 RESP2。

    ⚠️ **必须禁掉内部重试**：redis-py 8.x 对连接错误默认做指数退避重试，
    `socket_connect_timeout=0.3` 会被重试掩盖 —— Redis 没启时 `ping()`
    实测卡了 **8.5 秒**，排行榜接口直接读超时。
    排行榜是"缓存挂了也要能用"的接口，所以 `Retry(NoBackoff(), 0)`。
    """
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    return redis.Redis(
        **settings.REDIS,
        protocol=2,  # ← Redis 5.x 不支持 RESP3
        socket_connect_timeout=_REDIS_TIMEOUT,
        socket_timeout=_REDIS_TIMEOUT,
        retry=Retry(NoBackoff(), 0),  # ← 别让重试把超时拖成 8 秒
    )


def _leaderboard_from_redis(limit: int, offset: int) -> tuple[int, list[dict]] | None:
    """从 Redis ZSET 读 top N。**连不上或为空就返回 None**，由调用方退回 MySQL。

    Redis 在这里不是"可有可无的缓存"，它是排行榜的**读路径**：
    `ZREVRANGE` 是 O(log N + k)，而 MySQL 要全表 `GROUP BY`。
    但**不能只依赖它** —— Redis 重启会丢数据，MySQL 才是真相来源。

    失败后按 `_REDIS_BREAKER_SECONDS` 熔断，避免每个请求都白等一个超时。
    """
    global _REDIS_DOWN_UNTIL
    if time.monotonic() < _REDIS_DOWN_UNTIL:
        return None

    try:
        client = _redis_client()
        key = settings.LEADERBOARD_KEY
        total = int(client.zcard(key))
        if total == 0:
            return None  # 缓存空 → 让调用方用 MySQL 重建

        raw = client.zrevrange(key, offset, offset + limit - 1, withscores=True)
        if not raw:
            return total, []

        user_ids = [int(member) for member, _score in raw]
        stats = {
            row["user_id"]: row
            for row in ScoreRecord.objects.filter(user_id__in=user_ids)
            .values("user_id")
            .annotate(max_level=Max("level"), games=Count("id"))
        }
        names = dict(User.objects.filter(id__in=user_ids).values_list("id", "username"))
        entries = []
        for index, (member, score) in enumerate(raw):
            uid = int(member)
            # **过滤陈旧成员**：Redis 是缓存，数据库重置过、用户被删、切过库，
            # 都会让 ZSET 里残留已经不存在的 user_id。不过滤的话榜上会出现
            # `username: "?"`、`games: 0` 的幽灵条目（2026-11-01 测试时真实撞到）。
            if uid not in names:
                continue
            entries.append(
                {
                    "rank": offset + index + 1,
                    "username": names[uid],
                    "best_score": int(score),
                    "max_level": stats.get(uid, {}).get("max_level") or 1,
                    "games": stats.get(uid, {}).get("games") or 0,
                }
            )
        if not entries:
            # 整页都是陈旧成员 → 当作缓存不可用，让调用方用 MySQL 重建
            return None
        return total, entries
    except Exception:  # noqa: BLE001 - 缓存不可用不该让接口挂掉
        _REDIS_DOWN_UNTIL = time.monotonic() + _REDIS_BREAKER_SECONDS
        return None


@require_http_methods(["GET"])
def leaderboard(request: HttpRequest) -> JsonResponse:
    """`GET /api/leaderboard?limit=20&offset=0` —— 先查 Redis，未命中查 MySQL。"""
    try:
        limit = max(1, min(100, int(request.GET.get("limit", 20))))
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        return JsonResponse({"error": "limit / offset 必须是整数"}, status=400)

    cached = _leaderboard_from_redis(limit, offset)
    if cached is not None:
        total, entries = cached
        return JsonResponse({"total": total, "entries": entries, "source": "redis"})

    total, entries = _leaderboard_from_mysql(limit, offset)
    return JsonResponse({"total": total, "entries": entries, "source": "mysql"})