"""重建排行榜缓存（开发期用）：清空 ZSET → 从 MySQL 全量重建 → 打印榜面。

⚠️ 只在开发/演示时用。生产环境 Redis 丢了应该由服务端自己的写路径补回来，
   不该靠手工脚本。
"""

import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from accounts.scoring import _redis_client, rebuild_cache_from_mysql  # noqa: E402


def main() -> None:
    client = _redis_client()
    key = settings.LEADERBOARD_KEY
    removed = client.zcard(key)
    client.delete(key)
    print(f"  清空 {key}：原有 {removed} 条")

    count = rebuild_cache_from_mysql()
    print(f"  从 MySQL 重建：写入 {count} 条，ZCARD={client.zcard(key)}")

    raw = client.zrevrange(key, 0, 9, withscores=True)
    print("  榜面前 10：")
    for index, (member, score) in enumerate(raw, start=1):
        print(f"    #{index}  user_id={member.decode()}  score={int(score)}")


if __name__ == "__main__":
    main()