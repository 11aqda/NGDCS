"""E4 代理的测试：损伤配置的数学 + 保序语义。

代理本身是异步 IO，端到端的延迟验证放在实验里做（见 `tools/run_e4.py` 的预实验记录）。
这里用测试钉住两件最容易改错的事：

1. **`LinkConfig` 的注入强度**：延迟、抖动上限、丢包概率换算成额外延迟
2. **保序**：抖动/丢包会让不同块的延迟不同，但写出去的**字节顺序必须不变**
   —— 一旦乱序，TCP 流就毁了，对端解析器直接崩，而且现象是"偶发协议错误"，极难查
"""

import asyncio
import random
import unittest

from tools.netem_proxy import LinkConfig, ProxyStats, _pump


class LinkConfigTest(unittest.TestCase):
    def test_no_damage_means_no_delay(self):
        link = LinkConfig()
        for _ in range(50):
            delay, retransmit = link.next_delay_s(random.Random(1))
            self.assertEqual(delay, 0.0)
            self.assertFalse(retransmit)

    def test_fixed_delay_is_exact(self):
        link = LinkConfig(delay_ms=100)
        rng = random.Random(7)
        for _ in range(20):
            delay, retransmit = link.next_delay_s(rng)
            self.assertAlmostEqual(delay, 0.1, places=9)
            self.assertFalse(retransmit)

    def test_jitter_stays_within_range(self):
        """抖动是 `[delay, delay + jitter]` 的均匀分布，**不会超过上界**。"""
        link = LinkConfig(delay_ms=50, jitter_ms=30)
        rng = random.Random(3)
        values = [link.next_delay_s(rng)[0] * 1000 for _ in range(200)]
        self.assertGreaterEqual(min(values), 50.0)
        self.assertLessEqual(max(values), 80.0 + 1e-9)
        # 200 次采样应该铺开，而不是全挤在一个值上
        self.assertGreater(max(values) - min(values), 10.0)

    def test_loss_injects_one_rto(self):
        """丢包被模拟成**额外的 RTO 延迟**，不是"丢掉数据"。"""
        link = LinkConfig(delay_ms=0, loss_pct=100, rto_ms=200)
        delay, retransmit = link.next_delay_s(random.Random(1))
        self.assertTrue(retransmit)
        self.assertAlmostEqual(delay, 0.2, places=9)

    def test_loss_probability_is_roughly_right(self):
        link = LinkConfig(loss_pct=20, rto_ms=200)
        rng = random.Random(11)
        hits = sum(1 for _ in range(2000) if link.next_delay_s(rng)[1])
        # 2000 次采样、20% 期望 400 次；给足容差但能抓住"概率写反/单位错"
        self.assertGreater(hits, 320)
        self.assertLess(hits, 480)

    def test_zero_loss_never_triggers(self):
        link = LinkConfig(loss_pct=0.0)
        rng = random.Random(5)
        self.assertFalse(any(link.next_delay_s(rng)[1] for _ in range(500)))

    def test_negative_values_are_clamped(self):
        link = LinkConfig(delay_ms=-100, jitter_ms=-5, loss_pct=-10, rto_ms=-1)
        self.assertEqual(link.delay_ms, 0.0)
        self.assertEqual(link.jitter_ms, 0.0)
        self.assertEqual(link.loss_pct, 0.0)
        self.assertEqual(link.rto_ms, 0.0)

    def test_loss_pct_over_100_is_clamped(self):
        self.assertEqual(LinkConfig(loss_pct=250).loss_pct, 100.0)


class _FakeWriter:
    """把 write 的内容按顺序收集起来，代替真实 StreamWriter。"""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.chunks.append(bytes(data))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class PumpOrderingTest(unittest.TestCase):
    """**保序**是这个模块最容易翻车的地方，单独立一组测试。"""

    def _run(self, chunks: list[bytes], link: LinkConfig) -> bytes:
        async def scenario() -> bytes:
            reader = asyncio.StreamReader()
            for chunk in chunks:
                reader.feed_data(chunk)
            reader.feed_eof()

            writer = _FakeWriter()
            await _pump(reader, writer, link, random.Random(42), ProxyStats(), "down")
            return b"".join(writer.chunks)

        return asyncio.run(scenario())

    def test_order_without_damage(self):
        chunks = [b"AAA", b"BBB", b"CCC", b"DDD"]
        self.assertEqual(self._run(chunks, LinkConfig()), b"AAABBBCCCDDD")

    def test_order_with_jitter(self):
        """抖动让每块的延迟不同，但**写出顺序必须与读入一致**。

        如果实现改成"谁先到截止时刻谁先写"，这里就会挂 —— 而那正是坑。
        """
        chunks = [b"one", b"two", b"three", b"four", b"five"]
        link = LinkConfig(jitter_ms=30)
        self.assertEqual(self._run(chunks, link), b"onetwothreefourfive")

    def test_order_with_loss(self):
        """丢包注入的是延迟，不是丢数据 —— **字节一个都不能少**。

        这点和 `bot --sim-loss`（真的丢帧）本质不同，测试要能区分开。
        """
        chunks = [b"x" * 10, b"y" * 10, b"z" * 10]
        link = LinkConfig(loss_pct=50, rto_ms=1)  # RTO 调小，别让测试等 200ms
        self.assertEqual(self._run(chunks, link), b"x" * 10 + b"y" * 10 + b"z" * 10)

    def test_empty_stream_closes_writer(self):
        async def scenario() -> bool:
            reader = asyncio.StreamReader()
            reader.feed_eof()
            writer = _FakeWriter()
            await _pump(reader, writer, LinkConfig(), random.Random(1),
                        ProxyStats(), "up")
            return writer.closed

        self.assertTrue(asyncio.run(scenario()))

    def test_stats_count_bytes(self):
        async def scenario() -> ProxyStats:
            reader = asyncio.StreamReader()
            reader.feed_data(b"12345")
            reader.feed_eof()
            stats = ProxyStats()
            await _pump(reader, _FakeWriter(), LinkConfig(), random.Random(1),
                        stats, "up")
            return stats

        stats = asyncio.run(scenario())
        self.assertEqual(stats.up_bytes, 5)
        self.assertEqual(stats.down_bytes, 0)


if __name__ == "__main__":
    unittest.main()