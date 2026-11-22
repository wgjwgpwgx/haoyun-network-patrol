"""迈普 MyPower 交换机 Driver 测试

fixture 按官方手册格式构造(**未经真机验证**),现场适配走 UNKNOWN 回传流程。
覆盖场景：正常、空输出、格式不完整。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.drivers.maipu.driver import MaipuMyPowerSwitchDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "maipu" / "mypower_switch"


@pytest.fixture
def driver() -> MaipuMyPowerSwitchDriver:
    return MaipuMyPowerSwitchDriver()


@pytest.fixture
def load():
    def _load(filename: str) -> str:
        return (FIXTURES / filename).read_text(encoding="utf-8")
    return _load


class TestRegistry:
    def test_driver_registered(self):
        from patrol.drivers.registry import get_driver
        d = get_driver("maipu", "mypower_switch")
        assert isinstance(d, MaipuMyPowerSwitchDriver)


class TestDeviceInfo:
    def test_normal(self, driver, load):
        r = driver.parse_output("device_info", load("show_version.txt"))
        assert r.success is True
        d = r.parsed
        assert d["model"] == "S3100V2-24GT4XS"
        assert d["software_version"] == "2.10.13"
        assert "15 weeks" in d["uptime"]
        assert d["serial_number"] == "MP1102260B7"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", "")
        assert r.success is True
        assert r.parsed["model"] == ""


class TestCpuUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("cpu_usage", load("show_processes_cpu.txt"))
        assert r.success is True
        assert r.parsed["usage_5s"] == 12.0
        assert r.parsed["usage_percent"] == 12

    def test_empty(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None


class TestMemoryUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("memory_usage", load("show_memory_statistics.txt"))
        assert r.success is True
        assert r.parsed["total_bytes"] == 262144000
        assert r.parsed["usage_percent"] == 34  # 89128960/262144000


class TestInterfaceStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("interface_status", load("show_ip_interface_brief.txt"))
        assert r.success is True
        assert r.parsed["total"] == 3
        assert r.parsed["abnormal_count"] == 1
        assert r.parsed["abnormal_interfaces"] == ["GigabitEthernet0/2"]


class TestRoutingTable:
    def test_normal(self, driver, load):
        r = driver.parse_output("routing_table", load("show_ip_route.txt"))
        assert r.success is True
        assert r.parsed["routes"] == 3
        assert r.parsed["has_default_route"] is True


class TestLogbuffer:
    def test_normal(self, driver, load):
        r = driver.parse_output("logbuffer", load("show_logging.txt"))
        assert r.success is True
        assert r.parsed["total_lines"] == 4
        # 类 IOS %FACILITY-N-MNEM:仅 LINK-3(级别3) 计为告警
        assert r.parsed["error_count"] == 1


class TestConfigCur:
    def test_normal(self, driver, load):
        r = driver.parse_output("config_cur", load("show_running_config.txt"))
        assert r.success is True
        checks = {c["name"]: c["parsed"] for c in r.parsed["checks"]}
        assert checks["telnet_service"]["ssh_enabled"] is True
        assert checks["snmp_community"]["has_dangerous"] is True  # public 默认团体字
        assert checks["vty_auth"]["has_authentication"] is True
        assert checks["stp_status"]["stp_enabled"] is True


class TestLldpNeighbor:
    def test_normal(self, driver, load):
        r = driver.parse_output("lldp_neighbor", load("show_lldp_neighbors.txt"))
        assert r.success is True
        assert r.parsed["neighbor_count"] == 3
        first = r.parsed["neighbors"][0]
        assert first["local_intf"] == "Gi0/1"
        assert first["peer_device"] == "core-sw"
