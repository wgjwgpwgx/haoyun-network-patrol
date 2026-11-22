"""迪普 DPtech Driver 测试 - 基于真实 info-table HTML 结构"""
from __future__ import annotations

import pytest

from patrol.drivers.dptech.driver import DPtechFWFirewallDriver


@pytest.fixture
def driver() -> DPtechFWFirewallDriver:
    return DPtechFWFirewallDriver()


class TestDriverMetadata:
    def test_vendor(self, driver):
        assert driver.vendor == "dptech"
    def test_device_type(self, driver):
        assert driver.device_type == "fw_firewall"
    def test_check_commands(self, driver):
        assert len(driver.get_check_commands()) == 4


class TestDeviceInfo:
    def test_info_table(self, driver):
        html = '''
        <table class="info-table">
            <tr><td>设备型号</td><td>FW2000-GA</td></tr>
            <tr><td>设备名称</td><td>FW-CORE-01</td></tr>
            <tr><td>软件版本</td><td>V3.0-R5.0</td></tr>
            <tr><td>序列号</td><td>DP123456789</td></tr>
            <tr><td>运行时间</td><td>30 days 5 hours</td></tr>
        </table>
        '''
        r = driver.parse_output("device_info", html)
        assert r.success is True
        d = r.parsed
        assert d["model"] == "FW2000-GA"
        assert d["device_name"] == "FW-CORE-01"
        assert d["software_version"] == "V3.0-R5.0"
        assert d["serial_number"] == "DP123456789"
        assert d["uptime"] == "30 days 5 hours"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", "")
        assert r.success is True
        assert r.parsed["model"] == ""

    def test_no_info_table(self, driver):
        r = driver.parse_output("device_info", "<div>no table</div>")
        assert r.parsed["model"] == ""


class TestCpuUsage:
    def test_info_table(self, driver):
        html = '''
        <table class="info-table">
            <tr><td>CPU 利用率</td><td>23%</td></tr>
        </table>
        '''
        r = driver.parse_output("cpu_usage", html)
        assert r.success is True
        assert r.parsed["usage_percent"] == 23

    def test_fallback_percent(self, driver):
        html = '<div>CPU Usage: 45%</div>'
        r = driver.parse_output("cpu_usage", html)
        assert r.parsed["usage_percent"] == 45

    def test_empty(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.parsed["usage_percent"] is None


class TestMemoryUsage:
    def test_info_table(self, driver):
        html = '''
        <table class="info-table">
            <tr><td>内存使用率</td><td>55%</td></tr>
            <tr><td>总内存</td><td>4294967296</td></tr>
            <tr><td>已用内存</td><td>2362232013</td></tr>
        </table>
        '''
        r = driver.parse_output("memory_usage", html)
        assert r.success is True
        assert r.parsed["usage_percent"] == 55
        assert r.parsed["total_bytes"] == 4294967296
        assert r.parsed["used_bytes"] == 2362232013


class TestInterfaceStatus:
    def test_info_table(self, driver):
        html = '''
        <table class="info-table">
            <tr><td>ge0</td><td>up</td></tr>
            <tr><td>ge1</td><td>up</td></tr>
            <tr><td>ge2</td><td>down</td></tr>
            <tr><td>ge3</td><td>up</td></tr>
        </table>
        '''
        r = driver.parse_output("interface_status", html)
        assert r.success is True
        assert r.parsed["total"] == 4
        assert r.parsed["abnormal_count"] == 1
        assert "ge2" in r.parsed["abnormal_interfaces"]

    def test_all_up(self, driver):
        html = '''
        <table class="info-table">
            <tr><td>ge0</td><td>up</td></tr>
            <tr><td>ge1</td><td>up</td></tr>
        </table>
        '''
        r = driver.parse_output("interface_status", html)
        assert r.parsed["abnormal_count"] == 0

    def test_empty(self, driver):
        r = driver.parse_output("interface_status", "")
        assert r.parsed["total"] == 0
