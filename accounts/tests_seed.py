"""`seed_demo` 命令的测试：幂等、密码来自环境变量、演示数据可辨认。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import ScoreRecord
from accounts.management.commands.seed_demo import DEMO_PLAYERS, RECORDS_PER_PLAYER

PASSWORD = "unit-test-secret-9f3a"


def run_seed() -> str:
    out = StringIO()
    call_command("seed_demo", stdout=out)
    return out.getvalue()


class SeedDemoTest(TestCase):
    def test_requires_password_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEMO_PASSWORD", None)
            with self.assertRaises(CommandError):
                call_command("seed_demo", stdout=StringIO())
        self.assertFalse(User.objects.filter(username="demo").exists())

    @mock.patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}, clear=False)
    def test_creates_staff_players_and_records(self):
        run_seed()

        admin = User.objects.get(username="demo")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.check_password(PASSWORD))

        names = [name for name, _ in DEMO_PLAYERS]
        self.assertEqual(User.objects.filter(username__in=names).count(), len(names))
        self.assertEqual(
            ScoreRecord.objects.filter(user__username__in=names).count(),
            len(names) * RECORDS_PER_PLAYER,
        )

    @mock.patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}, clear=False)
    def test_is_idempotent(self):
        run_seed()
        first = set(
            ScoreRecord.objects.filter(user__username__startswith="demo_").values_list(
                "id", flat=True
            )
        )
        run_seed()
        second = set(
            ScoreRecord.objects.filter(user__username__startswith="demo_").values_list(
                "id", flat=True
            )
        )
        self.assertEqual(len(first), len(second))
        self.assertEqual(len(second), len(DEMO_PLAYERS) * RECORDS_PER_PLAYER)
        # 重建（id 换新），不是累加
        self.assertFalse(first & second)

    @mock.patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}, clear=False)
    def test_password_never_printed(self):
        output = run_seed()
        self.assertNotIn(PASSWORD, output)

    @mock.patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}, clear=False)
    def test_records_spread_over_last_week(self):
        run_seed()
        rows = ScoreRecord.objects.filter(user__username__startswith="demo_")
        now = datetime.now()
        for created_at in rows.values_list("created_at", flat=True):
            self.assertLessEqual(created_at, now + timedelta(seconds=5))
            self.assertGreaterEqual(created_at, now - timedelta(days=7, minutes=5))

    @mock.patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}, clear=False)
    def test_demo_can_open_dashboard(self):
        run_seed()
        self.assertTrue(self.client.login(username="demo", password=PASSWORD))
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        self.assertEqual(self.client.get("/api/v2/runs/").status_code, 200)
