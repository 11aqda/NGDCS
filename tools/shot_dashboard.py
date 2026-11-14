"""用 Edge headless + CDP 给看板页面截图（README / 答辩 PPT 用）。

## 为什么单独写一个工具

`docs/screenshots/` 里已有游戏端截图（PIL 存帧），但**网页截图**需要真浏览器：
CSS、ECharts、字体都得按浏览器排版来。这台机器没有 Selenium/Playwright，
所以直接用 Edge 自带的 DevTools 协议（CDP），只依赖 `websocket-client`。

## 两步走（**Edge 必须由 PowerShell 启动**）

本机实测：由 Python `subprocess` 启动的 Edge 会在几秒内崩溃
（`0xC0000409`，沙箱环境限制），而 PowerShell `Start-Process` 启动的稳定。
所以工具**只管截图**，浏览器由外面的命令起：

```powershell
# 1) 起站点（账号要有 is_staff）
E:\\PythonProject\\.venv\\Scripts\\python.exe manage.py runserver 127.0.0.1:8001 --noreload

# 2) 起 Edge（headless + 调试端口）
Start-Process "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" `
  -ArgumentList "--headless=new","--disable-gpu","--no-first-run",`
                "--remote-debugging-port=9223",`
                "--user-data-dir=E:\\PythonProject\\.cache\\shot\\edge",`
                "about:blank" -WindowStyle Hidden

# 3) 截图（密码只走环境变量，不落盘、不进命令历史）
$env:NGDCS_SHOT_PASSWORD = "******"
E:\\PythonProject\\.venv\\Scripts\\python.exe -X utf8 -m tools.shot_dashboard `
    --username <staff账号> --base-url http://127.0.0.1:8001 --out docs/screenshots
```

产出：`08-dashboard.png`、`09-dashboard-matches.png`、`10-api-runs.png`。

依赖：`websocket-client`（仅截图用，不在 requirements.txt 里；`pip install websocket-client`）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.request
from pathlib import Path

import requests
import websocket


class CDP:
    """极简 CDP 客户端：只用到 Navigate / Cookie / Screenshot。"""

    def __init__(self, ws_url: str):
        # suppress_origin：Edge 会拒绝带 Origin 的 WebSocket 握手（403），
        # 除非启动时加 --remote-allow-origins=*；这里不发 Origin 更省事。
        self.ws = websocket.create_connection(
            ws_url, timeout=30, suppress_origin=True
        )
        self._id = 0

    def send(self, method: str, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self._id:
                if "error" in message:
                    raise RuntimeError(f"{method} 失败：{message['error']}")
                return message.get("result", {})

    def close(self):
        self.ws.close()


def http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_edge(port: int) -> str:
    try:
        return http_json(f"http://127.0.0.1:{port}/json/version")[
            "webSocketDebuggerUrl"
        ]
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"调试端口 {port} 没有响应（{exc}）。\n"
            "Edge 必须由 PowerShell 的 Start-Process 启动（用 Python subprocess 起会崩），"
            "启动命令见本文件开头的说明。"
        ) from exc


def login(base_url: str, username: str, password: str) -> str:
    """走真实的登录表单，拿 sessionid（不绕过认证）。"""
    session = requests.Session()
    login_url = f"{base_url}/accounts/login/"
    page = session.get(login_url, timeout=10)
    page.raise_for_status()
    token = session.cookies.get("csrftoken")
    if not token:
        raise SystemExit("登录页没下发 csrftoken，确认 base-url 指向本项目的 Django")
    resp = session.post(
        login_url,
        data={
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": token,
            "next": "/dashboard/",
        },
        headers={"Referer": login_url},
        timeout=10,
        allow_redirects=True,
    )
    if "sessionid" not in session.cookies:
        raise SystemExit(f"登录失败（HTTP {resp.status_code}），检查账号/密码/CSRF")
    dashboard = session.get(f"{base_url}/dashboard/", timeout=10)
    if dashboard.status_code != 200:
        raise SystemExit(f"/dashboard/ 返回 {dashboard.status_code}，账号可能不是 staff")
    return session.cookies["sessionid"]


def new_target(browser_ws: str) -> str:
    cdp = CDP(browser_ws)
    try:
        return cdp.send("Target.createTarget", url="about:blank")["targetId"]
    finally:
        cdp.close()


def page_ws_url(port: int, target_id: str) -> str:
    for item in http_json(f"http://127.0.0.1:{port}/json/list"):
        if item.get("id") == target_id:
            return item["webSocketDebuggerUrl"]
    raise SystemExit("找不到新建的页面 target")


def capture(
    port: int,
    target_id: str,
    url: str,
    out: Path,
    session_id: str,
    width: int,
    height: int,
    origin: str,
) -> None:
    cdp = CDP(page_ws_url(port, target_id))
    try:
        cdp.send("Page.enable")
        cdp.send("Network.enable")
        cdp.send(
            "Network.setCookie",
            name="sessionid",
            value=session_id,
            url=origin + "/",
            path="/",
        )
        cdp.send(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=height,
            deviceScaleFactor=1,
            mobile=False,
        )
        cdp.send("Page.navigate", url=url)
        time.sleep(5)  # ECharts 走 CDN，留足加载时间
        size = cdp.send("Page.getLayoutMetrics")["cssContentSize"]
        shot = cdp.send(
            "Page.captureScreenshot",
            format="png",
            captureBeyondViewport=True,
            clip={
                "x": 0,
                "y": 0,
                "width": size["width"],
                "height": size["height"],
                "scale": 1,
            },
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(shot["data"]))
        print(f"[shot] {out}  ({size['width']}x{size['height']})")
    finally:
        cdp.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="看板页面截图（Edge headless + CDP）")
    parser.add_argument("--username", required=True, help="staff 账号（密码走 NGDCS_SHOT_PASSWORD）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", default="docs/screenshots")
    parser.add_argument("--debug-port", type=int, default=9223)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1200)
    args = parser.parse_args()

    password = os.environ.get("NGDCS_SHOT_PASSWORD")
    if not password:
        raise SystemExit("请先设置环境变量 NGDCS_SHOT_PASSWORD（不要把密码写进命令）")

    browser_ws = check_edge(args.debug_port)
    session_id = login(args.base_url, args.username, password)
    print("[shot] 登录成功，sessionid 已拿到（不打印内容）")

    out_dir = Path(args.out)
    pages = [
        ("08-dashboard.png", f"{args.base_url}/dashboard/"),
        ("09-dashboard-matches.png", f"{args.base_url}/dashboard/matches/"),
        ("10-api-runs.png", f"{args.base_url}/api/v2/runs/"),
    ]
    for filename, url in pages:
        target_id = new_target(browser_ws)
        capture(
            args.debug_port,
            target_id,
            url,
            out_dir / filename,
            session_id,
            args.width,
            args.height,
            args.base_url,
        )


if __name__ == "__main__":
    main()
