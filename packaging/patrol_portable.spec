# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - 昊云网络巡检助手绿色版(单文件)

Windows 由 packaging/build_portable.py 调用,Linux 由 packaging/build_portable_linux.py
调用,两个平台共用这一份:
    python -m PyInstaller --noconfirm --clean packaging/patrol_portable.spec

打包要点:
  - 数据文件与动态导入模块只在下面维护一处。不经过本文件打包,页面模板、报告模板、
    Word 模板都不会进包,按厂商名动态加载的设备驱动类也会缺失。
  - 内置模板/静态资源放在与源码相同的包路径下(patrol/api/templates 等),
    运行时代码用 Path(__file__).parent 定位,打包前后写法一致。
  - config/ 作为 config-defaults 内置,首次运行由 launcher 播种到 exe 旁;
    其中登录凭据与发信配置不内置,各安装首次运行时自行生成。
  - docx 需自带 default.docx 模板;certifi 需自带 cacert.pem(AI 走 HTTPS)。
  - uvicorn/netmiko 存在动态导入,必须整包收集;playwright 体积过大且需
    浏览器内核,绿色版明确排除(Web 采集另行安装)。
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD_DIR = os.path.join(ROOT, "build")
IS_WIN = sys.platform == "win32"

datas = [
    (os.path.join(ROOT, "src", "patrol", "api", "templates"), "patrol/api/templates"),
    (os.path.join(ROOT, "src", "patrol", "api", "static"), "patrol/api/static"),
    (os.path.join(ROOT, "src", "patrol", "reporter", "templates"), "patrol/reporter/templates"),
]
# config/ 作为 config-defaults 内置,首次运行由 launcher 播种到程序旁。登录凭据与发信
# 配置是本机生成的,不能当默认值带进程序(否则所有安装共用同一把会话签名密钥、
# 同一个发信授权码),所以逐个文件列出并跳过它们。
# 元组的第二项是目标文件夹,文件名由 PyInstaller 接在后面(写成完整文件名会多出一层目录)。
CONFIG_DIR = os.path.join(ROOT, "config")
for _dirpath, _dirs, _files in os.walk(CONFIG_DIR):
    for _name in _files:
        if _name not in ("auth.yaml", "smtp.yaml"):
            datas.append((os.path.join(_dirpath, _name),
                          os.path.join("config-defaults", os.path.relpath(_dirpath, CONFIG_DIR))))
datas += collect_data_files("docx")
datas += collect_data_files("certifi")

hiddenimports = []
if IS_WIN:
    hiddenimports += ["win32com.client", "pythoncom", "pywintypes"]  # Word 转 PDF
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("netmiko")
hiddenimports += collect_submodules("patrol")

if IS_WIN:
    excludes = ["playwright"]  # tkinter 必须保留:桌面小工具窗口依赖(Python 自带)
else:
    # Linux 包只提供命令行与 Web 模式:不带图形界面,launcher 导入 tkinter 失败后会转 Web 模式
    excludes = ["playwright", "tkinter", "_tkinter"]

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
    # Windows:窗口子系统,双击不产生黑色控制台(--web/CLI 由 launcher 按需接管输出);
    # Linux:控制台程序,终端里直接看巡检输出与 Web 模式日志
    name="启动巡检助手" if IS_WIN else "patrol-assistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=not IS_WIN,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon if IS_WIN and os.path.exists(_icon) else None,
    version=_version if IS_WIN and os.path.exists(_version) else None,
)
