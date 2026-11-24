"""打包配置(patrol_portable.spec)的数据文件清单。

两个平台共用一份 spec。清单写错了,源码测试照样全绿,要等成品在用户机器上首次启动才
暴露——页面打不开、设备驱动类缺失、播种配置时崩溃,或者把构建机的登录凭据带了进去。
这里直接执行 spec 到 Analysis 之前,按 Analysis 同样的方式展开清单,在两个平台的
分支下核对,不必构建(开发机上也构建不了另一个平台的包)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyInstaller")  # 只部署运行环境的机器上没有打包工具

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "patrol_portable.spec"


def embedded_files(platform: str, monkeypatch) -> set[str]:
    """在指定平台的分支下执行 spec(到 Analysis 之前),返回会进包的"程序内路径"。"""
    from PyInstaller.building.build_main import format_binaries_and_datas

    monkeypatch.setattr(sys, "platform", platform)
    namespace = {"SPECPATH": str(SPEC.parent)}
    source = SPEC.read_text(encoding="utf-8").split("\na = Analysis(")[0]
    exec(compile(source, SPEC.name, "exec"), namespace)  # noqa: S102 - 执行的是本项目的打包配置
    dest_src = format_binaries_and_datas(namespace["datas"], workingdir=str(SPEC.parent))
    return {dest.replace("\\", "/") for dest, _src in dest_src}


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_spec_packages_pages_templates_and_config(platform, monkeypatch):
    embedded = embedded_files(platform, monkeypatch)

    for name in ("patrol/api/templates/ui/login.html", "patrol/api/static/logo.png",
                 "patrol/reporter/templates", "docx/templates/default.docx", "certifi/cacert.pem"):
        assert any(path.startswith(name) for path in embedded), f"{name} 没有进包"

    # config/ 是首次运行的默认配置。登录凭据与发信配置是本机生成的,一旦带进程序,
    # 所有安装就共用同一把会话签名密钥、同一个发信授权码;少带了别的文件则播种时行为不对
    expected = {f"config-defaults/{path.relative_to(ROOT / 'config').as_posix()}"
                for path in (ROOT / "config").rglob("*")
                if path.is_file() and path.name not in ("auth.yaml", "smtp.yaml")}
    assert {path for path in embedded if path.startswith("config-defaults/")} == expected
