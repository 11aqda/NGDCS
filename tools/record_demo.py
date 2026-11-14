"""录一段看板演示 GIF（Edge headless + CDP + Pillow），输出到 docs/demo/。

流程：标题卡 → 服务端日志截图 → 登录页（逐字输入）→ 看板（滚动）→
对局记录（滚动）→ DRF 接口 → 结尾卡。

## 前置（和 tools/shot_dashboard.py 一样）

```powershell
# 1) 站点在 8001，Edge 由 PowerShell 启动（Python 起的会崩，见 shot_dashboard.py 注释）
Start-Process "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" `
  -ArgumentList "--headless=new","--disable-gpu","--remote-debugging-port=9228",`
                "--user-data-dir=E:\\PythonProject\\.cache\\record\\edge","about:blank" `
  -WindowStyle Hidden

# 2) 录制（demo 账号由 manage.py seed_demo 创建）
$env:DEMO_PASSWORD = "******"
E:\\PythonProject\\.venv\\Scripts\\python.exe -X utf8 -m tools.record_demo `
    --base-url http://127.0.0.1:8001 --debug-port 9228 --out docs/demo/ngdcs-demo.gif
```

GIF 只是演示用途，**不要提交大文件**：建议传到 GitHub Release，README 里引链接。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
from pathlib import Path

import requests
import websocket
from PIL import Image, ImageDraw, ImageFont

WIDTH = 900
HEIGHT = 560

TITLE_FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD_FONT = "C:/Windows/Fonts/msyhbd.ttc"


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(BOLD_FONT if bold else TITLE_FONT, size)
    except OSError:
        return ImageFont.load_default()


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=60, suppress_origin=True
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

    def eval(self, expression: str):
        return self.send(
            "Runtime.evaluate", expression=expression, returnByValue=True
        )

    def close(self):
        self.ws.close()


def card(lines: list[tuple[str, int, bool]], accent: str = "#4b6fd6") -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#0f1524")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 6], fill=accent)
    y = 150
    for text, size, bold in lines:
        f = font(size, bold)
        bbox = draw.textbbox((0, 0), text, font=f)
        draw.text(((WIDTH - bbox[2]) / 2, y), text, font=f, fill="#e8edf7")
        y += (bbox[3] - bbox[1]) + 34
    return img


def fit(image: Image.Image) -> Image.Image:
    """截屏转成 GIF 统一尺寸（保持比例，上下留黑）。"""
    scale = min(WIDTH / image.width, HEIGHT / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#0b0f18")
    canvas.paste(resized, ((WIDTH - resized.width) // 2, (HEIGHT - resized.height) // 2))
    return canvas


def png_bytes_to_image(data_b64: str) -> Image.Image:
    import base64

    return Image.open(io.BytesIO(base64.b64decode(data_b64))).convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--debug-port", type=int, default=9228)
    parser.add_argument("--username", default="demo")
    parser.add_argument("--password-env", default="DEMO_PASSWORD")
    parser.add_argument("--out", default="docs/demo/ngdcs-demo.gif")
    parser.add_argument("--server-log", default="docs/screenshots/05-server-log.png")
    args = parser.parse_args()

    password = os.environ.get(args.password_env)
    if not password:
        raise SystemExit(f"请先设置环境变量 {args.password_env}")

    try:
        version = requests.get(
            f"http://127.0.0.1:{args.debug_port}/json/version", timeout=5
        ).json()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Edge 调试端口 {args.debug_port} 没响应：{exc}")

    target = requests.put(
        f"http://127.0.0.1:{args.debug_port}/json/new?about:blank"
    ).json()
    cdp = CDP(target["webSocketDebuggerUrl"])
    frames: list[tuple[Image.Image, int]] = []

    def snap(delay_ms: int) -> None:
        data = cdp.send("Page.captureScreenshot", format="png")["data"]
        frames.append((fit(png_bytes_to_image(data)), delay_ms))

    def hold(seconds: float) -> None:
        # 用同一帧延长展示时间（GIF 里就是"停一下"）
        if frames:
            frames.append((frames[-1][0], int(seconds * 1000)))

    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    cdp.send(
        "Emulation.setDeviceMetricsOverride",
        width=1100,
        height=700,
        deviceScaleFactor=1,
        mobile=False,
    )

    frames.append(
        (
            card(
                [
                    ("NGDCS", 64, True),
                    ("多人游戏服务端监控与数据分析平台", 24, False),
                    ("Python · asyncio · Django · DRF · MySQL · Redis", 17, False),
                ]
            ),
            1600,
        )
    )

    log_path = Path(args.server_log)
    if log_path.exists():
        frames.append((fit(Image.open(log_path).convert("RGB")), 1800))

    # 登录页
    cdp.send("Page.navigate", url=f"{args.base_url}/accounts/login/")
    time.sleep(2)
    snap(800)

    def type_into(field: str, text: str, delay_ms: int = 90) -> None:
        for i in range(0, len(text) + 1, 2):
            part = text[:i]
            cdp.eval(
                "(() => { const el = document.querySelector('input[name=%s]');"
                " if (el) { el.value = %r; el.dispatchEvent(new Event('input', {bubbles:true})); } })();"
                % (field, part)
            )
            snap(delay_ms)

    type_into("username", args.username)
    hold(0.3)
    type_into("password", password)
    hold(0.3)

    cdp.eval("document.querySelector('form').requestSubmit();")
    time.sleep(3)
    snap(1200)

    # 看板滚动
    for y in [180, 360, 540, 720, 900, 1080]:
        cdp.eval(f"window.scrollTo(0, {y});")
        time.sleep(0.35)
        snap(400)

    # 对局记录
    cdp.send("Page.navigate", url=f"{args.base_url}/dashboard/matches/")
    time.sleep(2)
    snap(900)
    for y in [200, 400, 600]:
        cdp.eval(f"window.scrollTo(0, {y});")
        time.sleep(0.35)
        snap(400)

    # DRF 接口
    cdp.send("Page.navigate", url=f"{args.base_url}/api/v2/runs/")
    time.sleep(2.5)
    snap(1000)
    cdp.eval("window.scrollTo(0, 300);")
    time.sleep(0.35)
    snap(600)

    frames.append(
        (
            card(
                [
                    ("来源：真实运行", 34, True),
                    ("491 主测试 · 52 Django 测试", 20, False),
                    ("github.com/11aqda/NGDCS", 20, False),
                ],
                accent="#c9903a",
            ),
            1800,
        )
    )

    cdp.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    images = [frame for frame, _ in frames]
    durations = [ms for _, ms in frames]
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"[demo] {out}  {out.stat().st_size / 1024 / 1024:.2f} MB  "
          f"frames={len(images)}  total={(sum(durations) / 1000):.1f}s")


if __name__ == "__main__":
    main()
