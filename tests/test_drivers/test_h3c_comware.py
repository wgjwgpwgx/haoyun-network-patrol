"""H3C Comware Driver 解析测试 - 基于测试回显文件"""
from __future__ import annotations

import pytest

from patrol.drivers.h3c.comware_switch import H3CComwareSwitchDriver


@pytest.fixture
def driver() -> H3CComwareSwitchDriver:
    return H3CComwareSwitchDriver()


class TestDeviceInfo:
    def test_parse_version(self, driver, load_fixture):
        output = load_fixture("display_version.txt")
        result = driver.parse_output("device_info", output)

        assert result.success is True
        assert "S5560X" in result.parsed["model"]
        assert "7.1.075" in result.parsed["software_version"]
        assert "12 weeks" in result.parsed["uptime"]

    def test_parse_version_empty(self, driver):
        result = driver.parse_output("device_info", "")
        assert result.success is True
        assert result.parsed["model"] == ""


class TestCpuUsage:
    def test_parse_cpu(self, driver, load_fixture):
        output = load_fixture("display_cpu_usage.txt")
        result = driver.parse_output("cpu_usage", output)

        assert result.success is True
        assert result.parsed["usage_percent"] == 12

    def test_parse_cpu_high(self, driver):
        output = "Slot 0 CPU 0 usage:\n       95% in last 5 seconds"
        result = driver.parse_output("cpu_usage", output)

        assert result.success is True
        assert result.parsed["usage_percent"] == 95

    def test_parse_cpu_no_percent(self, driver):
        output = "No CPU information available."
        result = driver.parse_output("cpu_usage", output)

        assert result.success is True
        assert result.parsed["usage_percent"] is None


class TestMemoryUsage:
    def test_parse_memory(self, driver, load_fixture):
        output = load_fixture("display_memory.txt")
        result = driver.parse_output("memory_usage", output)

        assert result.success is True
        assert result.parsed["usage_percent"] == 35

    def test_parse_memory_fallback_calc(self, driver):
        output = "Total: 2048K\nUsed: 1024K"
        result = driver.parse_output("memory_usage", output)

        assert result.success is True
        assert result.parsed["usage_percent"] == 50


class TestInterfaceStatus:
    def test_parse_interfaces(self, driver, load_fixture):
        output = load_fixture("display_interface_brief.txt")
        result = driver.parse_output("interface_status", output)

        assert result.success is True
        assert result.parsed["total"] > 0
        assert result.parsed["abnormal_count"] > 0

    def test_parse_interfaces_all_up(self, driver):
        output = """Interface            Link Speed   Duplex  Type PVID
GE1/0/1              UP   1G      full    A    1
GE1/0/2              UP   100M    full    A    1
"""
        result = driver.parse_output("interface_status", output)
        assert result.success is True
        assert result.parsed["abnormal_count"] == 0
        assert result.parsed["total"] == 2


class TestInterfaceErrors:
    def test_parse_errors(self, driver, load_fixture):
        output = load_fixture("display_interface.txt")
        result = driver.parse_output("interface_errors", output)

        assert result.success is True
        assert result.parsed["error_count"] > 0
        assert result.parsed["interface_with_errors"] > 0

    def test_parse_no_errors(self, driver):
        output = """GigabitEthernet1/0/1
Current state: UP
Input:  100 packets, 5000 bytes
        0 errors, 0 CRC, 0 giants, 0 throttles
Output: 200 packets, 6000 bytes
        0 errors, 0 aborted, 0 deferred
"""
        result = driver.parse_output("interface_errors", output)

        assert result.success is True
        assert result.parsed["error_count"] == 0
        assert result.parsed["interface_with_errors"] == 0

    def test_parse_empty(self, driver):
        result = driver.parse_output("interface_errors", "")
        assert result.success is True
        assert result.parsed["error_count"] == 0


class TestTelnetService:
    def test_telnet_enabled(self, driver, load_fixture):
        output = load_fixture("display_tcp_status.txt")
        result = driver.parse_output("telnet_service", output)

        assert result.success is True
        assert result.parsed["telnet_enabled"] is True

    def test_telnet_disabled(self, driver, load_fixture):
        output = load_fixture("display_tcp_status_no_telnet.txt")
        result = driver.parse_output("telnet_service", output)

        assert result.success is True
        assert result.parsed["telnet_enabled"] is False

    def test_empty_output(self, driver):
        result = driver.parse_output("telnet_service", "")
        assert result.success is True
        assert result.parsed["telnet_enabled"] is False


class TestUnknownCheck:
    def test_unknown_check_name(self, driver):
        result = driver.parse_output("nonexistent_check", "some output")
        assert result.success is False
        assert "未实现" in result.error


class TestDeviceInfoEdgeCases:
    def test_serial_number(self, driver):
        """Serial Number 格式"""
        output = "H3C Comware Software\nSerial Number:210235A27SX001\n"
        r = driver.parse_output("device_info", output)
        assert r.parsed["serial_number"] == "210235A27SX001"

    def test_serial_number_with_spaces(self, driver):
        """Serial Number 带空格"""
        output = "Serial Number : ABC123DEF456\n"
        r = driver.parse_output("device_info", output)
        assert r.parsed["serial_number"] == "ABC123DEF456"

    def test_no_serial_number(self, driver):
        """无序列号时返回空字符串"""
        output = "H3C Comware Software\nVersion 5.20\n"
        r = driver.parse_output("device_info", output)
        assert r.parsed["serial_number"] == ""


class TestInterfaceErrorsEdgeCases:
    def test_errors_from_fixture(self, driver, load_fixture):
        """真实回显中的错误包"""
        output = load_fixture("display_interface.txt")
        r = driver.parse_output("interface_errors", output)
        assert r.success is True
        assert r.parsed["error_count"] > 0

    def test_no_errors(self, driver):
        """无错误包"""
        output = """GigabitEthernet1/0/1
Current state: UP
Input:  100 packets, 5000 bytes
        0 errors, 0 CRC
Output: 200 packets, 6000 bytes
        0 errors, 0 aborted
"""
        r = driver.parse_output("interface_errors", output)
        assert r.success is True
        assert r.parsed["error_count"] == 0


class TestDriverMetadata:
    def test_vendor(self, driver):
        assert driver.vendor == "h3c"

    def test_device_type(self, driver):
        assert driver.device_type == "comware_switch"

    def test_netmiko_type(self, driver):
        assert driver.netmiko_device_type == "hp_comware"

    def test_check_commands_count(self, driver):
        cmds = driver.get_check_commands()
        assert len(cmds) == 14  # 6 基础 + 7 九大类扩展
