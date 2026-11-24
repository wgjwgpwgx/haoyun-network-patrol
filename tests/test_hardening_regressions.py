"""v0.2.1 收尾加固回归(非界面部分):每条用例对应一个已修的小缺陷。"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import load_workbook

from patrol.api.store import DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from patrol.collector.web import WebCollector
from patrol.models import (
    CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport,
)
from patrol.reporter.excel import ExcelReporter
from patrol.update import load_update_url, save_update_url
from patrol.utils.filename import unique_filename

RULES = Path(__file__).parent.parent / "config" / "rules" / "default.yaml"


def _report(name: str = "sw", customer: str = "") -> PatrolReport:
    device = DeviceReport(asset=DeviceAsset(
        name=name, host="192.0.2.1", customer=customer, vendor="h3c",
        device_type="comware_switch"))
    device.check_items.append(CheckItem(
        name="cpu_usage", category="CPU", command="display cpu-usage",
        raw_output="95%", status=CheckStatus.FAIL, message="CPU 过高",
        details={"severity": "critical", "suggestion": "排查异常进程"}))
    return PatrolReport(devices=[device])


class TestWebCollectorHonoursCertificateSwitch:
    """设备上"跳过证书校验"关着时,Web 登录必须校验证书(此前恒为跳过)。"""

    @staticmethod
    def _context_kwargs(verify_ssl: bool) -> dict:
        seen: dict = {}

        def new_context(**kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop-after-context")  # 只关心创建上下文时的参数

        with patch("playwright.sync_api.sync_playwright") as playwright:
            browser = playwright.return_value.start.return_value \
                .chromium.launch.return_value
            browser.new_context.side_effect = new_context
            collector = WebCollector()
            asset = DeviceAsset(
                name="fw", host="192.0.2.1", vendor="sangfor",
                device_type="ngaf_firewall", login_method="web",
                web_protocol="https", username="u", password="p",
                verify_ssl=verify_ssl, screenshot=False, timeout=5)
            with pytest.raises(Exception):
                collector.connect(asset)
            collector.disconnect()
        return seen

    def test_certificate_is_verified_by_default(self):
        assert self._context_kwargs(True)["ignore_https_errors"] is False

    def test_switch_on_skips_verification(self):
        assert self._context_kwargs(False)["ignore_https_errors"] is True


class TestExcelNeutralisesFormulaPrefix:
    def test_formula_like_text_is_stored_as_text(self, tmp_path):
        """以 = + - @ 开头的文本会被 Excel 当公式执行(设备名、客户名都是用户可控的)。"""
        report = _report(name='=HYPERLINK("http://evil.example")', customer="-1+1")
        path = ExcelReporter().generate(report, tmp_path / "r.xlsx")

        inventory = load_workbook(path)["设备台账"]
        assert inventory.cell(row=2, column=1).value == "'-1+1"
        assert inventory.cell(row=2, column=2).value == \
            "'=HYPERLINK(\"http://evil.example\")"
        assert inventory.cell(row=2, column=9).value == 0  # 数值列不受影响

        issues = load_workbook(path)["异常跟踪"]
        assert str(issues.cell(row=2, column=1).value).startswith("'=")
        assert issues.cell(row=2, column=5).value == "排查异常进程"  # 普通文本原样


class TestSettingsFileIsNeverSilentlyWiped:
    def test_corrupt_file_is_kept_aside_before_rewrite(self, tmp_path):
        path = tmp_path / "settings.yaml"
        path.write_text("update_manifest_url: [unclosed\nother_setting: 1\n",
                        encoding="utf-8")

        save_update_url("https://updates.example.com/m.json", path)

        assert load_update_url(path) == "https://updates.example.com/m.json"
        backups = list(tmp_path.glob("settings.broken-*.yaml"))
        assert len(backups) == 1
        assert "other_setting: 1" in backups[0].read_text(encoding="utf-8")

    def test_healthy_file_keeps_other_settings(self, tmp_path):
        path = tmp_path / "settings.yaml"
        path.write_text("other_setting: keep-me\nupdate_manifest_url: old\n",
                        encoding="utf-8")

        save_update_url("https://new.example.com/m.json", path)

        assert "keep-me" in path.read_text(encoding="utf-8")


class TestSessionTokenParsing:
    def test_non_ascii_signature_is_rejected_rather_than_crashing(self):
        from patrol.api.auth import _valid_token

        assert _valid_token("1700000000.中文签名") is False
        assert _valid_token("1700000000." + "a" * 64 + "\u00e9") is False

    def test_issued_token_is_valid(self):
        from patrol.api.auth import _issue_token, _valid_token

        assert _valid_token(_issue_token()) is True


class TestReportsNeverOverwriteEachOther:
    def test_unique_filename_appends_a_counter(self, tmp_path):
        first = unique_filename(tmp_path, "patrol_192.0.2.1_20261124_120000.html")
        assert first == "patrol_192.0.2.1_20261124_120000.html"
        (tmp_path / first).write_text("x", encoding="utf-8")

        # 主机地址里带点:序号必须加在末尾,不能把地址切碎
        assert unique_filename(tmp_path, first) == "patrol_192.0.2.1_20261124_120000_2.html"

        # 只有伴生的数据文件存在(上一次只写了一半)同样算重名
        (tmp_path / "patrol_sw_20261124_120000_3.json").write_text("{}", encoding="utf-8")
        assert unique_filename(tmp_path, "patrol_sw_20261124_120000_3.html") == \
            "patrol_sw_20261124_120000_3_2.html"

    def test_two_tasks_finishing_in_the_same_second_get_two_files(
            self, tmp_path, monkeypatch):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 24, 12, 0, 0)

        monkeypatch.setenv("PATROL_CONCURRENCY", "1")  # 串行,避免两个任务同时判定重名
        monkeypatch.setattr("patrol.api.tasks.datetime", Frozen)

        config = tmp_path / "devices.yaml"
        config.write_text("devices: []\n", encoding="utf-8")
        devices, tasks = DeviceStore(str(config)), TaskStore()
        manager = TaskManager(devices, tasks, str(RULES), str(tmp_path / "output"))
        try:
            for i in range(2):
                devices.create({"name": f"sw-{i}", "host": "192.0.2.1",
                                "vendor": "h3c", "device_type": "comware_switch",
                                "username": "u", "password": "p"})
            monkeypatch.setattr(
                "patrol.api.tasks.run_inspection",
                lambda asset, driver, engine, incremental=False: DeviceReport(asset=asset))
            monkeypatch.setattr("patrol.storage.history.HistoryStore.save_run",
                                lambda self, **kw: None)

            outs = [manager.create_batch_task([f"sw-{i}"]) for i in range(2)]
            deadline = time.time() + 5
            while time.time() < deadline and any(
                    tasks.get(o.task_id)["status"] not in ("completed", "failed")
                    for o in outs):
                time.sleep(0.05)

            files = sorted(tasks.get(o.task_id)["report_file"] for o in outs)
            assert files == ["patrol_192.0.2.1_20261124_120000.html",
                             "patrol_192.0.2.1_20261124_120000_2.html"]
            assert all((tmp_path / "output" / f).exists() for f in files)
        finally:
            manager.shutdown()


class TestShutdownCancelsQueuedTasks:
    def test_queued_tasks_do_not_run_after_shutdown(self, tmp_path, monkeypatch):
        """退出程序时,还没轮到的巡检不应留在后台继续跑。"""
        monkeypatch.setenv("PATROL_CONCURRENCY", "1")
        config = tmp_path / "devices.yaml"
        config.write_text("devices: []\n", encoding="utf-8")
        devices, tasks = DeviceStore(str(config)), TaskStore()
        manager = TaskManager(devices, tasks, str(RULES), str(tmp_path / "output"))
        started, release = threading.Event(), threading.Event()

        def slow_inspection(asset, driver, engine, incremental=False):
            started.set()
            release.wait(5)
            return DeviceReport(asset=asset)

        try:
            for i in range(3):
                devices.create({"name": f"sw-{i}", "host": "192.0.2.1",
                                "vendor": "h3c", "device_type": "comware_switch",
                                "username": "u", "password": "p"})
            monkeypatch.setattr("patrol.api.tasks.run_inspection", slow_inspection)
            monkeypatch.setattr("patrol.storage.history.HistoryStore.save_run",
                                lambda self, **kw: None)
            for i in range(3):
                manager.create_batch_task([f"sw-{i}"])
            assert started.wait(5)  # 第一台已在采集

            manager.shutdown()
            release.set()

            deadline = time.time() + 5
            while time.time() < deadline and tasks.get(
                    [t for t in tasks.list_all() if t["device_name"] == "sw-0"][0]
                    ["task_id"])["status"] != "completed":
                time.sleep(0.05)
            queued = [t for t in tasks.list_all() if t["device_name"] != "sw-0"]
            assert len(queued) == 2
            assert all(t["status"] == "pending" for t in queued)  # 排队的被取消,没有执行

            assert manager.reconcile_interrupted() == 2  # 下次启动标为已中断
            assert all(tasks.get(t["task_id"])["status"] == "failed" for t in queued)
        finally:
            release.set()
            manager.shutdown()
