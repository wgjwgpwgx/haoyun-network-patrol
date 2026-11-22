"""打包绿色版 - 昊云网络巡检助手

用法(项目根目录执行):
    python packaging/build_portable.py

产物:
    dist/昊云网络巡检助手/               <- 整个文件夹拷给工程师即可
        启动巡检助手.exe                <- 双击启动,浏览器自动打开
        config/                         <- 设备/规则/AI 配置(可直接编辑)
        output/                         <- 巡检报告输出目录
        使用说明.txt
        LICENSE.txt                     <- MIT 许可证(允许二次开发)
    dist/昊云网络巡检助手-v0.1.0-绿色版.zip
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "昊云网络巡检助手"
EXE_NAME = "启动巡检助手"


def _read_version() -> str:
    """从 pyproject.toml 读取版本(单一事实源,避免升版漏改打包常量)。"""
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split('"')[1]
    raise RuntimeError("pyproject.toml 中未找到 version")


ROOT = Path(__file__).resolve().parents[1]
VERSION = _read_version()
BUILD_DIR = ROOT / "build"
SPEC = ROOT / "packaging" / "patrol_portable.spec"
DIST_ROOT = ROOT / "dist"
DIST_DIR = DIST_ROOT / APP_NAME


def make_icon() -> None:
    """用 logo.png 生成多尺寸 .ico(资源管理器/任务栏图标)。"""
    from PIL import Image

    logo = ROOT / "src" / "patrol" / "api" / "static" / "logo.png"
    img = Image.open(logo).convert("RGBA")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    img.save(
        BUILD_DIR / "app.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("[1/5] 图标已生成: build/app.ico")


def make_version_info() -> None:
    """生成 exe 文件属性(右键->属性->详细信息)。"""
    content = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 1, 0, 0),
    prodvers=(0, 1, 0, 0),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        "080404B0",
        [
          StringStruct("CompanyName", "Haoyun Networks"),
          StringStruct("FileDescription", "昊云网络巡检助手"),
          StringStruct("FileVersion", VERSION),
          StringStruct("InternalName", "patrol"),
          StringStruct("LegalCopyright", "Copyright 2026 Haoyun Networks"),
          StringStruct("OriginalFilename", "启动巡检助手.exe"),
          StringStruct("ProductName", "昊云网络巡检助手"),
          StringStruct("ProductVersion", VERSION),
        ],
      )
    ]),
    VarFileInfo([VarStruct("Translation", [2052, 1200])]),
  ]
)
"""
    (BUILD_DIR / "version_info.txt").write_text(content, encoding="utf-8")
    print("[2/5] 版本信息已生成: build/version_info.txt")


def run_pyinstaller() -> None:
    print("[3/5] PyInstaller 打包中(约 2~5 分钟)……")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / "pyi"),
        str(SPEC),
    ]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit("PyInstaller 打包失败,请查看上方报错。")


def assemble() -> None:
    print("[4/5] 组装绿色包目录……")
    # config/ 直接随包分发,工程师打开文件夹就能改
    # 先清掉上次构建残留,保证包内 config 与源码完全一致
    if (DIST_DIR / "config").exists():
        shutil.rmtree(DIST_DIR / "config")
    shutil.copytree(ROOT / "config", DIST_DIR / "config")
    (DIST_DIR / "output").mkdir(parents=True, exist_ok=True)

    # 使用说明转成带 BOM 的 UTF-8,老版记事本也能正确显示中文
    readme = ROOT / "packaging" / "使用说明.txt"
    text = readme.read_text(encoding="utf-8")
    (DIST_DIR / "使用说明.txt").write_text(text, encoding="utf-8-sig")

    # MIT 许可证随包分发(允许二次开发)
    shutil.copy2(ROOT / "LICENSE", DIST_DIR / "LICENSE.txt")

    exe = DIST_DIR / f"{EXE_NAME}.exe"
    if not exe.exists():
        sys.exit(f"未找到 {exe},打包异常。")
    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"      {exe.name} ({size_mb:.0f} MB)")


def make_zip() -> Path:
    print("[5/5] 生成分发压缩包……")
    # GitHub Release 附件名会剥除中文字符(CI 环境用 ASCII 名保证下载名可读;
    # 本地交付仍用中文名,双击体验不变)
    import os
    zip_name = (f"haoyun-patrol-v{VERSION}-win64-portable.zip"
                if os.environ.get("CI") else f"{APP_NAME}-v{VERSION}-绿色版.zip")
    zip_path = DIST_ROOT / zip_name
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(DIST_DIR.rglob("*")):
            if path.is_file():
                arcname = f"{APP_NAME}/{path.relative_to(DIST_DIR).as_posix()}"
                zf.write(path, arcname)
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"      {zip_path.name} ({size_mb:.0f} MB)")
    return zip_path


def main() -> None:
    # CI 英文 Windows 控制台为 cp1252,中文提示 print 会 UnicodeEncodeError,统一切 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not (ROOT / "pyproject.toml").exists():
        sys.exit("请在巡检助手项目根目录下运行本脚本。")
    make_icon()
    make_version_info()
    run_pyinstaller()
    assemble()
    make_zip()
    print()
    print("打包完成:")
    print(f"  文件夹: {DIST_DIR}")
    print(f"  压缩包: {DIST_ROOT / (APP_NAME + '-v' + VERSION + '-绿色版.zip')}")
    print("把文件夹(或解压后的文件夹)拷给工程师,双击「启动巡检助手.exe」即可。")


if __name__ == "__main__":
    main()
