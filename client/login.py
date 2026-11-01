"""登录 / 注册界面（步骤 10c）。

## 它存在的意义

前面所有东西都跑通了，但**玩家没有入口**：token 只能靠 curl 拿。
这个界面把「长短连接分层」（D-005）变成用户能看见的一步：

    输入账号密码 → HTTP 登录拿 token → 之后 TCP 连接用它认证

## 三个设计取舍

### ① 登录放在**游戏循环之外**，同步调用 HTTP 就行

`04 §3.1` 明确写了：所有 HTTP 调用都发生在游戏循环之外（登录界面 / 排行榜界面 / 结算界面）。
所以这里**不需要异步**，一次 `requests.post` 阻塞几十毫秒完全可以接受 ——
真正要避免的是"在 20 Hz 的渲染循环里发 HTTP"，那会把 fps 拖垮。

### ② 一定留「游客」入口

服务端的认证是**可选**的（不发 `C_AUTH` 就是匿名玩家）。
没有游客模式的话，起个服务端想自己试玩还得先注册 —— 开发时极其碍事。
游客进游戏不参与排行榜（服务端本来就不会给匿名玩家算分）。

### ③ 密码框显示星号，但不做"记住密码"

这是毕设演示环境，明文存密码反而增加风险。每次启动重新输入。
"""

from __future__ import annotations

import pygame
import requests

BG = (16, 20, 32)
TEXT = (220, 226, 240)
DIM = (120, 132, 156)
ACCENT = (90, 200, 255)
ERROR = (255, 120, 120)
OK = (120, 230, 160)
FIELD_BG = (30, 38, 54)
FIELD_ACTIVE = (42, 54, 76)
BTN = (44, 58, 82)
BTN_HOVER = (62, 84, 118)


class LoginScreen:
    """一个自包含的小界面：返回值就是登录结果。"""

    def __init__(self, screen: pygame.Surface, font, big_font, api_base: str) -> None:
        self.screen = screen
        self.font = font
        self.big_font = big_font
        self.api_base = api_base.rstrip("/")
        self.width, self.height = screen.get_size()

        self.username = ""
        self.password = ""
        self.focus = "username"
        self.message = ""
        self.message_color = DIM
        self.busy = False

    # ------------------------------------------------------------ 布局

    def _fields(self) -> dict[str, pygame.Rect]:
        cx = self.width // 2
        w = min(int(self.width * 0.62), 420)
        h = max(38, int(self.height * 0.055))
        top = int(self.height * 0.38)
        gap = int(h * 0.55)
        return {
            "username": pygame.Rect(cx - w // 2, top, w, h),
            "password": pygame.Rect(cx - w // 2, top + h + gap, w, h),
        }

    def _buttons(self) -> dict[str, pygame.Rect]:
        cx = self.width // 2
        w = min(int(self.width * 0.62), 420)
        h = max(38, int(self.height * 0.055))
        top = int(self.height * 0.38) + 2 * h + int(h * 1.4)
        gap = int(w * 0.03)
        half = (w - gap) // 2
        return {
            "login": pygame.Rect(cx - w // 2, top, half, h),
            "register": pygame.Rect(cx - w // 2 + half + gap, top, half, h),
            "guest": pygame.Rect(cx - w // 2, top + h + int(h * 0.5), w, h),
        }

    # ------------------------------------------------------------ 交互

    def _submit(self, action: str) -> tuple[str, str] | None:
        """发 HTTP 请求。成功返回 (token, username)，失败把错误写进 message。"""
        if not self.username or not self.password:
            self.message = "用户名和密码都要填"
            self.message_color = ERROR
            return None

        path = "/api/auth/login" if action == "login" else "/api/auth/register"
        self.busy = True
        self.message = "连接服务器中…"
        self.message_color = DIM
        self._draw()  # 立刻把「连接中」画出来，否则会像卡死
        pygame.display.flip()

        try:
            response = requests.post(
                f"{self.api_base}{path}",
                json={"username": self.username, "password": self.password},
                timeout=5,
            )
            data = response.json()
        except requests.RequestException as exc:
            self.busy = False
            self.message = f"连不上认证服务器：{type(exc).__name__}"
            self.message_color = ERROR
            return None
        except ValueError:
            self.busy = False
            self.message = "服务器返回的不是 JSON"
            self.message_color = ERROR
            return None

        self.busy = False
        if response.status_code >= 400:
            self.message = data.get("error", f"HTTP {response.status_code}")
            self.message_color = ERROR
            return None

        self.message = f"欢迎，{data.get('username', '')}"
        self.message_color = OK
        return data["token"], data["username"]

    def _handle_key(self, event: pygame.event.Event) -> tuple[str, str] | None:
        if event.key == pygame.K_ESCAPE:
            raise SystemExit(0)
        if event.key == pygame.K_TAB:
            self.focus = "password" if self.focus == "username" else "username"
            return None
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._submit("login")
        if event.key == pygame.K_BACKSPACE:
            if self.focus == "username":
                self.username = self.username[:-1]
            else:
                self.password = self.password[:-1]
            return None

        char = event.unicode
        if char and char.isprintable() and len(char) == 1:
            if self.focus == "username" and len(self.username) < 20:
                self.username += char
            elif self.focus == "password" and len(self.password) < 32:
                self.password += char
        return None

    # ------------------------------------------------------------ 绘制

    def _draw(self) -> None:
        self.screen.fill(BG)
        cx = self.width // 2

        title = self.big_font.render("NGDCS  ·  实时对战", True, TEXT)
        self.screen.blit(title, title.get_rect(center=(cx, int(self.height * 0.20))))
        hint = self.font.render("登录后可参与排行榜 · 游客模式不记分", True, DIM)
        self.screen.blit(hint, hint.get_rect(center=(cx, int(self.height * 0.26))))

        fields = self._fields()
        for name, rect in fields.items():
            active = self.focus == name
            pygame.draw.rect(self.screen, FIELD_ACTIVE if active else FIELD_BG,
                             rect, border_radius=6)
            pygame.draw.rect(self.screen, ACCENT if active else (52, 64, 88),
                             rect, 2, border_radius=6)

            label = "用户名" if name == "username" else "密  码"
            label_surface = self.font.render(label, True, DIM)
            self.screen.blit(label_surface, (rect.x, rect.y - label_surface.get_height() - 4))

            text = self.username if name == "username" else "•" * len(self.password)
            caret = "|" if active and (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            value = self.font.render(text + caret, True, TEXT)
            self.screen.blit(value, (rect.x + 12, rect.centery - value.get_height() // 2))

        mouse = pygame.mouse.get_pos()
        labels = {"login": "登  录", "register": "注  册", "guest": "游客进入"}
        for name, rect in self._buttons().items():
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(self.screen, BTN_HOVER if hover else BTN, rect, border_radius=6)
            pygame.draw.rect(self.screen, (70, 88, 118), rect, 1, border_radius=6)
            text = self.font.render(labels[name], True, TEXT)
            self.screen.blit(text, text.get_rect(center=rect.center))

        if self.message:
            surface = self.font.render(self.message, True, self.message_color)
            self.screen.blit(
                surface,
                surface.get_rect(center=(cx, int(self.height * 0.80))),
            )

    # ------------------------------------------------------------ 主循环

    def run(self) -> tuple[str, str] | None:
        """阻塞直到登录成功或退出。返回 (token, username)；`("", "游客")` 表示游客。"""
        clock = pygame.time.Clock()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise SystemExit(0)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in self._fields().items():
                        if rect.collidepoint(event.pos):
                            self.focus = name
                    for name, rect in self._buttons().items():
                        if not rect.collidepoint(event.pos):
                            continue
                        if name == "guest":
                            return "", "游客"
                        result = self._submit(name)
                        if result is not None:
                            return result
                if event.type == pygame.KEYDOWN and not self.busy:
                    result = self._handle_key(event)
                    if result is not None:
                        return result

            self._draw()
            pygame.display.flip()
            clock.tick(60)