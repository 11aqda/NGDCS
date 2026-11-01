"""字体加载：**必须能显示中文**。

## 为什么单独一个模块

2026-11-01 实测：登录界面用 `SysFont("consolas")` 渲染中文，满屏都是**方块（□）** ——
consolas 没有中文字形。HUD 以前只显示 ASCII 所以没暴露，加上 `[用户名]` 之后就露馅了。

Windows 的中文字体都是**文件**形式（`.ttc` / `.ttf`），用 `pygame.font.Font(path, size)`
直接加载最稳；`SysFont("microsoftyahei")` 依赖 SDL 的字体名映射，跨版本不一定对得上。

## 回退策略

按优先级找一个存在的字体文件；**一个都找不到就退回系统默认**
（可能没有中文，但至少不会崩）——宁可显示方块，也不能因为字体缺失让程序起不来。
"""

from __future__ import annotations

from pathlib import Path

import pygame

# 按优先级排列。前两个是微软雅黑（普通 / 粗体），后面是黑体、等线、宋体兜底。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    r"C:\Windows\Fonts\Deng.ttf",     # 等线
    r"C:\Windows\Fonts\simsun.ttc",   # 宋体
)

_cached_path: str | None = None
_resolved = False


def cjk_font_path() -> str | None:
    """返回第一个存在的中文字体文件；找不到返回 None。结果缓存一次。"""
    global _cached_path, _resolved
    if _resolved:
        return _cached_path
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            _cached_path = candidate
            break
    _resolved = True
    return _cached_path


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    """加载能显示中文的字体；找不到中文字体则退回系统默认。"""
    path = cjk_font_path()
    if path is not None:
        try:
            font = pygame.font.Font(path, size)
            font.set_bold(bold)
            return font
        except OSError:
            pass  # 字体文件坏了 / 格式不支持 → 走回退
    return pygame.font.SysFont("consolas", size, bold=bold)


def load_mono_font(size: int, bold: bool = False) -> pygame.font.Font:
    """等宽字体，**只用于纯 ASCII**（HUD 里的数字、十六进制）。

    ⚠️ 不要拿它显示中文 —— 和上面同一个坑。
    """
    return pygame.font.SysFont("consolas", size, bold=bold)