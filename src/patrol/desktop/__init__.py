"""桌面小工具 - Tkinter 原生窗口,双击即用,无需浏览器"""
from __future__ import annotations

__all__ = ["run"]


def run() -> int:
    """启动桌面小工具(延迟导入,命令行模式不加载 tkinter)。"""
    from patrol.desktop.app import run as _run

    return _run()
