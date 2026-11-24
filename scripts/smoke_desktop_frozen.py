"""冻结冒烟:绿色包桌面小工具窗口构建闭环

流程:以 PATROL_DESKTOP_SMOKE=1 启动 dist 下的 exe
    → 构建主窗口 + 遍历 6 个面板 + 服务层可达 + PDF 组件已打包
    → 输出 DESKTOP_SMOKE_OK 并自行退出。

    python scripts/smoke_desktop_frozen.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "dist" / "昊云网络巡检助手"
EXE = ROOT / "启动巡检助手.exe"

_passed = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global _passed
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f"  ← {detail}" if detail and not ok else ""))
    if ok:
        _passed += 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not EXE.exists():
        print(f"未找到 {EXE},请先执行 python packaging/build_portable.py")
        return 1

    env = dict(os.environ)
    env["PATROL_DESKTOP_SMOKE"] = "1"

    proc = subprocess.run([str(EXE)], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")

    ok_marker = "DESKTOP_SMOKE_OK" in out
    check(ok_marker, "桌面窗口构建并输出 DESKTOP_SMOKE_OK", out[-400:])
    check(proc.returncode == 0, "进程正常退出", f"returncode={proc.returncode}")
    check("SMOKE 2/5" in out, "6 个功能面板全部遍历刷新", out[-400:])
    check("SMOKE 5/5" in out, "报告/AI/更新服务层可达、PDF 组件已打包", out[-400:])
    check("Traceback" not in out, "无未捕获异常", out[-400:])

    print(f"\n桌面小工具冻结冒烟 {_passed}/5 通过")
    return 0 if _passed == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
