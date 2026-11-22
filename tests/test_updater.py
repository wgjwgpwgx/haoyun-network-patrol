"""绿色包自动更新服务测试(patron.updater)"""
from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from patrol.updater import (
    UpdateError,
    clear_pending,
    download_package,
    install_now,
    load_pending,
    stage_update,
    update_dir,
    write_update_script,
)


def _make_zip(path, files: dict[str, bytes]) -> "zipfile.ZipFile":
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


class TestDownloadPackage:
    def test_local_copy(self, tmp_path):
        src = tmp_path / "pkg.zip"
        src.write_bytes(b"PK\x05\x06" + b"x" * 10)
        dest = download_package(str(src), "0.2.0", root=tmp_path)
        assert dest.exists()
        assert dest.read_bytes() == src.read_bytes()
        assert dest.parent == update_dir(tmp_path) / "downloads"

    def test_sha256_verify_ok(self, tmp_path):
        src = tmp_path / "pkg.zip"
        data = b"content-for-hash"
        src.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        dest = download_package(str(src), "0.2.0", root=tmp_path, expected_sha256=digest)
        assert dest.exists()

    def test_sha256_mismatch_rejected(self, tmp_path):
        src = tmp_path / "pkg.zip"
        src.write_bytes(b"tampered")
        with pytest.raises(UpdateError, match="校验失败"):
            download_package(str(src), "0.2.0", root=tmp_path, expected_sha256="0" * 64)
        assert not (update_dir(tmp_path) / "downloads" / "update-0.2.0.zip").exists()

    def test_missing_source(self, tmp_path):
        with pytest.raises(UpdateError, match="不存在"):
            download_package(str(tmp_path / "nope.zip"), root=tmp_path)

    def test_empty_url(self, tmp_path):
        with pytest.raises(UpdateError, match="地址为空"):
            download_package("", root=tmp_path)


class TestStageUpdate:
    def test_stages_exe_and_text_from_nested_folder(self, tmp_path):
        z = _make_zip(tmp_path / "p.zip", {
            "昊云网络巡检助手/启动巡检助手.exe": b"MZ-fake-exe",
            "昊云网络巡检助手/使用说明.txt": b"readme",
            "昊云网络巡检助手/LICENSE.txt": b"MIT",
        })
        pending = stage_update(z, "0.2.0", root=tmp_path)
        staging = update_dir(tmp_path) / "staging"
        assert (staging / "启动巡检助手.exe").read_bytes() == b"MZ-fake-exe"
        assert (staging / "使用说明.txt").exists()
        assert (staging / "LICENSE.txt").exists()
        assert pending["exe_name"] == "启动巡检助手.exe"
        assert pending["version"] == "0.2.0"
        assert load_pending(tmp_path)["version"] == "0.2.0"

    def test_never_stages_user_data(self, tmp_path):
        z = _make_zip(tmp_path / "p.zip", {
            "app/启动巡检助手.exe": b"MZ",
            "app/config/ai.yaml": b"api_key: SECRET",
            "app/output/report.html": b"<html>",
        })
        stage_update(z, "0.3.0", root=tmp_path)
        staging = update_dir(tmp_path) / "staging"
        assert not (staging / "config").exists()
        assert not (staging / "output").exists()
        assert list(staging.iterdir()) == [staging / "启动巡检助手.exe"]

    def test_flat_layout(self, tmp_path):
        z = _make_zip(tmp_path / "p.zip", {"启动巡检助手.exe": b"MZ"})
        pending = stage_update(z, "0.2.0", root=tmp_path)
        assert pending["exe_name"] == "启动巡检助手.exe"

    def test_no_exe_raises(self, tmp_path):
        z = _make_zip(tmp_path / "p.zip", {"readme.txt": b"x"})
        with pytest.raises(UpdateError, match="未找到程序文件"):
            stage_update(z, root=tmp_path)

    def test_bad_zip_raises(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        with pytest.raises(UpdateError, match="不是有效的 zip"):
            stage_update(bad, root=tmp_path)

    def test_clear_pending(self, tmp_path):
        z = _make_zip(tmp_path / "p.zip", {"启动巡检助手.exe": b"MZ"})
        stage_update(z, "0.2.0", root=tmp_path)
        clear_pending(tmp_path)
        assert load_pending(tmp_path) is None


class TestUpdateScript:
    def test_script_content_ascii_and_complete(self, tmp_path):
        script = write_update_script(4242, root=tmp_path)
        text = script.read_text(encoding="ascii")  # 必须纯 ASCII
        assert "rem spawned from pid 4242" in text
        assert "update\\backup" in text        # 备份旧程序(且只备一次,防覆盖)
        assert "staging\\*.exe" in text        # 通配符替换,避免中文名
        assert 'start "" "%APPDIR%' in text.replace("%%F", "%APPDIR%") or 'do start "" "%%F"' in text
        assert 'del "%~f0"' in text            # 脚本自删
        assert "del /q \"%APPDIR%update\\pending.json\"" in text
        # 重启前清 PyInstaller 引导变量,防止新实例误入子启动阶段秒退
        for var in ("_MEIPASS", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL",
                    "PYINSTALLER_RESET_ENVIRONMENT"):
            assert f'set "{var}="' in text
        assert b"\r\r\n" not in script.read_bytes()  # 行尾必须是精确 CRLF

    def test_no_pid_polling_lock_is_readiness(self, tmp_path):
        # 不轮询 PID(PID 会被回收导致误判);以拷贝成功(fc /b 校验)作为就绪判定
        text = write_update_script(1, root=tmp_path).read_text(encoding="ascii")
        assert "tasklist" not in text
        assert ":retry" in text and "fc /b" in text


class TestInstallNow:
    def test_dev_mode_rejected(self, tmp_path):
        z = _make_zip(tmp_path / "p.zip", {"启动巡检助手.exe": b"MZ"})
        stage_update(z, "0.2.0", root=tmp_path)
        with pytest.raises(UpdateError, match="源码运行模式"):
            install_now(root=tmp_path)

    def test_without_pending_rejected(self, tmp_path):
        # frozen 检查在前;用 monkeypatch 绕过以测无 pending 分支
        import patrol.updater as updater_mod

        original = updater_mod.is_frozen
        updater_mod.is_frozen = lambda: True
        try:
            with pytest.raises(UpdateError, match="没有待安装的更新包"):
                install_now(root=tmp_path)
        finally:
            updater_mod.is_frozen = original
