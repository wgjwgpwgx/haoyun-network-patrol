"""华为 VRP 交换机 Driver 测试 - 基于 S5735-S48P4X 真实回显

每个解析器覆盖四种场景：
  1. 正常 — 真实设备回显
  2. 异常 — 触发 FAIL 的值
  3. 空输出 — 空字符串
  4. 格式不完整 — 部分/截断数据
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "huawei" / "vrp_switch"


@pytest.fixture
def driver() -> HuaweiVRPSwitchDriver:
    return HuaweiVRPSwitchDriver()


@pytest.fixture
def load():
    def _load(filename: str) -> str:
        return (FIXTURES / filename).read_text(encoding="utf-8")
    return _load


# ═══════════════════════════════════════════════════════════════
# display version → device_info
# ═══════════════════════════════════════════════════════════════


class TestDeviceInfo:
    def test_normal(self, driver, load):
        r = driver.parse_output("device_info", load("display_version.txt"))
        assert r.success is True
        d = r.parsed
        assert d["model"] == "S5735‑S48P4X"
        assert d["software_version"] == "V500R019C10SPC500"
        assert "35 weeks" in d["uptime"]
        assert d["serial_number"] == "2102354835106F000127"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", "")
        assert r.success is True
        assert r.parsed["model"] == ""
        assert r.parsed["uptime"] == ""

    def test_incomplete(self, driver):
        output = "Huawei Versatile Routing Platform Software\n"
        r = driver.parse_output("device_info", output)
        assert r.success is True
        assert r.parsed["model"] == ""


# ═══════════════════════════════════════════════════════════════
# display cpu-usage → cpu_usage
# ═══════════════════════════════════════════════════════════════


class TestCpuUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("cpu_usage", load("display_cpu_usage.txt"))
        assert r.success is True
        d = r.parsed
        assert d["usage_percent"] == 14
        assert d["usage_10s"] == 14.3
        assert d["usage_1m"] == 13.7
        assert d["usage_5m"] == 12.1
        assert d["max_usage"] == 72.6

    def test_abnormal(self, driver):
        output = "Control Plane\nCPU Usage: 92.1%   Max: 95.0%\n"
        r = driver.parse_output("cpu_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 92

    def test_empty(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None

    def test_incomplete(self, driver):
        output = "CPU Usage Stat. Cycle: 10 (Second)\n"
        r = driver.parse_output("cpu_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] is None


# ═══════════════════════════════════════════════════════════════
# display memory-usage → memory_usage
# ═══════════════════════════════════════════════════════════════


class TestMemoryUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("memory_usage", load("display_memory_usage.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total_bytes"] == 1610612736
        assert d["used_bytes"] == 418759315
        assert d["usage_percent"] == 26

    def test_abnormal(self, driver):
        output = "System Total Memory Is: 1000000 bytes\nTotal Memory Used Is: 920000 bytes\nMemory Using Percentage Is: 92%\n"
        r = driver.parse_output("memory_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 92

    def test_empty(self, driver):
        r = driver.parse_output("memory_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None

    def test_incomplete(self, driver):
        output = "Memory Using Percentage Is: 45%\n"
        r = driver.parse_output("memory_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 45
        assert r.parsed["total_bytes"] is None


# ═══════════════════════════════════════════════════════════════
# display interface brief → interface_status
# ═══════════════════════════════════════════════════════════════


class TestInterfaceStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("interface_status", load("display_interface_brief.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total"] == 14
        # GE0/0/3, GE0/0/5-48, XGE0/0/3, XGE0/0/4, Vlanif40 = 5 个 down
        assert d["abnormal_count"] == 5
        assert "GigabitEthernet0/0/3" in d["abnormal_interfaces"]
        assert "GigabitEthernet0/0/5‑48" in d["abnormal_interfaces"]
        assert "Vlanif40" in d["abnormal_interfaces"]

    def test_abnormal(self, driver):
        output = (
            "Interface PHY Protocol InUti OutUti inErrors outErrors\n"
            "GigabitEthernet0/0/1 up up 0.01% 0.01% 5 3\n"
        )
        r = driver.parse_output("interface_status", output)
        assert r.success is True
        assert r.parsed["interfaces"][0]["in_errors"] == 5
        assert r.parsed["interfaces"][0]["out_errors"] == 3

    def test_empty(self, driver):
        r = driver.parse_output("interface_status", "")
        assert r.success is True
        assert r.parsed["total"] == 0

    def test_incomplete(self, driver):
        output = "PHY: Physical\nInterface PHY Protocol\n"
        r = driver.parse_output("interface_status", output)
        assert r.success is True
        assert r.parsed["total"] == 0


# ═══════════════════════════════════════════════════════════════
# display ip routing-table → routing_table
# ═══════════════════════════════════════════════════════════════


class TestRoutingTable:
    def test_normal(self, driver, load):
        r = driver.parse_output("routing_table", load("display_ip_routing_table.txt"))
        assert r.success is True
        assert r.parsed["destinations"] == 421
        assert r.parsed["routes"] == 421

    def test_empty(self, driver):
        r = driver.parse_output("routing_table", "")
        assert r.success is True
        assert r.parsed["destinations"] == 0

    def test_incomplete(self, driver):
        output = "Destinations : 100\n"
        r = driver.parse_output("routing_table", output)
        assert r.success is True
        assert r.parsed["destinations"] == 100
        assert r.parsed["routes"] == 0


# ═══════════════════════════════════════════════════════════════
# display fan → fan_status
# ═══════════════════════════════════════════════════════════════


class TestFanStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("fan_status", load("display_fan.txt"))
        assert r.success is True
        assert r.parsed["fan_count"] == 1
        assert r.parsed["abnormal_count"] == 0
        assert r.parsed["fans"][0]["state"] == "Normal"

    def test_abnormal(self, driver):
        output = "Fan 1:\n  Status: Normal\nFan 2:\n  Status: Abnormal\n"
        r = driver.parse_output("fan_status", output)
        assert r.success is True
        assert r.parsed["abnormal_count"] == 1

    def test_empty(self, driver):
        r = driver.parse_output("fan_status", "")
        assert r.success is True
        assert r.parsed["fan_count"] == 0


# ═══════════════════════════════════════════════════════════════
# display power → power_status
# ═══════════════════════════════════════════════════════════════


class TestPowerStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("power_status", load("display_power.txt"))
        assert r.success is True
        assert r.parsed["power_count"] == 2
        assert r.parsed["abnormal_count"] == 0

    def test_abnormal(self, driver):
        output = "Power 1:\n  Status: Normal\nPower 2:\n  Status: Fault\n"
        r = driver.parse_output("power_status", output)
        assert r.success is True
        assert r.parsed["abnormal_count"] == 1

    def test_empty(self, driver):
        r = driver.parse_output("power_status", "")
        assert r.success is True
        assert r.parsed["power_count"] == 0


# ═══════════════════════════════════════════════════════════════
# display logbuffer → logbuffer
# ═══════════════════════════════════════════════════════════════


class TestLogbuffer:
    def test_normal(self, driver, load):
        r = driver.parse_output("logbuffer", load("display_logbuffer.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total_lines"] == 5
        # severity: SHELL/6=6, IFNET/4=4, IFNET/4=4, OSPF/6=6, SEC/6=6
        # 全部 >= 4，无告警
        assert d["error_count"] == 0

    def test_abnormal(self, driver):
        output = (
            "%2026-09-21T10:00:00.000 SW1 %%01OSPF/1/NEIGHBOR(l):Neighbor down.\n"
            "%2026-09-21T10:01:00.000 SW1 %%01IFNET/4/LINK_STATE(l):Link up.\n"
        )
        r = driver.parse_output("logbuffer", output)
        assert r.success is True
        assert r.parsed["error_count"] == 1  # severity 1

    def test_empty(self, driver):
        r = driver.parse_output("logbuffer", "")
        assert r.success is True
        assert r.parsed["total_lines"] == 0
        assert r.parsed["error_count"] == 0


# ═══════════════════════════════════════════════════════════════
# display current-configuration → config_cur
# ═══════════════════════════════════════════════════════════════


class TestConfigCur:
    def test_normal(self, driver, load):
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        assert r.success is True
        checks = r.parsed["checks"]
        assert len(checks) == 9  # 4 原有安全项 + 5 等保基线项

    def test_ssh_enabled(self, driver, load):
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is False
        assert telnet["parsed"]["ssh_enabled"] is True

    def test_vty_auth(self, driver, load):
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        vty = next(c for c in r.parsed["checks"] if c["name"] == "vty_auth")
        assert vty["parsed"]["has_authentication"] is True
        assert vty["parsed"]["ssh_only"] is True

    def test_stp_enabled(self, driver, load):
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
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
    def test_config_cur_telnet_enabled(self, driver):
        """配置中有 telnet server enable"""
        output = "telnet server enable\nssh server enable\n#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is True
        assert telnet["parsed"]["ssh_enabled"] is True

    def test_config_cur_vty_no_auth(self, driver):
        """VTY 无认证"""
        output = "user-interface vty 0 4\n protocol inbound ssh\n#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        vty = next(c for c in r.parsed["checks"] if c["name"] == "vty_auth")
        assert vty["parsed"]["has_authentication"] is False

    def test_config_cur_stp_disabled(self, driver):
        """STP 未启用"""
        output = "#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        stp = next(c for c in r.parsed["checks"] if c["name"] == "stp_status")
        assert stp["parsed"]["stp_enabled"] is False


class TestDriverMetadata:
    def test_vendor(self, driver):
        assert driver.vendor == "huawei"

    def test_device_type(self, driver):
        assert driver.device_type == "vrp_switch"

    def test_check_commands_count(self, driver):
        assert len(driver.get_check_commands()) == 18  # 9 基础 + 7 扩展 + ntp

    def test_unknown_check(self, driver):
        r = driver.parse_output("nonexistent", "some output")
        assert r.success is False
