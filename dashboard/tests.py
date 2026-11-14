"""看板实时指标的取数逻辑：Redis 优先，CSV 回退。

不连真实 Redis —— 用 mock 替掉 `_redis_client` / `_read_live_metrics`，
这样 CI 里没有 Redis 也能跑。
"""

from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from dashboard import views


def stamp(offset_seconds: int = 0) -> str:
    return (datetime.now() + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def live_data(**overrides) -> dict:
    data = {
        "timestamp": stamp(),
        "client_count": "4",
        "tick_ms_p95": "1.2",
        "bytes_out": "7804",
        "snapshot_bytes": "1927",
        "cpu_percent": "2.5",
    }
    data.update(overrides)
    return data


class ParseLiveMetricsTest(SimpleTestCase):
    def test_fresh_hash_becomes_dashboard_dict(self):
        got = views._parse_live_metrics(live_data())
        self.assertEqual(got["online"], 4)
        self.assertEqual(got["tick_p95"], 1.2)
        self.assertEqual(got["snapshot_bytes"], 1927)
        self.assertAlmostEqual(got["bandwidth_kbps"], 7804 / 1024)
        self.assertEqual(got["cpu_percent"], 2.5)
        self.assertEqual(got["source"], "redis")
        self.assertTrue(got["live"])
        self.assertGreaterEqual(got["age"], 0)

    def test_stale_hash_is_ignored(self):
        # 超过 TTL 就不认：防止 key 被别的东西续命却写的是旧数据
        self.assertIsNone(
            views._parse_live_metrics(live_data(timestamp=stamp(-30)))
        )

    def test_missing_timestamp_is_ignored(self):
        data = live_data()
        del data["timestamp"]
        self.assertIsNone(views._parse_live_metrics(data))

    def test_empty_hash_is_ignored(self):
        self.assertIsNone(views._parse_live_metrics({}))

    def test_bad_numbers_are_ignored(self):
        self.assertIsNone(
            views._parse_live_metrics(live_data(client_count="not-a-number"))
        )


class ReadLiveMetricsTest(SimpleTestCase):
    def test_redis_error_returns_none(self):
        with mock.patch.object(
            views, "_redis_client", side_effect=ConnectionError("redis down")
        ):
            self.assertIsNone(views._read_live_metrics())

    def test_empty_redis_returns_none(self):
        client = mock.Mock()
        client.hgetall.return_value = {}
        with mock.patch.object(views, "_redis_client", return_value=client):
            self.assertIsNone(views._read_live_metrics())

    def test_redis_hash_is_used(self):
        client = mock.Mock()
        client.hgetall.return_value = live_data()
        with mock.patch.object(views, "_redis_client", return_value=client):
            got = views._read_live_metrics()
        self.assertEqual(got["source"], "redis")
        client.hgetall.assert_called_once_with(settings.LIVE_METRICS_KEY)


class LatestMetricsTest(SimpleTestCase):
    def test_prefers_redis(self):
        with mock.patch.object(
            views, "_read_live_metrics", return_value={"online": 7, "source": "redis"}
        ):
            self.assertEqual(views._latest_metrics()["online"], 7)
            self.assertEqual(views._latest_metrics()["source"], "redis")

    def test_falls_back_to_csv(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "server_metrics.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "timestamp",
                    "client_count",
                    "tick_ms_p95",
                    "bytes_out",
                    "snapshot_bytes",
                    "cpu_percent",
                ]
            )
            writer.writerow([stamp(), "2", "3.4", "2048", "512", "1.5"])

        with override_settings(METRICS_CSV=path), mock.patch.object(
            views, "_read_live_metrics", return_value=None
        ):
            got = views._latest_metrics()

        self.assertEqual(got["source"], "csv")
        self.assertEqual(got["online"], 2)
        self.assertEqual(got["snapshot_bytes"], 512)
        self.assertTrue(got["live"])

    def test_nothing_available_returns_none(self):
        with mock.patch.object(views, "_read_live_metrics", return_value=None), \
             override_settings(METRICS_CSV=Path("Z:/no/such/file.csv")):
            self.assertIsNone(views._latest_metrics())


class SettingsTest(SimpleTestCase):
    def test_metrics_csv_defaults_to_workspace_data(self):
        # 没设 NGDCS_METRICS_CSV 时，默认读本工作区 data/（14 §11.10）
        self.assertEqual(
            settings.METRICS_CSV,
            settings.BASE_DIR / "data" / "server_metrics.csv",
        )

    def test_live_metrics_key_and_ttl(self):
        self.assertEqual(settings.LIVE_METRICS_KEY, "ngdcs:metrics:live")
        self.assertEqual(settings.LIVE_METRICS_TTL, 10)
