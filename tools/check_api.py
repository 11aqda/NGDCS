"""步骤 10 的接口自测：三个 HTTP 接口 + Redis 排行榜路径。

直接打真实的 `runserver`，不做 mock —— 因为这一层的坑几乎全在"真实链路"上
（驱动、字符集、CSRF、Redis 连不上时的退路），mock 掉就测不到了。
"""

import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ok = 0
fail = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok, fail
    if condition:
        ok += 1
        print(f"  ✅ {label}")
    else:
        fail += 1
        print(f"  ❌ {label}  {detail}")


def post(path: str, payload: dict) -> requests.Response:
    return requests.post(f"{BASE}{path}", json=payload, timeout=5)


def get(path: str) -> requests.Response:
    return requests.get(f"{BASE}{path}", timeout=5)


name = f"tester{int(time.time()) % 100000}"

print("=== 注册 ===")
r = post("/api/auth/register", {"username": name, "password": "secret123"})
check("注册 201", r.status_code == 201, f"实际 {r.status_code} {r.text[:120]}")
body = r.json() if r.status_code < 300 else {}
check("返回 token", bool(body.get("token")))
check("返回用户名", body.get("username") == name)
token = body.get("token", "")
user_id = body.get("user_id", 0)

print("=== 注册校验 ===")
r = post("/api/auth/register", {"username": name, "password": "secret123"})
check("重名 409", r.status_code == 409, f"实际 {r.status_code}")
r = post("/api/auth/register", {"username": "ab", "password": "secret123"})
check("用户名太短 400", r.status_code == 400, f"实际 {r.status_code}")
r = post("/api/auth/register", {"username": "abcdefg", "password": "123"})
check("密码太短 400", r.status_code == 400, f"实际 {r.status_code}")
r = requests.post(f"{BASE}/api/auth/register", data=b"not json", timeout=5)
check("非法 JSON 400", r.status_code == 400, f"实际 {r.status_code}")

print("=== 登录 ===")
r = post("/api/auth/login", {"username": name, "password": "secret123"})
check("登录 200", r.status_code == 200, f"实际 {r.status_code}")
check("登录返回新 token", bool(r.json().get("token")))
r = post("/api/auth/login", {"username": name, "password": "wrongpass"})
check("错密码 401", r.status_code == 401, f"实际 {r.status_code}")
r = post("/api/auth/login", {"username": "no_such_user_xyz", "password": "x"})
check("用户不存在也是 401（不泄漏）", r.status_code == 401, f"实际 {r.status_code}")
check(
    "两种失败回复同一句话",
    r.json().get("error") == "用户名或密码错误",
    r.text[:120],
)

print("=== 排行榜（空）===")
r = get("/api/leaderboard")
check("空榜 200", r.status_code == 200, f"实际 {r.status_code}")
check("返回 entries 列表", isinstance(r.json().get("entries"), list))

print("=== 写入成绩后查榜 ===")
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp.settings")
sys.path.insert(0, ".")
import django

django.setup()
from django.contrib.auth.models import User

from accounts.models import ScoreRecord
from accounts.scoring import record_result

user = User.objects.get(username=name)
ScoreRecord.objects.filter(user=user).delete()
# 走**真实写入路径**：MySQL + Redis 都写（写透缓存，见 accounts/scoring.py）
record_result(user.id, 777, level=2, kills=77)
record_result(user.id, 333, level=1, kills=33)

r = get("/api/leaderboard?limit=5")
data = r.json()
check("查榜 200", r.status_code == 200)
mine = [e for e in data.get("entries", []) if e["username"] == name]
check("能查到自己的成绩", bool(mine), json.dumps(data, ensure_ascii=False)[:200])
if mine:
    check("best_score 取最大值 777", mine[0]["best_score"] == 777, str(mine[0]))
    check("games 统计为 2 局", mine[0]["games"] == 2, str(mine[0]))
    check("max_level 取最大值 2", mine[0]["max_level"] == 2, str(mine[0]))
check("total 是人数", data.get("total", 0) >= 1, str(data.get("total")))
check("未命中 Redis 时来源是 mysql", data.get("source") in ("mysql", "redis"), data.get("source"))
print(f"     source={data.get('source')}  total={data.get('total')}")

print("=== 参数校验 ===")
r = get("/api/leaderboard?limit=abc")
check("limit 非法 400", r.status_code == 400, f"实际 {r.status_code}")
r = get("/api/leaderboard?limit=999")
check("limit 上限被夹到 100", r.status_code == 200)

print("=== 方法限制 ===")
r = requests.get(f"{BASE}/api/auth/login", timeout=5)
check("login 用 GET 返回 405", r.status_code == 405, f"实际 {r.status_code}")

print()
print(f"  结果：{ok} 通过，{fail} 失败")
sys.exit(0 if fail == 0 else 1)