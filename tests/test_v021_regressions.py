"""v0.2.1 修复回归(Web / 采集 / 驱动 / 导入 / 服务层):每条用例对应一个已修缺陷。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import patrol.api.app as app_module
import patrol.api.ui as ui_module
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from patrol.collector.ssh import SSHCollector
from patrol.desktop import service
from patrol.drivers.maipu.driver import MaipuMyPowerSwitchDriver
from patrol.drivers.registry import get_driver
from patrol.drivers.zte.driver import ZteZXR10SwitchDriver
from patrol.importer import import_rows, read_table
from patrol.models import DeviceAsset

RULES = Path(__file__).parent.parent / "config" / "rules" / "default.yaml"

_REPORT = {
    "title": "网络设备巡检报告", "generated_at": "2026-11-01T10:00:00",
    "devices": [{
        "name": "sw-01", "customer": "", "host": "192.0.2.1", "vendor": "h3c",
        "device_type": "comware_switch",
        "pass_count": 2, "fail_count": 1, "unknown_count": 0,
        "check_items": [
            {"name": "cpu_usage", "category": "CPU", "status": "PASS",
             "message": "ok", "details": {}},
            {"name": "memory_usage", "category": "内存", "status": "PASS",
             "message": "ok", "details": {}},
            {"name": "fan_status", "category": "硬件", "status": "FAIL",
             "message": "风扇故障", "details": {"severity": "critical"}},
        ],
    }],
}


@pytest.fixture
def web(tmp_path, monkeypatch):
    """隔离的 Web 环境:临时设备库/任务库/报告目录,并替换应用的全局实例。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    ds = DeviceStore(str(tmp_path / "devices.yaml"))
    cs = CustomerStore(str(tmp_path / "customers.yaml"))
    ts = TaskStore()
    tm = TaskManager(ds, ts, str(RULES), str(tmp_path / "output"))
    globals_ = (app_module, ui_module)
    saved = [(m._device_store, m._customer_store, m._task_store)
             for m in globals_]
    saved.append(app_module._task_manager)
    for m in globals_:
        m._device_store, m._customer_store, m._task_store = ds, cs, ts
    app_module._task_manager = tm
    yield TestClient(app_module.app)
    for m, (d, c, t) in zip(globals_, saved):
        m._device_store, m._customer_store, m._task_store = d, c, t
    app_module._task_manager = saved[-1]
    tm.shutdown()


class TestWebDashboardShowsRealNumbers:
    def test_counts_and_risks_come_from_latest_report(self, web, tmp_path):
        stem = tmp_path / "output" / "patrol_sw-01_20261101_100000"
        stem.with_suffix(".json").write_text(
            json.dumps(_REPORT, ensure_ascii=False), encoding="utf-8")
        stem.with_suffix(".html").write_text("<html></html>", encoding="utf-8")

        page = web.get("/ui").text

        assert "风扇故障" in page  # 风险明细(此前首页写死为空)
        assert "sw-01" in page
        assert re.search(r'num text-success">\s*2\s*<', page)
        assert re.search(r'num text-danger">\s*1\s*<', page)

    def test_without_any_report_it_says_so(self, web):
        page = web.get("/ui").text
        assert "还没有巡检报告" in page
        assert "暂无异常" not in page


class TestPrecheck:
    def test_udp_and_serial_methods_are_not_probed_over_tcp(self, web):
        devices = (("snmp-dev", "snmp", "192.0.2.50"),
                   ("console-dev", "console", "COM1"))
        for name, method, host in devices:
            r = web.post("/devices", json={
                "name": name, "host": host, "login_method": method,
                "username": "u", "password": "c"})
            assert r.status_code == 201, r.text

        with patch("socket.create_connection") as probe:
            data = web.post("/ui/tasks/precheck",
                            data={"device_names": "snmp-dev,console-dev"}).json()

        probe.assert_not_called()
        assert data["unreachable"] == 0
        assert all(r["reachable"] for r in data["results"])


class TestSuperPasswordAsEnableSecret:
    """类 IOS 设备登录后若落在非特权模式,netmiko 用 secret 做 enable 密码。"""

    @staticmethod
    def _connect_params(asset: DeviceAsset) -> dict:
        with patch("patrol.collector.ssh.ConnectHandler") as handler, \
                patch.object(SSHCollector, "_enter_super_mode"):
            SSHCollector().connect(asset)
        return handler.call_args[1]

    def test_passed_to_netmiko_as_secret(self):
        params = self._connect_params(DeviceAsset(
            name="rj", host="192.0.2.1", vendor="ruijie",
            device_type="rgos_switch", username="u", password="login-pw",
            super_password="enable-pw", timeout=5))
        assert params["secret"] == "enable-pw"
        assert params["password"] == "login-pw"

    def test_absent_when_not_configured(self):
        params = self._connect_params(DeviceAsset(
            name="hw", host="192.0.2.1", vendor="huawei",
            device_type="vrp_switch", username="u", password="login-pw",
            timeout=5))
        assert "secret" not in params


def _config_checks(driver, config: str) -> dict:
    parsed = driver.parse_output("config_cur", config)
    assert parsed.success
    return {c["name"]: c["parsed"] for c in parsed.parsed["checks"]}


class TestExplicitlyDisabledIsNotEnabled:
    @pytest.mark.parametrize("driver", [ZteZXR10SwitchDriver(),
                                        MaipuMyPowerSwitchDriver()])
    def test_no_prefix_and_disable_do_not_count_as_enabled(self, driver):
        checks = _config_checks(driver, "no telnet-server enable\n"
                                        "spanning-tree disable\n"
                                        "no snmp-server community public\n")
        assert checks["telnet_service"]["telnet_enabled"] is False
        assert checks["stp_status"]["stp_enabled"] is False
        assert checks["snmp_community"]["communities"] == []


class TestSnmpCommunityAttributeWords:
    @pytest.mark.parametrize("line", [
        "snmp community public ro",
        "snmp-server community public RO",
        "snmp-agent community read public",
    ])
    def test_readonly_word_is_not_mistaken_for_community(self, line):
        snmp = _config_checks(ZteZXR10SwitchDriver(), line + "\n")["snmp_community"]
        assert [c["community"] for c in snmp["communities"]] == ["public"]
        assert snmp["has_dangerous"] is True


class TestImportedDevicesCanGetADriver:
    @pytest.mark.parametrize("vendor,expected", [
        ("华为", "vrp_switch"), ("华三", "comware_switch"), ("锐捷", "rgos_switch"),
        ("中兴", "zxr10_switch"), ("迈普", "mypower_switch"),
    ])
    def test_missing_type_column_gets_vendor_default(self, tmp_path, vendor,
                                                     expected):
        from openpyxl import Workbook
        xlsx = tmp_path / "台账.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["管理地址", "用户名", "密码", "设备名称", "厂商"])
        ws.append(["192.0.2.10", "admin", "pw", "接入-01", vendor])
        wb.save(xlsx)

        table = read_table(xlsx)
        devices = DeviceStore(str(tmp_path / "d.yaml"))
        customers = CustomerStore(str(tmp_path / "c.yaml"))
        result = import_rows(devices, customers, table, {
            "host": 0, "username": 1, "password": 2, "name": 3, "vendor": 4})

        assert result["created"] == 1, result["errors"]
        dev = devices.get("接入-01")
        assert dev["device_type"] == expected
        get_driver(dev["vendor"], dev["device_type"])  # 取得到驱动才能巡检

    def test_type_written_in_sheet_is_kept(self, tmp_path):
        from openpyxl import Workbook
        xlsx = tmp_path / "台账.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["管理地址", "用户名", "密码", "设备名称", "厂商", "设备类型"])
        ws.append(["192.0.2.10", "admin", "pw", "核心-01", "华三", "s7506e"])
        wb.save(xlsx)

        table = read_table(xlsx)
        devices = DeviceStore(str(tmp_path / "d.yaml"))
        result = import_rows(devices, CustomerStore(str(tmp_path / "c.yaml")),
                             table, {"host": 0, "username": 1, "password": 2,
                                     "name": 3, "vendor": 4, "device_type": 5})

        assert result["created"] == 1, result["errors"]
        assert devices.get("核心-01")["device_type"] == "s7506e"


class TestNonWindowsPaths:
    @pytest.mark.parametrize("platform,opener",
                             [("darwin", "open"), ("linux", "xdg-open")])
    def test_open_path_uses_platform_opener(self, monkeypatch, platform, opener):
        monkeypatch.delattr(os, "startfile", raising=False)
        monkeypatch.setattr(sys, "platform", platform)
        calls: list[list[str]] = []
        monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args))
        target = os.path.join("output", "r.html")

        service.open_path(target)

        assert calls == [[opener, target]]

    def test_remove_schedule_does_not_call_schtasks(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: pytest.fail("非 Windows 平台不应调用 schtasks"))
        service.remove_schedule()
