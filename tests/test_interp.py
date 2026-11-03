"""`protocol/interp.py` 的测试 —— 用**已知答案**把公式钉死。

这个模块是 E4 / 图 6-8~6-10 / 6-12 的唯一数据来源，公式写错的后果是
"图画得很漂亮但全是错的"，所以每条都要有能手算验证的用例。
"""

import unittest

from protocol.interp import (
    PlayerInterp,
    clamp_alpha,
    distance,
    lerp_point,
)


class ClampAlphaTest(unittest.TestCase):
    def test_middle(self):
        # 当前帧 t=1.1，两帧间隔 0.1，现在 t=1.15 → 走了半帧 → alpha=0.5
        #
        # ⚠️ 注意：`now` **不可能早于当前帧时间**（客户端总是收到帧之后才渲染），
        # 所以 alpha<0 的情况在真实运行里不会出现，只有钳位的兜底意义。
        self.assertAlmostEqual(clamp_alpha(1.15, 1.0, 1.1), 0.5)

    def test_at_curr_frame_is_zero(self):
        """刚到当前帧时 alpha=0（显示的是**上一帧**的位置）。"""
        self.assertAlmostEqual(clamp_alpha(1.1, 1.0, 1.1), 0.0)

    def test_after_one_interval_is_one(self):
        self.assertAlmostEqual(clamp_alpha(1.2, 1.0, 1.1), 1.0)

    def test_never_extrapolates(self):
        """**钳位**：超过一帧也不外推，最远显示到当前帧。"""
        self.assertEqual(clamp_alpha(99.0, 1.0, 1.1), 1.0)

    def test_never_goes_negative(self):
        self.assertEqual(clamp_alpha(0.0, 1.0, 1.1), 0.0)

    def test_zero_span_is_safe(self):
        """两帧时间戳相同（理论上不该发生）不能除零。"""
        self.assertEqual(clamp_alpha(5.0, 1.0, 1.0), 1.0)


class LerpPointTest(unittest.TestCase):
    def test_endpoints(self):
        self.assertEqual(lerp_point((0, 0), (10, 20), 0.0), (0.0, 0.0))
        self.assertEqual(lerp_point((0, 0), (10, 20), 1.0), (10.0, 20.0))

    def test_midpoint(self):
        self.assertEqual(lerp_point((0, 0), (10, 20), 0.5), (5.0, 10.0))


class PlayerInterpTest(unittest.TestCase):
    def test_first_two_frames_give_no_error(self):
        """前两帧量不了误差 —— 至少要有"上一帧 + 当前帧"才能插值。"""
        track = PlayerInterp()
        self.assertIsNone(track.ingest(1.0, (0.0, 0.0)))
        self.assertIsNone(track.ingest(1.1, (10.0, 0.0)))

    def test_constant_velocity_error_is_one_tick_displacement(self):
        """**核心用例**：匀速直线运动，误差 = 一个帧间隔的位移。

        玩家每帧走 10 px（t=1.1 在 10，t=1.2 在 20）。
        t=1.2 到达那一刻，画面还停在 t=1.1 的位置（alpha 钳到 1）→ 差 10 px。
        """
        track = PlayerInterp()
        track.ingest(1.0, (0.0, 0.0))
        track.ingest(1.1, (10.0, 0.0))
        error = track.ingest(1.2, (20.0, 0.0))
        self.assertAlmostEqual(error, 10.0, places=6)

    def test_error_follows_speed(self):
        """走得越快，同一帧率下误差越大 —— 线性关系。"""
        for speed in (5.0, 10.0, 40.0):
            track = PlayerInterp()
            track.ingest(1.0, (0.0, 0.0))
            track.ingest(1.1, (speed, 0.0))
            error = track.ingest(1.2, (2 * speed, 0.0))
            self.assertAlmostEqual(error, speed, places=6)

    def test_lower_tick_rate_makes_error_bigger(self):
        """**这条是 E5 图 6-12 的立论依据**：帧间隔越大误差越大。

        同样速度 100 px/s：50 ms 一帧走 5 px，100 ms 一帧走 10 px。
        """
        def one_tick_error(frame_s: float) -> float:
            track = PlayerInterp()
            speed = 100.0
            track.ingest(0.0, (0.0, 0.0))
            track.ingest(frame_s, (speed * frame_s, 0.0))
            return track.ingest(2 * frame_s, (speed * 2 * frame_s, 0.0))

        error_50ms = one_tick_error(0.05)
        error_100ms = one_tick_error(0.10)
        self.assertAlmostEqual(error_50ms, 5.0, places=6)
        self.assertAlmostEqual(error_100ms, 10.0, places=6)
        self.assertGreater(error_100ms, error_50ms)

    def test_dropped_frame_doubles_error(self):
        """**丢掉一帧，误差翻倍** —— E4 图 6-8 的核心机制。

        正常帧序列：t=1.0, 1.1, 1.2（每帧 10 px）。
        丢包版本：t=1.0, 1.1, **1.2 丢了**, 1.3。
        t=1.3 到达时，画面还停在 t=1.1（10 px），真值 30 px → 差 20 px。
        """
        normal = PlayerInterp()
        normal.ingest(1.0, (0.0, 0.0))
        normal.ingest(1.1, (10.0, 0.0))
        normal.ingest(1.2, (20.0, 0.0))
        baseline = normal.ingest(1.3, (30.0, 0.0))

        dropped = PlayerInterp()
        dropped.ingest(1.0, (0.0, 0.0))
        dropped.ingest(1.1, (10.0, 0.0))
        # t=1.2 这一帧丢了，直接跳到 1.3
        lossy = dropped.ingest(1.3, (30.0, 0.0))

        self.assertAlmostEqual(baseline, 10.0, places=6)
        self.assertAlmostEqual(lossy, 20.0, places=6)
        self.assertGreater(lossy, baseline)

    def test_displayed_clamps_instead_of_extrapolating(self):
        """长时间没新帧时，画面**冻住**而不是飞出去。"""
        track = PlayerInterp()
        track.ingest(1.0, (0.0, 0.0))
        track.ingest(1.1, (10.0, 0.0))
        # 过了很久（相当于连续丢了很多帧）
        shown = track.displayed(9.0)
        self.assertEqual(shown, (10.0, 0.0))

    def test_summary_percentiles(self):
        track = PlayerInterp()
        track.ingest(0.0, (0.0, 0.0))
        for index in range(1, 101):
            track.ingest(index * 0.1, (index * 1.0, 0.0))
        summary = track.summary()
        # 101 次 ingest，前两帧不产生误差 → 99 个样本
        self.assertEqual(summary["err_px_samples"], 99)
        # 每步 1 px → 每个样本的误差都是 1 px
        self.assertAlmostEqual(summary["err_px_mean"], 1.0, places=6)
        self.assertAlmostEqual(summary["err_px_p95"], 1.0, places=6)

    def test_empty_summary_is_null_not_zero(self):
        """没有样本时返回 None 而不是 0 —— 0 会被画图当成"误差为零"，
        那是最容易骗过自己的假数据（E2 的 P99 就踩过这个坑）。"""
        summary = PlayerInterp().summary()
        self.assertIsNone(summary["err_px_mean"])
        self.assertEqual(summary["err_px_samples"], 0)

    def test_reset_clears_history(self):
        track = PlayerInterp()
        track.ingest(0.0, (0.0, 0.0))
        track.ingest(0.1, (1.0, 0.0))
        track.reset()
        self.assertEqual(track.count, 0)
        self.assertIsNone(track.ingest(0.2, (2.0, 0.0)))


class DistanceTest(unittest.TestCase):
    def test_3_4_5(self):
        self.assertAlmostEqual(distance((0, 0), (3, 4)), 5.0)

    def test_zero(self):
        self.assertEqual(distance((7, 7), (7, 7)), 0.0)


if __name__ == "__main__":
    unittest.main()