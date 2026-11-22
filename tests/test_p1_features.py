"""P1 第一批功能测试:子网扫描/预检/AI摘要"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestScanRoutes:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"; cfg.mkdir()
        (cfg / "devices.yaml").write_text("devices: []", encoding="utf-8")
        (tmp_path / "output").mkdir()
        from fastapi.testclient import TestClient
        import patrol.api.app as am
        import patrol.api.ui as um
        from patrol.api.store import CustomerStore, DeviceStore, TaskStore
        from patrol.api.tasks import TaskManager
        from patrol.storage.sqlstore import bootstrap
        dev, cust, ts, audit = bootstrap(str(tmp_path / "data/patrol.db"))
        tm = TaskManager(dev, ts, str(
            Path(__file__).parent / "config/rules/default.yaml"
            if False else Path("config/rules/default.yaml")),
            str(tmp_path / "output"))
        saved = (am._device_store, am._customer_store, am._task_store,
                 am._task_manager, um._device_store, um._customer_store,
                 um._task_store)
        am._device_store, am._customer_store = dev, cust
        am._task_store, am._task_manager = ts, tm
        um._device_store, um._customer_store = dev, cust
        um._task_store = ts
        yield TestClient(am.app)
        (am._device_store, am._customer_store, am._task_store,
         am._task_manager, um._device_store, um._customer_store,
         um._task_store) = saved

    def test_scan_invalid_cidr(self, client):
        r = client.post("/ui/devices/scan", data={"cidr": "bad"})
        assert r.json()["ok"] is False

    @patch("patrol.netscan.scan_subnet")
    def test_scan_success(self, mock_scan, client):
        mock_scan.return_value = [
            {"host": "10.0.0.1", "alive": True, "vendor": "huawei",
             "device_type": "vrp_switch", "sysdescr": "Huawei S5735",
             "sysname": "sw-01"}]
        r = client.post("/ui/devices/scan",
                        data={"cidr": "10.0.0.0/24", "community": "public"})
        data = r.json()
        assert data["ok"] is True and data["total"] == 1

    def test_precheck(self, client):
        # 先建设备
        client.post("/devices", json={
            "name": "precheck-test", "host": "127.0.0.1",
            "username": "u", "password": "p"})
        r = client.post("/ui/tasks/precheck",
                        data={"device_names": "precheck-test"})
        data = r.json()
        assert data["ok"] is True
        # 127.0.0.1:22 可能通也可能不通,关键是返回结果结构正确
        assert "results" in data and len(data["results"]) == 1


class TestExecSummary:
    @pytest.fixture(autouse=True)
    def _clean_cwd(self, tmp_path, monkeypatch):
        """隔离工作目录,避免前序测试的 AI 配置干扰。"""
        monkeypatch.chdir(tmp_path)

    def test_template_fallback(self):
        from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport
        from patrol.reporter.html import _generate_exec_summary
        dev = DeviceReport(asset=DeviceAsset(name="d", host="10.0.0.1"))
        dev.check_items.append(CheckItem(
            name="cpu", category="CPU", command="c", raw_output="",
            status=CheckStatus.PASS, message="ok"))
        summary = _generate_exec_summary([dev], {"overall": 100})
        assert "1 台" in summary and "平稳" in summary

    def test_with_failures(self):
        from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport
        from patrol.reporter.html import _generate_exec_summary
        dev = DeviceReport(asset=DeviceAsset(name="bad-dev", host="10.0.0.2"))
        dev.check_items.append(CheckItem(
            name="fan", category="风扇", command="c", raw_output="",
            status=CheckStatus.FAIL, message="风扇故障"))
        summary = _generate_exec_summary([dev], {"overall": 40})
        assert "异常" in summary or "bad-dev" in summary
