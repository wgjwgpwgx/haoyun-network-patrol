# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - 昊云网络巡检助手绿色版(单文件 exe)

由 packaging/build_portable.py 调用:
    python -m PyInstaller --noconfirm --clean packaging/patrol_portable.spec

打包要点:
  - 内置模板/静态资源放在与源码相同的包路径下(patrol/api/templates 等),
    运行时代码用 Path(__file__).parent 定位,打包前后写法一致。
  - config/ 作为 config-defaults 内置,首次运行由 launcher 播种到 exe 旁。
  - docx 需自带 default.docx 模板;certifi 需自带 cacert.pem(AI 走 HTTPS)。
  - uvicorn/netmiko 存在动态导入,必须整包收集;playwright 体积过大且需
    浏览器内核,绿色版明确排除(Web 采集另行安装)。
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD_DIR = os.path.join(ROOT, "build")

datas = [
    (os.path.join(ROOT, "src", "patrol", "api", "templates"), "patrol/api/templates"),
    (os.path.join(ROOT, "src", "patrol", "api", "static"), "patrol/api/static"),
    (os.path.join(ROOT, "src", "patrol", "reporter", "templates"), "patrol/reporter/templates"),
    (os.path.join(ROOT, "config"), "config-defaults"),
]
datas += collect_data_files("docx")
datas += collect_data_files("certifi")

hiddenimports = ["win32com.client", "pythoncom", "pywintypes"]
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("netmiko")
hiddenimports += collect_submodules("patrol")

excludes = ["playwright"]  # tkinter 必须保留:桌面小工具窗口依赖(Python 自带)

a = Analysis(
    [os.path.join(ROOT, "src", "patrol", "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

_icon = os.path.join(BUILD_DIR, "app.ico")
_version = os.path.join(BUILD_DIR, "version_info.txt")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="启动巡检助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 窗口子系统:双击不产生黑色控制台(--web/CLI 由 launcher 按需接管输出)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon if os.path.exists(_icon) else None,
    version=_version if os.path.exists(_version) else None,
)
