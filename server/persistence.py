"""TCP 服务端 ↔ Django 数据层的桥（步骤 10b）。

## 为什么需要这个桥

分数要由**服务端**在结算时写进 MySQL + Redis（`04 §3.1` 取消了 `/api/scores`，
客户端根本没有上报接口）。但 TCP 服务端是纯 asyncio 进程，不认 Django。

## 三条硬约束

### ① 绝不能阻塞 tick loop

Django ORM 是**同步阻塞**的。在 20 Hz 的 tick 里直接调用 MySQL/Redis，
等于把数据库延迟算进帧耗时 —— E9 测过 tick 只有 5.7 ms，一次 20 ms 的写库就能掉帧。
所以全部走 `asyncio.to_thread()`（D-006 的同一思路：同步 IO 放线程池）。

### ② 默认**关闭**（`--persist-scores`）

E9 / E1 / E2 / E8 的实验数据全部是在"不碰数据库"的条件下测的。
如果服务端默认连库，那些基线就悄悄多了数据库开销 —— 而且不会报错，只是数据变了。
**实验脚本永远不传这个开关，游戏演示才传。**

### ③ 数据库不可用时**不能影响对局**

连不上 MySQL / Redis 时只记日志：认证退化成匿名玩家、结算跳过写库。
**玩游戏不能因为数据库挂了就崩。**

## 为什么用 Django 而不是裸 pymysql

写分逻辑（`accounts/scoring.py::record_result`）里已经有"先 MySQL 再 Redis、
写透缓存、失败只记日志"的完整语义。用裸 pymysql 再实现一遍就会有两份可能走岔的实现 ——
**服务端和 HTTP 层写的是同一张表，必须走同一段代码。**
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_READY = False
_UNAVAILABLE = False


def _ensure_django() -> bool:
    """懒加载 Django。**只初始化一次**，失败也记住，不再重试刷屏。"""
    global _READY, _UNAVAILABLE
    if _READY:
        return True
    if _UNAVAILABLE:
        return False

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp.settings")
    try:
        import django

        django.setup()
        _READY = True
        return True
    except Exception as exc:  # noqa: BLE001
        _UNAVAILABLE = True
        logger.warning("Django 初始化失败，成绩持久化不可用：%s", exc)
        return False


def _authenticate_blocking(token: str) -> tuple[int, str] | None:
    """token → (user_id, nickname)。无效返回 None。"""
    if not _ensure_django():
        return None
    from accounts.models import AuthToken

    row = (
        AuthToken.objects.filter(token=token)
        .values("user_id", "user__username")
        .first()
    )
    if row is None:
        return None
    return row["user_id"], row["user__username"]


def _record_blocking(user_id: int, score: int, level: int, kills: int) -> bool:
    if not _ensure_django():
        return False
    from accounts.scoring import record_result

    record_result(user_id, score, level=level, kills=kills)
    return True


async def authenticate_token(token: str) -> tuple[int, str] | None:
    """异步包装：真正的查询在**线程池**里跑，不阻塞事件循环。"""
    try:
        return await asyncio.to_thread(_authenticate_blocking, token)
    except Exception as exc:  # noqa: BLE001 - 数据库故障不该让连接崩掉
        logger.warning("token 认证失败（数据库不可用？）：%s", exc)
        return None


async def persist_score(user_id: int, score: int, level: int = 1, kills: int = 0) -> bool:
    """异步写一局成绩（MySQL + Redis，写透）。失败只记日志。"""
    try:
        return await asyncio.to_thread(_record_blocking, user_id, score, level, kills)
    except Exception as exc:  # noqa: BLE001
        logger.warning("成绩写入失败（不影响对局）：%s", exc)
        return False