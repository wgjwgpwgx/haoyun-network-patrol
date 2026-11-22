"""绿色包启动器 - 双击即用(桌面小工具,无需浏览器)

职责：
  1. 定位程序根目录（打包后为 exe 所在目录，开发态为项目根目录）并切换工作目录，
     保证 config/ 与 output/ 始终位于程序旁边，方便工程师直接查看编辑。
  2. 首次运行时从内置默认配置播种 config/（不覆盖已有文件）。
  3. 双击默认打开 Tkinter 原生小工具窗口（本地运行,不开浏览器,永不弹黑色控制台）。
  4. `--web` 参数启动 Web 服务并自动开浏览器（远程访问场景,带登录认证）。
  5. 其他命令行参数转交 patrol.cli（如：启动巡检助手.exe run -c config/xx.yaml）。
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import webbrowser
from pathlib import Path

APP_NAME = "昊云网络巡检助手"
APP_VERSION = "0.1.0"
DEFAULT_PORT = 8765


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """程序根目录：打包后为 exe 所在目录，开发态为项目根目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve()
    root = here.parents[2]  # src/patrol/launcher.py -> 项目根
    if (root / "pyproject.toml").exists():
        return root
    return Path.cwd()


def defaults_dir() -> Path:
    """内置默认配置目录（打包后在 _MEIPASS 内，开发态即项目 config/）。"""
    if is_frozen():
        return Path(sys._MEIPASS) / "config-defaults"  # type: ignore[attr-defined]
    return app_root() / "config"


def seed_config(root: Path) -> None:
    """首次运行播种 config/：仅补齐缺失文件，不覆盖工程师已改的配置。"""
    cfg = root / "config"
    src = defaults_dir()
    if not src.exists():
        cfg.mkdir(parents=True, exist_ok=True)
        return
    for s in src.rglob("*"):
        rel = s.relative_to(src)
        d = cfg / rel
        if s.is_dir():
            d.mkdir(parents=True, exist_ok=True)
        elif not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)


def pick_port(preferred: int = DEFAULT_PORT, tries: int = 20) -> int:
    """从 preferred 起找一个可用端口。"""
    for port in range(preferred, preferred + tries):
        # 不设 SO_REUSEADDR：Windows 上它会放行"端口已被占用"的绑定,导致探测失效
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"端口 {preferred}~{preferred + tries - 1} 均被占用，请释放后重试")


def set_console_title(title: str) -> None:
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)  # type: ignore[attr-defined]
    except Exception:
        pass


def _ensure_cli_output() -> None:
    """窗口子系统构建（双击无黑框）下保证命令行输出可见。

    绿色包 exe 不带控制台；只有 stdout 已被父进程重定向（冒烟脚本、`> log.txt`）
    或显式带参启动（--web / CLI）时才接输出通道。双击开桌面小工具时什么都不做，
    永远不会弹出黑色控制台。
    """
    if not is_frozen():
        return
    if sys.platform != "win32":
        return  # 控制台接管为 Windows 冻结包专用,其他平台无需处理

    def _fileno(stream) -> int | None:
        try:
            return stream.fileno()
        except Exception:
            return None

    if _fileno(sys.stdout) is not None:
        return  # 已有正常输出流(PyInstaller 已接管管道/文件)

    import ctypes
    import io

    kernel32 = ctypes.windll.kernel32
    if kernel32.GetFileType(kernel32.GetStdHandle(-11)) != 0:  # FILE_TYPE_UNKNOWN=0
        # 句柄已被重定向但流未接管(冒烟/日志文件):接回 fd 1/2(UTF-8)
        sys.stdout = io.TextIOWrapper(open(1, "wb", closefd=False),
                                      encoding="utf-8", errors="replace",
                                      line_buffering=True)
        sys.stderr = io.TextIOWrapper(open(2, "wb", closefd=False),
                                      encoding="utf-8", errors="replace",
                                      line_buffering=True)
        return

    if not (sys.argv[1:] or os.environ.get("PATROL_DESKTOP_SMOKE")):
        return  # 双击开桌面小工具:无输出需求,不分配控制台

    if not kernel32.AttachConsole(-1):  # 附着启动本程序的 cmd 窗口
        kernel32.AllocConsole()  # 快捷方式带参启动:自开控制台
    sys.stdout = open("CONOUT$", "w", encoding="mbcs", errors="replace")
    sys.stderr = open("CONOUT$", "w", encoding="mbcs", errors="replace")
    sys.stdin = open("CONIN$", "r", encoding="mbcs", errors="replace")


def _open_browser_later(url: str, delay: float = 1.5) -> None:
    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Timer(delay, _open).start()


def main() -> int:
    _ensure_cli_output()  # 窗口子系统:按需接管管道/控制台输出,双击无黑框

    # 先切到程序根目录：config/ 与 output/ 始终在程序旁边
    root = app_root()
    os.chdir(root)
    seed_config(root)
    (root / "output").mkdir(parents=True, exist_ok=True)

    args = sys.argv[1:]

    # --web:启动 Web 服务(远程访问场景,带登录认证,自动开浏览器)
    if args and args[0] == "--web":
        return run_web(root)

    # 其他参数转交命令行工具（如：启动巡检助手.exe run -c config\xx.yaml）
    if args:
        from patrol.cli import main as cli_main

        cli_main()
        return 0

    # 双击默认：打开桌面小工具窗口(原生界面,无需浏览器)
    from patrol.desktop.app import run as run_desktop

    return run_desktop()


def run_web(root: Path) -> int:
    """Web 模式:本地端口起服务并自动开浏览器(--web 显式启用)。"""
    host = os.environ.get("PATROL_HOST", "127.0.0.1")
    preferred = int(os.environ.get("PATROL_PORT", DEFAULT_PORT))
    port = pick_port(preferred)
    url = f"http://{host}:{port}/ui"

    set_console_title(f"{APP_NAME} v{APP_VERSION} - Web 模式运行中")

    print("=" * 52)
    print(f"  {APP_NAME} v{APP_VERSION}(Web 模式)")
    print("=" * 52)
    print(f"  服务地址 : {url}")
    if port != preferred:
        print(f"  (端口 {preferred} 被占用，已自动改用 {port})")
    print("  浏览器即将自动打开，请稍候……")
    print("  配置文件 : config\\devices.yaml （设备清单）")
    print(f"  报告目录 : {root / 'output'}")
    print()
    print("  关闭本窗口即可停止服务。")
    print("=" * 52)

    if os.environ.get("PATROL_NO_BROWSER") != "1":
        _open_browser_later(url)

    # chdir 之后再导入：store/tasks 均按相对路径读写 config/ 与 output/
    import uvicorn

    from patrol.api.app import app

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n服务已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
