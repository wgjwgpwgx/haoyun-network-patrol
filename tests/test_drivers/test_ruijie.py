"""锐捷 RGOS 交换机 Driver 测试 - 基于 RG-S5750C 真实回显

每个解析器覆盖四种场景：正常、异常、空输出、格式不完整。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.drivers.ruijie.driver import RuijieRGOSSwitchDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ruijie" / "rgos_switch"


@pytest.fixture
def driver() -> RuijieRGOSSwitchDriver:
    return RuijieRGOSSwitchDriver()


@pytest.fixture
def load():
    def _load(filename: str) -> str:
        return (FIXTURES / filename).read_text(encoding="utf-8")
    return _load


# ═══════════════════════════════════════════════════════════════
# show version → device_info
# ═══════════════════════════════════════════════════════════════


class TestDeviceInfo:
    def test_normal(self, driver, load):
        r = driver.parse_output("device_info", load("show_version.txt"))
        assert r.success is True
        d = r.parsed
        assert d["model"] == "S5750C-48GT4XS-H"
        assert d["software_version"] == "S5700H_RGOS"
        assert "28 weeks" in d["uptime"]
        assert d["serial_number"] == "G1M109S003135"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", "")
        assert r.success is True
        assert r.parsed["model"] == ""

    def test_incomplete(self, driver):
        r = driver.parse_output("device_info", "System description : Ruijie Switch\n")
        assert r.success is True
        assert r.parsed["model"] == ""


# ═══════════════════════════════════════════════════════════════
# show cpu → cpu_usage
# ═══════════════════════════════════════════════════════════════


class TestCpuUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("cpu_usage", load("show_cpu.txt"))
        assert r.success is True
        d = r.parsed
        assert d["usage_percent"] == 11
        assert d["usage_5s"] == 11.2
        assert d["usage_1m"] == 10.7
        assert d["usage_5m"] == 9.5

    def test_abnormal(self, driver):
        output = "CPU utilization in five seconds: 92.5%\nCPU utilization in one minute : 88.0%\nCPU utilization in five minutes: 85.0%\n"
        r = driver.parse_output("cpu_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 92  # round(92.5) = 92 (banker's rounding)

    def test_empty(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None

    def test_incomplete(self, driver):
        output = "CPU Using Rate Information\n"
        r = driver.parse_output("cpu_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] is None


# ═══════════════════════════════════════════════════════════════
# show memory → memory_usage
# ═══════════════════════════════════════════════════════════════


class TestMemoryUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("memory_usage", load("show_memory.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total_bytes"] == 1073741824
        assert d["used_bytes"] == 279134208
        assert d["usage_percent"] == 26

    def test_abnormal(self, driver):
        output = "System Total Memory(bytes): 512000000\nTotal Used Memory(bytes): 460800000\nMemory Used Rate: 90%\n"
        r = driver.parse_output("memory_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 90

    def test_empty(self, driver):
        r = driver.parse_output("memory_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None

    def test_incomplete(self, driver):
        output = "Memory Used Rate: 45%\n"
        r = driver.parse_output("memory_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 45


# ═══════════════════════════════════════════════════════════════
# show ip interface brief → interface_status
# ═══════════════════════════════════════════════════════════════


class TestInterfaceStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("interface_status", load("show_ip_interface_brief.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total"] == 5
        # Vlan 40 down
        assert d["abnormal_count"] == 1
        assert "Vlan 40" in d["abnormal_interfaces"]

    def test_abnormal(self, driver):
        output = (
            "Interface              IP-Address(Pri)      Status       Protocol\n"
            "Vlan 10                10.0.0.1/24          up           up\n"
            "Vlan 20                10.0.0.2/24          down         down\n"
        )
        r = driver.parse_output("interface_status", output)
        assert r.success is True
        assert r.parsed["abnormal_count"] == 1

    def test_empty(self, driver):
        r = driver.parse_output("interface_status", "")
        assert r.success is True
        assert r.parsed["total"] == 0

    def test_incomplete(self, driver):
        output = "Interface              IP-Address(Pri)\n"
        r = driver.parse_output("interface_status", output)
        assert r.success is True
        assert r.parsed["total"] == 0


# ═══════════════════════════════════════════════════════════════
# show ip route → routing_table
# ═══════════════════════════════════════════════════════════════


class TestRoutingTable:
    def test_normal(self, driver, load):
        r = driver.parse_output("routing_table", load("show_ip_route.txt"))
        assert r.success is True
        d = r.parsed
        assert d["routes"] == 6  # 4 connected + 1 OSPF + 1 static
        assert d["has_default_route"] is True

    def test_empty(self, driver):
        r = driver.parse_output("routing_table", "")
        assert r.success is True
        assert r.parsed["routes"] == 0

    def test_no_default(self, driver):
        output = "C    10.0.0.0/24 is directly connected, Vlan 10\n"
        r = driver.parse_output("routing_table", output)
        assert r.success is True
        assert r.parsed["has_default_route"] is False


# ═══════════════════════════════════════════════════════════════
# show logging reverse → logbuffer
# ═══════════════════════════════════════════════════════════════


class TestLogbuffer:
    def test_normal(self, driver, load):
        r = driver.parse_output("logbuffer", load("show_logging.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total_lines"] == 5
        # %%7, %%6, %%6, %%5, %%7 — 全部 > 3，无告警
        assert d["error_count"] == 0

    def test_abnormal(self, driver):
        output = "2026-09-21 10:00:00 SW1 %%1-SYSLOG: System crash!\n"
        r = driver.parse_output("logbuffer", output)
        assert r.success is True
        assert r.parsed["error_count"] == 1

    def test_empty(self, driver):
        r = driver.parse_output("logbuffer", "")
        assert r.success is True
        assert r.parsed["total_lines"] == 0


# ═══════════════════════════════════════════════════════════════
# show running-config → config_cur
# ═══════════════════════════════════════════════════════════════


class TestConfigCur:
    def test_normal(self, driver, load):
        r = driver.parse_output("config_cur", load("show_running_config.txt"))
        assert r.success is True
        checks = r.parsed["checks"]
        assert len(checks) == 4

    def test_ssh_enabled(self, driver, load):
        r = driver.parse_output("config_cur", load("show_running_config.txt"))
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["ssh_enabled"] is True

    def test_vty_auth(self, driver, load):
        r = driver.parse_output("config_cur", load("show_running_config.txt"))
        vty = next(c for c in r.parsed["checks"] if c["name"] == "vty_auth")
        assert vty["parsed"]["has_authentication"] is True
        assert vty["parsed"]["ssh_only"] is True

    def test_stp_enabled(self, driver, load):
        r = driver.parse_output("config_cur", load("show_running_config.txt"))
        stp = next(c for c in r.parsed["checks"] if c["name"] == "stp_status")
        assert stp["parsed"]["stp_enabled"] is True

    def test_empty(self, driver):
        r = driver.parse_output("config_cur", "")
        assert r.success is True
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is False


# ═══════════════════════════════════════════════════════════════
# 元数据
# ═══════════════════════════════════════════════════════════════


class TestDriverEdgeCases:
    def test_interface_mismatched_columns(self, driver):
        """列数不足的行应被跳过"""
        output = "Interface IP-Address Status\nVlan 10 10.0.0.1 up up\n"
        r = driver.parse_output("interface_status", output)
        assert r.success is True

    def test_routing_no_default_route(self, driver):
        output = "C    10.0.0.0/24 is directly connected, Vlan 10\n"
        r = driver.parse_output("routing_table", output)
        assert r.parsed["has_default_route"] is False

    def test_config_telnet_transport(self, driver):
        """transport input telnet 应标记 telnet_enabled"""
        output = "line vty 0 4\n login local\n transport input telnet\n!\nend\n"
        r = driver.parse_output("config_cur", output)
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is True

    def test_config_transport_all(self, driver):
        """transport input all 应标记 telnet_enabled"""
        output = "line vty 0 4\n transport input all\n!\nend\n"
        r = driver.parse_output("config_cur", output)
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is True

    def test_logbuffer_severity_boundary(self, driver):
        """severity=3 应计入告警，severity=4 不计入"""
        output = "2026-09-21 10:00:00 SW1 %%3-SYSLOG: Error!\n2026-09-21 10:01:00 SW1 %%4-SYSLOG: Warning.\n"
        r = driver.parse_output("logbuffer", output)
        assert r.parsed["error_count"] == 1


class TestDriverMetadata:
    def test_vendor(self, driver):
        assert driver.vendor == "ruijie"

    def test_device_type(self, driver):
        assert driver.device_type == "rgos_switch"

    def test_netmiko_type(self, driver):
        assert driver.netmiko_device_type == "ruijie_os"

    def test_check_commands_count(self, driver):
        assert len(driver.get_check_commands()) == 8

    def test_unknown_check(self, driver):
        r = driver.parse_output("nonexistent", "output")
        assert r.success is False
