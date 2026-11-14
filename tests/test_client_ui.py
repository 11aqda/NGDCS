"""客户端登录 / 排行榜界面的测试（步骤 10c）。

用 `SDL_VIDEODRIVER=dummy` 跑无显示环境 —— 这些测试只验证**逻辑**，
不验证"画面好不好看"（那要靠 `office_render` 或人眼看截图）。

重点覆盖三件事：
1. HTTP 失败时**不能崩**，要能给出可读的错误
2. 登录成功的返回值必须是 `(token, username)`，供上层拿去发 `C_AUTH`
3. 输入框的键盘行为（Tab 切换、退格、长度上限）
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import requests

from client.board import fetch_leaderboard
from client.login import LoginScreen
from client.fonts import load_font


def _surface():
    pygame.display.init()
    return pygame.display.set_mode((720, 960))


class FetchLeaderboardTest(unittest.TestCase):
    def test_parses_entries(self):
        fake = mock.Mock()
        fake.status_code = 200
        fake.json.return_value = {"entries": [{"rank": 1, "username": "a"}]}
        with mock.patch("client.board.requests.get", return_value=fake):
            entries, error = fetch_leaderboard("http://x")
        self.assertEqual(error, "")
        self.assertEqual(entries[0]["username"], "a")

    def test_connection_error_is_soft(self):
        """**连不上服务器不能让界面卡死或崩**，返回空榜 + 可读的错误。"""
        with mock.patch(
            "client.board.requests.get",
            side_effect=requests.ConnectionError("boom"),
        ):
            entries, error = fetch_leaderboard("http://x")
        self.assertEqual(entries, [])
        self.assertIn("连不上", error)

    def test_http_error_reports_server_message(self):
        fake = mock.Mock()
        fake.status_code = 400
        fake.json.return_value = {"error": "limit 非法"}
        with mock.patch("client.board.requests.get", return_value=fake):
            entries, error = fetch_leaderboard("http://x")
        self.assertEqual(entries, [])
        self.assertEqual(error, "limit 非法")

    def test_non_json_response_is_soft(self):
        fake = mock.Mock()
        fake.status_code = 200
        fake.json.side_effect = ValueError("no json")
        with mock.patch("client.board.requests.get", return_value=fake):
            entries, error = fetch_leaderboard("http://x")
        self.assertEqual(entries, [])
        self.assertIn("JSON", error)


class LoginScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = _surface()
        cls.font = load_font(18)
        cls.big_font = load_font(24, bold=True)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def _screen_obj(self) -> LoginScreen:
        return LoginScreen(self.screen, self.font, self.big_font, "http://api")

    def test_empty_fields_is_rejected_locally(self):
        """空用户名/密码**不该发请求** —— 本地就挡住。"""
        screen = self._screen_obj()
        with mock.patch("client.login.requests.post") as post:
            result = screen._submit("login")
        self.assertIsNone(result)
        post.assert_not_called()
        self.assertIn("都要填", screen.message)

    def test_success_returns_token_and_name(self):
        screen = self._screen_obj()
        screen.username = "alice"
        screen.password = "unit-test-password"
        fake = mock.Mock()
        fake.status_code = 201
        fake.json.return_value = {"token": "abc123", "username": "alice"}
        with mock.patch("client.login.requests.post", return_value=fake):
            result = screen._submit("register")
        self.assertEqual(result, ("abc123", "alice"))

    def test_login_uses_login_path_and_register_uses_register_path(self):
        screen = self._screen_obj()
        screen.username, screen.password = "a", "b"
        fake = mock.Mock()
        fake.status_code = 200
        fake.json.return_value = {"token": "t", "username": "a"}
        with mock.patch("client.login.requests.post", return_value=fake) as post:
            screen._submit("login")
            self.assertIn("/api/auth/login", post.call_args.args[0])
            screen._submit("register")
            self.assertIn("/api/auth/register", post.call_args.args[0])

    def test_server_error_message_is_surfaced(self):
        screen = self._screen_obj()
        screen.username, screen.password = "a", "b"
        fake = mock.Mock()
        fake.status_code = 401
        fake.json.return_value = {"error": "用户名或密码错误"}
        with mock.patch("client.login.requests.post", return_value=fake):
            result = screen._submit("login")
        self.assertIsNone(result)
        self.assertEqual(screen.message, "用户名或密码错误")

    def test_network_error_is_soft(self):
        screen = self._screen_obj()
        screen.username, screen.password = "a", "b"
        with mock.patch(
            "client.login.requests.post",
            side_effect=requests.ConnectionError("down"),
        ):
            result = screen._submit("login")
        self.assertIsNone(result)
        self.assertIn("连不上", screen.message)

    def test_password_is_masked_in_state_not_rendering(self):
        """密码**明文保存在内存里**（要发给服务端），但界面显示的是星号。

        这里只断言"字段名没写错"这类低级问题，渲染本身靠人眼看截图。
        """
        screen = self._screen_obj()
        screen.focus = "password"
        for char in "abc":
            screen._handle_key(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode=char)
            )
        self.assertEqual(screen.password, "abc")

    def test_tab_switches_focus(self):
        screen = self._screen_obj()
        self.assertEqual(screen.focus, "username")
        screen._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, unicode=""))
        self.assertEqual(screen.focus, "password")
        screen._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, unicode=""))
        self.assertEqual(screen.focus, "username")

    def test_backspace_edits_focused_field(self):
        screen = self._screen_obj()
        screen.username = "abc"
        screen._handle_key(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, unicode="")
        )
        self.assertEqual(screen.username, "ab")

    def test_username_length_capped(self):
        screen = self._screen_obj()
        for _ in range(30):
            screen._handle_key(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a")
            )
        self.assertEqual(len(screen.username), 20)



class InterpolationRegressionTest(unittest.TestCase):
    """守住一个曾经存在、影响过 E4/E5 结论解读的 bug。

    `client/main.py` 原来用**写死的** `TICK_INTERVAL = 0.05`（20 Hz 的间隔）
    当插值分母。后果：

      · 30 Hz：真实间隔 33 ms，alpha 按 50 ms 算 → 永远追不上，画面"拖影"
      · 10 Hz：真实间隔 100 ms，alpha 50 ms 就到 1 并钳住 → 后 50 ms 冻住再跳
      · 抖动时：相邻间隔忽大忽小，固定分母与真实节奏完全不匹配

    正确做法是按**两帧实际到达时刻**算，并且复用 `protocol/interp.py::clamp_alpha`
    —— **测量（err_px）和渲染必须是同一个公式**，否则实验结论和玩家体验就是两回事。
    """

    def test_client_uses_measured_interval(self):
        import inspect

        import client.main as client_main

        # 模块级不能再有写死的 TICK_INTERVAL（用属性判断，别用字符串扫描 ——
        # 解释性注释里会提到这个名字，扫字符串会误报）
        self.assertFalse(
            hasattr(client_main, "TICK_INTERVAL"),
            "客户端不该再有写死的 TICK_INTERVAL —— 插值分母必须来自实际到达时刻",
        )
        source = inspect.getsource(client_main)
        self.assertIn("clamp_alpha", source,
                      "客户端插值必须复用 protocol/interp.py 的 clamp_alpha")
        self.assertIn("curr_arrived_at", source)
        self.assertIn("prev_arrived_at", source)

    def test_clamp_alpha_matches_render_intent(self):
        """插值系数的语义：**新帧到达时 alpha=0（显示上一帧），过一个间隔才到 1**。

        这正是"渲染滞后一帧"的来源，也是 err_px 的基线不为 0 的原因
        （见 protocol/interp.py 的模块注释与 E4 §3.2 ①）。
        关键是这个规律**与频率无关**：33 ms 和 100 ms 的间隔表现一致。
        """
        from protocol.interp import clamp_alpha

        for span in (0.033, 0.100):          # 30 Hz / 10 Hz
            self.assertAlmostEqual(clamp_alpha(span, 0.0, span), 0.0, places=9)
            self.assertAlmostEqual(clamp_alpha(span + span / 2, 0.0, span), 0.5, places=9)
            self.assertAlmostEqual(clamp_alpha(span * 2, 0.0, span), 1.0, places=9)

if __name__ == "__main__":
    unittest.main()