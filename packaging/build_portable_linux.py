"""Linux 绿色包构建 - CI 容器内运行(manylinux2014 基线,glibc 2.17+)

兼容目标:银河麒麟 V10 / 统信 UOS 及主流发行版(x86_64 / aarch64 飞腾·鲲鹏)。
形态:单文件可执行(CLI 巡检 + Web 模式全功能;无图形库环境自动转 Web)。

用法(容器内):
    python packaging/build_portable_linux.py --arch x86_64
产物:
    dist/haoyun-patrol-v{版本}-linux-{arch}.tar.gz
    解压后 ./patrol-assistant --web 即可使用(默认双击运行会自动转 Web)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"
DIST_ROOT = ROOT / "dist"
APP_DIR_NAME = "haoyun-patrol"
EXE_NAME = "patrol-assistant"


def read_version() -> str:
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split('"')[1]
    raise RuntimeError("pyproject.toml 中未找到 version")


def run_pyinstaller(arch: str) -> None:
    print(f"[1/3] PyInstaller 打包中(linux-{arch},约 2~5 分钟)……")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile",
        "--name", EXE_NAME,
        "--console",  # Linux 终端使用:CLI 巡检输出/Web 模式日志
        "--distpath", str(DIST_ROOT / "linux"),
        "--workpath", str(BUILD_DIR / "pyi-linux"),
        str(ROOT / "src" / "patrol" / "launcher.py"),
    ]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit("PyInstaller 打包失败,请查看上方报错。")


def assemble() -> Path:
    print("[2/3] 组装绿色包目录……")
    app_dir = DIST_ROOT / "linux" / APP_DIR_NAME
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    exe = DIST_ROOT / "linux" / f"{EXE_NAME}"
    shutil.move(str(exe), app_dir / EXE_NAME)
    # config/ 随包分发(发布仓为演示数据),打开文件夹即可改
    shutil.copytree(ROOT / "config", app_dir / "config")
    (app_dir / "output").mkdir(exist_ok=True)
    (app_dir / "使用说明.txt").write_text(
        "昊云网络巡检助手(Linux 绿色版)\n"
        "\n"
        "快速开始(终端):\n"
        "  ./patrol-assistant            # 无图形库时自动转 Web 模式\n"
        "  ./patrol-assistant --web      # Web 模式(浏览器访问输出的 /ui 地址,带登录认证)\n"
        "  ./patrol-assistant run -c config/tasks/demo.yaml   # CLI 直接巡检\n"
        "\n"
        "配置:config/ 下按需修改(设备档案 devices.yaml、规则 rules/、AI ai.yaml)\n"
        "报告:巡检产物在 output/ 目录\n"
        "\n"
        "适配:银河麒麟 / 统信 UOS / 主流 Linux(x86_64 与 aarch64 飞腾·鲲鹏)\n"
        "作者:昊云  QQ:370428679  MIT 开源协议\n",
        encoding="utf-8")
    return app_dir


def make_tar(app_dir: Path, arch: str, version: str) -> Path:
    print("[3/3] 生成分发压缩包……")
    tar_path = DIST_ROOT / f"haoyun-patrol-v{version}-linux-{arch}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    with tarfile.open(tar_path, "w:gz") as tf:
        for path in sorted(app_dir.rglob("*")):
            tf.add(path, arcname=f"{APP_DIR_NAME}/{path.relative_to(app_dir)}")
    size_mb = tar_path.stat().st_size / 1024 / 1024
    print(f"      {tar_path.name} ({size_mb:.0f} MB)")
    return tar_path


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"],
                    help="目标架构(默认 x86_64,应与构建容器一致)")
    args = ap.parse_args()
    if not (ROOT / "pyproject.toml").exists():
        sys.exit("请在项目根目录下运行本脚本。")
    run_pyinstaller(args.arch)
    app_dir = assemble()
    make_tar(app_dir, args.arch, read_version())
    print("打包完成:解压后 ./patrol-assistant --web 即可使用。")


if __name__ == "__main__":
    main()
