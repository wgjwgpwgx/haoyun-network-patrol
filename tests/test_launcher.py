"""启动器(绿色包入口)单元测试"""
from __future__ import annotations

import socket

from patrol import launcher


class TestSeedConfig:
    def test_copies_missing_files_only(self, tmp_path, monkeypatch):
        defaults = tmp_path / "defaults"
        (defaults / "rules").mkdir(parents=True)
        (defaults / "ai.yaml").write_text("enabled: false", encoding="utf-8")
        (defaults / "rules" / "default.yaml").write_text("rules: []", encoding="utf-8")
        monkeypatch.setattr(launcher, "defaults_dir", lambda: defaults)

        root = tmp_path / "app"
        root.mkdir()
        (root / "config").mkdir()
        (root / "config" / "ai.yaml").write_text("enabled: true", encoding="utf-8")

        launcher.seed_config(root)
        # 已有文件不覆盖
        assert (root / "config" / "ai.yaml").read_text(encoding="utf-8") == "enabled: true"
        # 缺失文件被补齐(含子目录)
        assert (root / "config" / "rules" / "default.yaml").exists()

    def test_missing_defaults_creates_empty_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "defaults_dir", lambda: tmp_path / "nope")
        root = tmp_path / "app"
        launcher.seed_config(root)
        assert (root / "config").is_dir()

    def test_dev_defaults_is_project_config(self):
        assert (launcher.defaults_dir() / "rules" / "default.yaml").exists()


class TestPickPort:
    def test_returns_free_port_in_range(self):
        port = launcher.pick_port(48311, tries=5)
        assert 48311 <= port < 48316

    def test_skips_busy_port(self):
        busy = socket.socket()
        busy.bind(("127.0.0.1", 48321))
        busy.listen(1)
        try:
            port = launcher.pick_port(48321, tries=5)
            assert port != 48321
        finally:
            busy.close()


class TestAppRoot:
    def test_app_root_is_project_root(self):
        root = launcher.app_root()
        assert (root / "pyproject.toml").exists()

    def test_not_frozen_in_tests(self):
        assert launcher.is_frozen() is False


class TestDispatch:
    """入口分发:双击=桌面小工具,--web=Web 模式,其余=命令行工具。"""

    def _prepare(self, monkeypatch, tmp_path, argv):
        import sys

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(launcher, "app_root", lambda: tmp_path)
        monkeypatch.setattr(sys, "argv", argv)
        return tmp_path

    def test_no_args_runs_desktop_tool(self, monkeypatch, tmp_path):
        self._prepare(monkeypatch, tmp_path, ["启动巡检助手.exe"])
        called = {}
        monkeypatch.setattr("patrol.desktop.app.run",
                            lambda: called.setdefault("mode", "desktop") and 0 or 0)
        assert launcher.main() == 0
        assert called["mode"] == "desktop"

    def test_web_flag_runs_web_mode(self, monkeypatch, tmp_path):
        root = self._prepare(monkeypatch, tmp_path, ["启动巡检助手.exe", "--web"])
        called = {}
        monkeypatch.setattr(launcher, "run_web",
                            lambda r: called.setdefault("mode", "web") and 0 or 0)
        assert launcher.main() == 0
        assert called["mode"] == "web"

    def test_cli_args_run_cli(self, monkeypatch, tmp_path):
        self._prepare(monkeypatch, tmp_path, ["启动巡检助手.exe", "run", "-c", "x.yaml"])
        called = {}
        monkeypatch.setattr("patrol.cli.main",
                            lambda: called.setdefault("mode", "cli"))
        assert launcher.main() == 0
        assert called["mode"] == "cli"
