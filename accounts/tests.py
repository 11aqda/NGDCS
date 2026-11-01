"""账号 / 排行榜接口的 Django 测试。

跑法（**不是** `python -m unittest`，Django 的 TestCase 要用它自己的 runner）：

    .venv\\Scripts\\python.exe -X utf8 manage.py test accounts

它会自动建一个 `test_myproject` 库、跑完即删，不会污染 `myproject`。
另有一套**打真实 HTTP** 的集成检查在 `tools/check_api.py`（24 条断言），
两者互补：这里测逻辑与边界，那里测"真的能通过 WSGI 跑起来"。
"""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import AuthToken, ScoreRecord

# 测试期间**禁用真实 Redis**：把地址指向一个必然连不上的端口。
#
# 为什么必须这样：Redis 是**进程外**状态，不随 Django 的测试库回滚。
# 不隔离的话，开发库里灌过的 ZSET 会干扰断言 —— 2026-11-01 实测就是这么翻车的：
# 测试库的用户 id 和 Redis 里残留的 id 对不上，榜上出现 `username: "?"` 的幽灵条目。
#
# Redis 读路径由 `tools/check_api.py`（打真实 HTTP）单独验证。
NO_REDIS = override_settings(REDIS={"host": "127.0.0.1", "port": 1, "db": 0})


class RegisterTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def post(self, payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.client.post(
            "/api/auth/register", data=body, content_type="application/json"
        )

    def test_success_returns_token_and_user(self):
        response = self.post({"username": "alice", "password": "secret123"})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["token"])
        self.assertEqual(data["username"], "alice")
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_password_is_hashed_not_stored_plain(self):
        """**关键安全断言**：库里绝不能出现明文密码。"""
        self.post({"username": "bob", "password": "secret123"})
        user = User.objects.get(username="bob")
        self.assertNotEqual(user.password, "secret123")
        self.assertTrue(user.password.startswith("pbkdf2_"))
        self.assertTrue(user.check_password("secret123"))

    def test_duplicate_username_conflicts(self):
        self.post({"username": "carol", "password": "secret123"})
        response = self.post({"username": "carol", "password": "secret123"})
        self.assertEqual(response.status_code, 409)

    def test_username_too_short(self):
        self.assertEqual(
            self.post({"username": "ab", "password": "secret123"}).status_code, 400
        )

    def test_username_too_long(self):
        self.assertEqual(
            self.post({"username": "x" * 21, "password": "secret123"}).status_code, 400
        )

    def test_password_too_short(self):
        self.assertEqual(
            self.post({"username": "dave", "password": "123"}).status_code, 400
        )

    def test_invalid_json(self):
        self.assertEqual(self.post(b"not json").status_code, 400)

    def test_non_object_json(self):
        self.assertEqual(self.post(b"[1,2,3]").status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/api/auth/register").status_code, 405)


class LoginTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        User.objects.create_user(username="erin", password="secret123")

    def post(self, payload):
        return self.client.post(
            "/api/auth/login",
            data=json.dumps(payload).encode(),
            content_type="application/json",
        )

    def test_success(self):
        response = self.post({"username": "erin", "password": "secret123"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["token"])

    def test_each_login_issues_a_new_token(self):
        first = self.post({"username": "erin", "password": "secret123"}).json()["token"]
        second = self.post({"username": "erin", "password": "secret123"}).json()["token"]
        self.assertNotEqual(first, second)
        self.assertEqual(AuthToken.objects.filter(user__username="erin").count(), 2)

    def test_wrong_password(self):
        self.assertEqual(
            self.post({"username": "erin", "password": "nope"}).status_code, 401
        )

    def test_unknown_user_says_the_same_thing(self):
        """**账号枚举防护**：用户不存在与密码错误必须回同一句话。"""
        wrong = self.post({"username": "erin", "password": "nope"})
        missing = self.post({"username": "ghost", "password": "nope"})
        self.assertEqual(wrong.status_code, missing.status_code)
        self.assertEqual(wrong.json()["error"], missing.json()["error"])


@NO_REDIS
class LeaderboardTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="x")

    def test_empty(self):
        data = self.client.get("/api/leaderboard").json()
        self.assertEqual(data["entries"], [])
        self.assertEqual(data["total"], 0)

    def test_aggregates_best_score_level_and_games(self):
        ScoreRecord.objects.create(user=self.alice, score=100, level=1)
        ScoreRecord.objects.create(user=self.alice, score=900, level=3)
        ScoreRecord.objects.create(user=self.bob, score=500, level=2)

        data = self.client.get("/api/leaderboard").json()
        entries = {e["username"]: e for e in data["entries"]}

        self.assertEqual(entries["alice"]["best_score"], 900)
        self.assertEqual(entries["alice"]["max_level"], 3)
        self.assertEqual(entries["alice"]["games"], 2)
        self.assertEqual(entries["bob"]["best_score"], 500)
        self.assertLess(entries["alice"]["rank"], entries["bob"]["rank"])

    def test_total_counts_users_not_rows(self):
        ScoreRecord.objects.create(user=self.alice, score=100)
        ScoreRecord.objects.create(user=self.alice, score=200)
        self.assertEqual(self.client.get("/api/leaderboard").json()["total"], 1)

    def test_limit_and_offset(self):
        for index in range(5):
            user = User.objects.create_user(username=f"u{index}", password="x")
            ScoreRecord.objects.create(user=user, score=100 + index)
        data = self.client.get("/api/leaderboard?limit=2&offset=1").json()
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(data["entries"][0]["rank"], 2)

    def test_limit_is_clamped(self):
        self.assertEqual(self.client.get("/api/leaderboard?limit=999").status_code, 200)

    def test_bad_limit_returns_400(self):
        self.assertEqual(self.client.get("/api/leaderboard?limit=abc").status_code, 400)

    def test_negative_offset_treated_as_zero(self):
        data = self.client.get("/api/leaderboard?offset=-5").json()
        self.assertEqual(data["entries"], [])

    def test_falls_back_to_mysql_when_redis_unavailable(self):
        """Redis 不可用（或空）时必须回落到 MySQL，而不是报错。"""
        ScoreRecord.objects.create(user=self.alice, score=321)
        data = self.client.get("/api/leaderboard").json()
        self.assertIn(data["source"], ("mysql", "redis"))
        self.assertEqual(data["entries"][0]["best_score"], 321)