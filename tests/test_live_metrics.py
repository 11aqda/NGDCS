"""`server/live_metrics.py` 与 `--live-metrics` 的单元测试。

**不连真实 Redis**：用一个记录调用的假客户端，所以断网/没装 Redis 也能跑。
真实链路的冒烟在交付时另做（Redis 起/停两种）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from server.live_metrics import (
    LIVE_METRICS_KEY,
    LIVE_METRICS_TTL,
    LiveMetricsPublisher,
)


class FakePipeline:
    def __init__(self, log: list):
        self.log = log

    def hset(self, key, mapping=None):  # noqa: N802 - 模仿 redis-py
        self.log.append(("hset", key, dict(mapping or {})))
        return self

    def expire(self, key, ttl):  # noqa: N802
        self.log.append(("expire", key, ttl))
        return self

    def execute(self):
        self.log.append(("execute",))
        return []


class FakeRedis:
    def __init__(self, log: list | None = None):
        self.log = log if log is not None else []

    def pipeline(self):
        return FakePipeline(self.log)


class BrokenRedis:
    def pipeline(self):
        raise ConnectionError("redis down")


def sample_row(**overrides) -> dict:
    row = {
        "timestamp": "2026-11-14T18:00:00",
        "t_mono": 1.5,
        "scenario_id": "adhoc",
        "client_count": 4,
        "enemies": 30,
        "bullets": 200,
        "tick_ms_avg": 1.0,
        "tick_ms_p95": 1.2,
        "tick_ms_max": 1.5,
        "sim_ms": 0.2,
        "collision_ms": 0.4,
        "ser_ms": 0.3,
        "net_ms": 0.1,
        "encode_ms": 0.05,
        "hits": 3,
        "snapshot_bytes": 1927,
        "cpu_percent": 2.0,
        "cpu_seconds": 1.0,
        "mem_mb": 80.0,
        "packets_out": 80,
        "bytes_out": 7804,
        "packets_in": 80,
        "bytes_in": 1040,
    }
    row.update(overrides)
    return row


class PublisherWriteTest(unittest.TestCase):
    def test_defaults(self):
        # key / TTL 是定死的口径（14 §11.10），改了就两边对不上
        self.assertEqual(LIVE_METRICS_KEY, "ngdcs:metrics:live")
        self.assertEqual(LIVE_METRICS_TTL, 10)

    def test_write_sets_hash_and_ttl(self):
        fake = FakeRedis()
        pub = LiveMetricsPublisher(client=fake)
        pub._write_now({"client_count": 4, "tick_ms_p95": 1.2})

        hset = [entry for entry in fake.log if entry[0] == "hset"]
        expire = [entry for entry in fake.log if entry[0] == "expire"]
        self.assertEqual(len(hset), 1)
        self.assertEqual(hset[0][1], LIVE_METRICS_KEY)
        self.assertEqual(hset[0][2], {"client_count": 4, "tick_ms_p95": 1.2})
        self.assertEqual(expire, [("expire", LIVE_METRICS_KEY, LIVE_METRICS_TTL)])
        # HSET 与 EXPIRE 必须在同一个 pipeline 里（一次往返，且不会只写一半）
        self.assertEqual(fake.log[-1], ("execute",))

    def test_custom_key_and_ttl(self):
        fake = FakeRedis()
        pub = LiveMetricsPublisher(client=fake, key="custom:key", ttl=3)
        pub._write_now({"a": 1})
        self.assertIn(("expire", "custom:key", 3), fake.log)


class PublisherAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_consume_once_writes(self):
        fake = FakeRedis()
        pub = LiveMetricsPublisher(client=fake)
        pub.publish({"a": 1})
        await pub.consume_once()
        self.assertEqual(pub.written, 1)
        self.assertEqual(pub.failed, 0)
        self.assertIn(("hset", LIVE_METRICS_KEY, {"a": 1}), fake.log)

    async def test_redis_failure_is_swallowed(self):
        pub = LiveMetricsPublisher(client=BrokenRedis())
        pub.publish({"a": 1})
        await pub.consume_once()  # 不抛 = 不影响 tick
        self.assertEqual(pub.failed, 1)
        self.assertEqual(pub.written, 0)

    async def test_queue_full_drops_oldest(self):
        fake = FakeRedis()
        pub = LiveMetricsPublisher(client=fake, queue_size=1)
        pub.publish({"n": 1})
        pub.publish({"n": 2})  # 队列满 → 丢掉旧的
        await pub.consume_once()
        self.assertIn(("hset", LIVE_METRICS_KEY, {"n": 2}), fake.log)

    async def test_start_and_stop(self):
        pub = LiveMetricsPublisher(client=FakeRedis())
        task = pub.start()
        self.assertFalse(task.done())
        await pub.stop()
        self.assertTrue(task.cancelled() or task.done())

    async def test_publish_without_loop_does_not_raise(self):
        # 生产里 publish 只在事件循环内调用；这里只确认它不依赖 await
        pub = LiveMetricsPublisher(client=FakeRedis())
        for i in range(5):
            pub.publish({"n": i})  # queue_size=2，多余的直接丢
        self.assertLessEqual(pub._queue.qsize(), 2)


class MetricsRecorderBridgeTest(unittest.TestCase):
    """CSV 与 Redis 必须用同一份 row，字段不能各写各的。"""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "server_metrics.csv"

    def make_recorder(self, live=None):
        from server.metrics import MetricsRecorder

        return MetricsRecorder(
            self.path,
            enable_process_stats=False,
            live=live,
        )

    def test_row_is_published_unchanged(self):
        class Capture:
            def __init__(self):
                self.rows = []

            def publish(self, row):
                self.rows.append(row)

        capture = Capture()
        recorder = self.make_recorder(live=capture)
        try:
            row = recorder.write(
                client_count=4,
                enemies=30,
                bullets=200,
                stats={
                    "avg_ms": 1.0,
                    "p95_ms": 1.2,
                    "max_ms": 1.5,
                    "sim_ms": 0.2,
                    "collision_ms": 0.4,
                    "ser_ms": 0.3,
                    "net_ms": 0.1,
                    "encode_ms": 0.05,
                    "hits": 3,
                    "snapshot_bytes": 1927,
                    "packets_out": 80,
                    "bytes_out": 7804,
                    "packets_in": 80,
                    "bytes_in": 1040,
                },
            )
        finally:
            recorder.close()

        self.assertEqual(len(capture.rows), 1)
        self.assertIs(capture.rows[0], row)
        self.assertEqual(row["client_count"], 4)
        self.assertEqual(row["snapshot_bytes"], 1927)
        self.assertIn("timestamp", row)
        # CSV 里也必须真有这一行，不能只发 Redis
        import csv

        with self.path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["client_count"], "4")

    def test_no_live_publisher_is_fine(self):
        recorder = self.make_recorder(live=None)
        try:
            row = recorder.write(
                client_count=0,
                enemies=0,
                bullets=0,
                stats={
                    "avg_ms": 0.1,
                    "p95_ms": 0.1,
                    "max_ms": 0.1,
                    "sim_ms": 0.0,
                    "collision_ms": 0.0,
                    "ser_ms": 0.0,
                    "net_ms": 0.1,
                    "encode_ms": 0.0,
                    "hits": 0,
                    "snapshot_bytes": 0,
                    "packets_out": 0,
                    "bytes_out": 0,
                    "packets_in": 0,
                    "bytes_in": 0,
                },
            )
        finally:
            recorder.close()
        self.assertEqual(row["client_count"], 0)


class FlagTest(unittest.TestCase):
    """--live-metrics 必须默认关：实验基线不能悄悄多出 Redis 开销。"""

    def parse(self, argv):
        from server.main import parse_args

        with mock.patch.object(sys, "argv", argv):
            return parse_args()

    def test_default_off(self):
        args = self.parse(["server"])
        self.assertFalse(args.live_metrics)

    def test_flag_on(self):
        args = self.parse(["server", "--live-metrics"])
        self.assertTrue(args.live_metrics)
