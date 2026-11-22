"""中兴 ZXR10 交换机 Driver 测试

fixture 按官方手册格式构造(**未经真机验证**),现场适配走 UNKNOWN 回传流程。
覆盖场景：正常、空输出、格式不完整。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.drivers.zte.driver import ZteZXR10SwitchDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "zte" / "zxr10_switch"


@pytest.fixture
def driver() -> ZteZXR10SwitchDriver:
    return ZteZXR10SwitchDriver()


@pytest.fixture
def load():
    def _load(filename: str) -> str:
        return (FIXTURES / filename).read_text(encoding="utf-8")
    return _load


class TestRegistry:
    def test_driver_registered(self):
        from patrol.drivers.registry import get_driver
        d = get_driver("zte", "zxr10_switch")
        assert isinstance(d, ZteZXR10SwitchDriver)


class TestDeviceInfo:
    def test_normal(self, driver, load):
        r = driver.parse_output("device_info", load("show_version.txt"))
        assert r.success is True
        d = r.parsed
        assert d["model"] == "5250-28PS-E"
        assert d["software_version"] == "V3.1.0"
        assert "12 weeks" in d["uptime"]
        assert d["serial_number"] == "ZTE05G10249"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", "")
        assert r.success is True
        assert r.parsed["model"] == ""


class TestCpuUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("cpu_usage", load("show_cpu.txt"))
        assert r.success is True
        assert r.parsed["usage_5s"] == 8.3
        assert r.parsed["usage_percent"] == 8

    def test_empty(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None


class TestMemoryUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("memory_usage", load("show_memory.txt"))
        assert r.success is True
        assert r.parsed["total_bytes"] == 1073741824
        assert r.parsed["usage_percent"] == 26


class TestInterfaceStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("interface_status", load("show_ip_interface_brief.txt"))
        assert r.success is True
        assert r.parsed["total"] == 4
        assert r.parsed["abnormal_count"] == 1
        assert r.parsed["abnormal_interfaces"] == ["gei-1/1/24"]


class TestRoutingTable:
    def test_normal(self, driver, load):
        r = driver.parse_output("routing_table", load("show_ip_route.txt"))
        assert r.success is True
        assert r.parsed["routes"] == 4
        assert r.parsed["has_default_route"] is True


class TestLogbuffer:
    def test_normal(self, driver, load):
        r = driver.parse_output("logbuffer", load("show_logging.txt"))
        assert r.success is True
        assert r.parsed["total_lines"] == 4
        # 级别取 %%01MOD/N/ 斜杠间:仅 /2/REBOOT(级别2) 计为告警
        assert r.parsed["error_count"] == 1


class TestConfigCur:
    def test_normal(self, driver, load):
        r = driver.parse_output("config_cur", load("show_running_config.txt"))
        assert r.success is True
        checks = {c["name"]: c["parsed"] for c in r.parsed["checks"]}
        assert checks["telnet_service"]["ssh_enabled"] is True
        assert checks["telnet_service"]["telnet_enabled"] is False
        assert checks["snmp_community"]["has_dangerous"] is False  # zte-public 非默认值
        assert checks["vty_auth"]["has_authentication"] is True
        assert checks["vty_auth"]["ssh_only"] is True
        assert checks["stp_status"]["stp_enabled"] is True


class TestLldpNeighbor:
    def test_normal(self, driver, load):
        r = driver.parse_output("lldp_neighbor", load("show_lldp_neighbors.txt"))
        assert r.success is True
        assert r.parsed["neighbor_count"] == 3
        first = r.parsed["neighbors"][0]
        assert first["local_intf"] == "gei-1/1/1"
        assert first["peer_device"] == "core-sw"
