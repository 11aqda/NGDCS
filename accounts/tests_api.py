"""`/api/v2/runs/` 的接口测试（DRF 只读资源）。

覆盖验收四条：管理员 200 / 匿名 401 或 403 / 分页·搜索·排序 / 只读 405。
另外确认旧的 `/api/leaderboard` 没被影响。
"""

from __future__ import annotations

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from accounts.models import ScoreRecord

URL = "/api/v2/runs/"


class RunApiTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            "admin", password="not-used", is_staff=True
        )
        cls.alice = User.objects.create_user("alice", password="not-used")
        cls.bob = User.objects.create_user("bob", password="not-used")

        cls.admin_records = [
            ScoreRecord.objects.create(user=cls.admin, score=100 + i, level=2, kills=i)
            for i in range(10)
        ]
        cls.alice_records = [
            ScoreRecord.objects.create(user=cls.alice, score=200 + i, level=3, kills=i)
            for i in range(13)
        ]
        cls.bob_records = [
            ScoreRecord.objects.create(user=cls.bob, score=500 + i, level=1, kills=i)
            for i in range(5)
        ]

    # ---- 权限 ----

    def test_admin_can_list(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 28)
        self.assertEqual(len(resp.data["results"]), 20)  # 默认每页 20
        self.assertIsNotNone(resp.data["next"])

    def test_anonymous_is_denied(self):
        resp = self.client.get(URL)
        # SessionAuthentication 不给 WWW-Authenticate → DRF 返回 403；两种都算通过
        self.assertIn(resp.status_code, (401, 403))

    def test_non_staff_is_denied(self):
        self.client.force_authenticate(self.alice)
        resp = self.client.get(URL)
        self.assertIn(resp.status_code, (401, 403))

    # ---- 资源 ----

    def test_detail(self):
        record = self.alice_records[0]
        self.client.force_authenticate(self.admin)
        resp = self.client.get(f"{URL}{record.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], record.id)
        self.assertEqual(resp.data["username"], "alice")

    def test_serializer_shape(self):
        self.client.force_authenticate(self.admin)
        item = self.client.get(URL).data["results"][0]
        self.assertEqual(
            set(item.keys()),
            {"id", "username", "score", "level", "kills", "created_at"},
        )

    # ---- 分页 / 搜索 / 排序 ----

    def test_page_size_and_page(self):
        self.client.force_authenticate(self.admin)
        first = self.client.get(URL, {"page_size": 5})
        second = self.client.get(URL, {"page_size": 5, "page": 2})
        self.assertEqual(len(first.data["results"]), 5)
        self.assertEqual(len(second.data["results"]), 5)
        self.assertNotEqual(
            [row["id"] for row in first.data["results"]],
            [row["id"] for row in second.data["results"]],
        )

    def test_search_by_username(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get(URL, {"search": "alice"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 13)
        self.assertTrue(
            all(row["username"] == "alice" for row in resp.data["results"])
        )

    def test_ordering_default_is_score_desc(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get(URL)
        scores = [row["score"] for row in resp.data["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ordering_asc(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get(URL, {"ordering": "score"})
        scores = [row["score"] for row in resp.data["results"]]
        self.assertEqual(scores, sorted(scores))

    # ---- 只读 ----

    def test_post_is_rejected(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(URL, {"score": 1}, format="json")
        self.assertEqual(resp.status_code, 405)

    def test_delete_is_rejected(self):
        record = self.admin_records[0]
        self.client.force_authenticate(self.admin)
        resp = self.client.delete(f"{URL}{record.id}/")
        self.assertEqual(resp.status_code, 405)


class ExistingApiUntouchedTest(APITestCase):
    def test_leaderboard_still_works(self):
        resp = self.client.get("/api/leaderboard")
        self.assertEqual(resp.status_code, 200)
        # 旧接口是纯 Django JsonResponse，不是 DRF Response，所以用 .json()
        self.assertIn("entries", resp.json())
