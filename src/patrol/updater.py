"""绿色包在线自动更新

流程:
    检查更新(patron.update) → 下载更新包(zip) → 可选 sha256 校验
    → 解压暂存(update/staging) → 生成 update.cmd → 退出主程序
    → 脚本替换程序本体后自动重启。

安全边界:只替换程序本体(*.exe)与随包说明文件(*.txt / LICENSE.txt),
永远不覆盖用户数据 config/ 与 output/;旧 exe 备份到 update/backup/ 可回滚。
更新脚本内容为纯 ASCII(cmd 的代码页处理中文文件名不可靠),
exe 等中文文件名通过通配符匹配,避免编码问题。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class UpdateError(Exception):
    """更新失败(下载/校验/解压/环境不支持)。"""


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def update_dir(root: Path | None = None) -> Path:
    """更新工作区:相对 CWD 的 update/(与 config/、output/ 同级,绿色包内即包根)。"""
    return (root or Path(".")) / "update"


def download_package(
    url: str,
    version: str = "",
    root: Path | None = None,
    timeout: float = 300.0,
    expected_sha256: str = "",
) -> Path:
    """下载(或本地拷贝)更新包到 update/downloads/,可选 sha256 校验。"""
    if not (url or "").strip():
        raise UpdateError("更新包地址为空")
    dl_dir = update_dir(root) / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    dest = dl_dir / f"update-{version or 'pkg'}.zip"

    if re.match(r"^https?://", url, re.IGNORECASE):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes(1 << 16):
                            f.write(chunk)
        except httpx.HTTPError as e:
            raise UpdateError(f"下载更新包失败: {e}") from e
    else:
        src = Path(url)
        if not src.exists():
            raise UpdateError(f"更新包文件不存在: {url}")
        shutil.copyfile(src, dest)

    if expected_sha256:
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest.lower() != expected_sha256.strip().lower():
            dest.unlink(missing_ok=True)
            raise UpdateError("更新包校验失败(sha256 不匹配),已丢弃")
    logger.info("更新包已下载: %s (%d 字节)", dest, dest.stat().st_size)
    return dest


def stage_update(zip_path: Path, version: str = "", root: Path | None = None) -> dict:
    """解压更新包到 update/staging/ 并记录待更新信息(update/pending.json)。

    zip 布局兼容"整包文件夹"与"平铺"两种;只取出 exe 与说明文本文件到 staging 根,
    其余内容(尤其 config/)一律不进入暂存区。
    """
    staging = update_dir(root) / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    raw = staging / "raw"
    raw.mkdir(parents=True)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(raw)
    except zipfile.BadZipFile as e:
        raise UpdateError(f"更新包不是有效的 zip: {e}") from e

    exes = sorted(raw.rglob("*.exe"), key=lambda p: len(p.parts))
    if not exes:
        raise UpdateError("更新包中未找到程序文件(*.exe)")
    main_exe = next((p for p in exes if "巡检" in p.name or "patrol" in p.name.lower()), exes[0])
    pkg_root = main_exe.parent

    staging.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main_exe, staging / main_exe.name)
    for extra in list(pkg_root.glob("*.txt")) + [pkg_root / "LICENSE.txt"]:
        if extra.exists() and extra.is_file():
            shutil.copy2(extra, staging / extra.name)

    pending = {
        "version": version,
        "exe_name": main_exe.name,
        "downloaded_at": datetime.now().isoformat(),
    }
    from patrol.utils.fs import atomic_write_text

    atomic_write_text(
        update_dir(root) / "pending.json",
        json.dumps(pending, ensure_ascii=False, indent=2),
    )
    shutil.rmtree(raw)
    logger.info("更新包已暂存: exe=%s version=%s", main_exe.name, version)
    return pending


def load_pending(root: Path | None = None) -> dict | None:
    """读取待安装更新信息(无则 None)。"""
    path = update_dir(root) / "pending.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clear_pending(root: Path | None = None) -> None:
    (update_dir(root) / "pending.json").unlink(missing_ok=True)


def write_update_script(pid: int, root: Path | None = None) -> Path:
    """生成 update.cmd(纯 ASCII;宽限等待 → 备份 → 拷贝重试替换 → 重启)。

    pid 仅写入注释行供排查,不作为等待依据:
    Windows PID 会被回收,轮询 PID 可能误判"进程仍在"而空转。
    就绪判定以"目标文件拷贝成功"为准(文件锁释放),fc /b 逐字节校验拷贝结果
    (copy 的 errorlevel 在部分路径不可靠,set /a 还会污染 errorlevel)。
    重启前清空 PyInstaller 引导变量(_MEIPASS/_PYI_*/PYINSTALLER_*):
    onefile 父进程会把它们传进子进程环境,新实例若继承之,引导器会误判
    自身为子启动阶段而复用旧解压目录(_MEI),旧进程退出后该目录被删,新实例秒退。
    """
    script = (root or Path(".")) / "update.cmd"
    # 说明:staging 根目录已保证只有 exe/txt,故用通配符拷贝,避免批处理里的中文文件名;
    # 拷贝带重试(onefile 启动器父进程退场/杀软扫描有短暂文件锁窗口);
    # 失败保留 pending 供重试。write_bytes 保证精确 CRLF(write_text 会二次转换行尾)。
    script.write_bytes(
        "\r\n".join([
            "@echo off",
            "setlocal enableextensions",
            'set "APPDIR=%~dp0"',
            f"rem spawned from pid {pid}",
            "ping -n 8 127.0.0.1 >nul",
            "set /a TRY=0",
            ":retry",
            "set /a TRY+=1",
            'if not exist "%APPDIR%update\\backup" mkdir "%APPDIR%update\\backup"',
            'if not exist "%APPDIR%update\\backup\\*.exe" copy /y "%APPDIR%*.exe" "%APPDIR%update\\backup\\" >nul 2>&1',
            'copy /y "%APPDIR%update\\staging\\*.exe" "%APPDIR%" >nul 2>&1',
            'for %%F in ("%APPDIR%update\\staging\\*.exe") do fc /b "%%F" "%APPDIR%%%~nxF" >nul 2>&1',
            "if not errorlevel 1 goto copied",
            "if %TRY% GEQ 30 goto failed",
            "ping -n 4 127.0.0.1 >nul",
            "goto retry",
            ":copied",
            'copy /y "%APPDIR%update\\staging\\*.txt" "%APPDIR%" >nul 2>&1',
            'del /q "%APPDIR%update\\pending.json" 2>nul',
            'rd /s /q "%APPDIR%update\\staging" 2>nul',
            'del /q "%APPDIR%update\\downloads\\*.zip" 2>nul',
            'set "_MEIPASS="',
            'set "_MEIPASS2="',
            'set "_PYI_APPLICATION_HOME_DIR="',
            'set "_PYI_ARCHIVE_FILE="',
            'set "_PYI_PARENT_PROCESS_LEVEL="',
            'set "_PYI_SPLASH_IPC="',
            'set "PYINSTALLER_RESET_ENVIRONMENT="',
            'set "PYINSTALLER_STRICT_UNPACK_MODE="',
            'for %%F in ("%APPDIR%*.exe") do start "" "%%F"',
            "goto cleanup",
            ":failed",
            "echo update failed, keep pending for retry",
            'set "_MEIPASS="',
            'set "_MEIPASS2="',
            'set "_PYI_APPLICATION_HOME_DIR="',
            'set "_PYI_ARCHIVE_FILE="',
            'set "_PYI_PARENT_PROCESS_LEVEL="',
            'set "_PYI_SPLASH_IPC="',
            'set "PYINSTALLER_RESET_ENVIRONMENT="',
            'set "PYINSTALLER_STRICT_UNPACK_MODE="',
            'for %%F in ("%APPDIR%*.exe") do start "" "%%F"',
            "goto cleanup",
            ":cleanup",
            '(goto) 2>nul & del "%~f0"',
            "",
        ]).encode("ascii"),
    )
    return script


def install_now(root: Path | None = None) -> Path:
    """启动更新脚本并返回其路径(调用方随后应退出进程让脚本接手)。

    仅绿色包(frozen)支持替换本体;开发模式抛 UpdateError。
    """
    root = root or Path(".")
    if not is_frozen():
        raise UpdateError("当前为源码运行模式,不支持自动替换程序本体;绿色包内才支持一键更新")
    if load_pending(root) is None:
        raise UpdateError("没有待安装的更新包,请先下载")

    script = write_update_script(os.getpid(), root)
    cmd = ["cmd", "/c", str(script)]
    base_flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    kwargs = {"close_fds": True, "cwd": str(root)}
    # 优先脱离父进程 Job(某些启动器/任务容器退出时会连坐杀掉子进程),
    # 环境不允许 breakaway 时退回普通分离启动。
    try:
        subprocess.Popen(
            cmd,
            creationflags=base_flags | _CREATE_BREAKAWAY_FROM_JOB,
            **kwargs,
        )
    except (OSError, ValueError):
        subprocess.Popen(cmd, creationflags=base_flags, **kwargs)
    logger.info("更新脚本已启动: %s", script)
    return script
