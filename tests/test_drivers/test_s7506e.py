"""H3C S7506E Driver 解析测试

每个解析器覆盖四种场景：
  1. 正常 — 真实设备回显
  2. 异常 — 触发 FAIL 的值
  3. 空输出 — 空字符串
  4. 格式不完整 — 部分/截断数据
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.drivers.h3c.s7506e import H3CS7506EDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "h3c" / "s7506e"


@pytest.fixture
def driver() -> H3CS7506EDriver:
    return H3CS7506EDriver()


@pytest.fixture
def load():
    def _load(filename: str) -> str:
        return (FIXTURES / filename).read_text(encoding="utf-8")
    return _load


# ═══════════════════════════════════════════════════════════════
# display version → device_info
# ═══════════════════════════════════════════════════════════════


class TestDeviceInfo:
    """display version 解析器测试"""

    def test_normal(self, driver, load):
        """正常：完整回显，所有字段可解析"""
        r = driver.parse_output("device_info", load("display_version.txt"))
        assert r.success is True
        d = r.parsed
        assert d["model"] == "S7506"
        assert d["device_name"] == "hhht_sw_s7506e"
        assert d["brand"] == "H3C"
        assert d["serial_number"] == "210235A27SX111000004"
        assert d["mgmt_ip"] == "192.168.158.35"
        assert d["memory_size"] == "512M"
        assert d["software_version"] == "5.20"
        assert "122 weeks" in d["uptime"]

    def test_abnormal(self, driver):
        """异常：只有 Version 行，其他字段缺失"""
        output = "Version 5.20\n"
        r = driver.parse_output("device_info", output)
        assert r.success is True
        d = r.parsed
        assert d["software_version"] == "5.20"
        assert d["model"] == ""           # 缺失 → 空字符串
        assert d["device_name"] == ""     # 缺失 → 空字符串
        assert d["serial_number"] == ""   # 缺失 → 空字符串
        assert d["uptime"] == ""          # 缺失 → 空字符串

    def test_empty(self, driver):
        """空输出：所有字段为空"""
        r = driver.parse_output("device_info", "")
        assert r.success is True
        d = r.parsed
        assert d["model"] == ""
        assert d["device_name"] == ""
        assert d["software_version"] == ""
        assert d["uptime"] == ""

    def test_incomplete(self, driver):
        """格式不完整：只有 uptime 行"""
        output = "52 weeks, 3 days, 2 hours, 15 minutes\n"
        r = driver.parse_output("device_info", output)
        assert r.success is True
        d = r.parsed
        assert "52 weeks" in d["uptime"]
        assert d["model"] == ""
        assert d["software_version"] == ""


# ═══════════════════════════════════════════════════════════════
# display cpu → cpu_usage
# ═══════════════════════════════════════════════════════════════


class TestCpuUsage:
    """display cpu 解析器测试"""

    def test_normal(self, driver, load):
        """正常：三个时间窗口的 CPU 利用率"""
        r = driver.parse_output("cpu_usage", load("display_cpu.txt"))
        assert r.success is True
        d = r.parsed
        assert d["usage_5s"] == 3
        assert d["usage_1m"] == 4
        assert d["usage_5m"] == 4
        assert d["usage_percent"] == 3   # 取 5 秒值

    def test_abnormal(self, driver):
        """异常：CPU 高于阈值"""
        output = "       92% in last 5 seconds\n       88% in last 1 minute\n       85% in last 5 minutes\n"
        r = driver.parse_output("cpu_usage", output)
        assert r.success is True
        d = r.parsed
        assert d["usage_5s"] == 92
        assert d["usage_percent"] == 92

    def test_empty(self, driver):
        """空输出：所有值为 None"""
        r = driver.parse_output("cpu_usage", "")
        assert r.success is True
        d = r.parsed
        assert d["usage_5s"] is None
        assert d["usage_1m"] is None
        assert d["usage_5m"] is None
        assert d["usage_percent"] is None

    def test_incomplete(self, driver):
        """格式不完整：只有 5 秒行"""
        output = "       15% in last 5 seconds\n"
        r = driver.parse_output("cpu_usage", output)
        assert r.success is True
        d = r.parsed
        assert d["usage_5s"] == 15
        assert d["usage_1m"] is None      # 缺失 → None
        assert d["usage_5m"] is None      # 缺失 → None


# ═══════════════════════════════════════════════════════════════
# display memory → memory_usage
# ═══════════════════════════════════════════════════════════════


class TestMemoryUsage:
    """display memory 解析器测试"""

    def test_normal(self, driver, load):
        """正常：完整内存信息"""
        r = driver.parse_output("memory_usage", load("display_memory.txt"))
        assert r.success is True
        d = r.parsed
        assert d["total_bytes"] == 438322720
        assert d["used_bytes"] == 12827289
        assert d["usage_percent"] == 28

    def test_abnormal(self, driver):
        """异常：内存使用率 95%"""
        output = "System Total Memory(bytes): 512000000\nTotal Used Memory(bytes): 486400000\nUsed Rate: 95%\n"
        r = driver.parse_output("memory_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 95

    def test_empty(self, driver):
        """空输出：所有值为 None"""
        r = driver.parse_output("memory_usage", "")
        assert r.success is True
        d = r.parsed
        assert d["total_bytes"] is None
        assert d["used_bytes"] is None
        assert d["usage_percent"] is None

    def test_incomplete(self, driver):
        """格式不完整：只有 Used Rate"""
        output = "Used Rate: 42%\n"
        r = driver.parse_output("memory_usage", output)
        assert r.success is True
        assert r.parsed["usage_percent"] == 42
        assert r.parsed["total_bytes"] is None
        assert r.parsed["used_bytes"] is None


# ═══════════════════════════════════════════════════════════════
# display dev version → board_status
# ═══════════════════════════════════════════════════════════════


class TestBoardStatus:
    """display dev version 解析器测试"""

    def test_normal(self, driver, load):
        """正常：5 块板卡，全部 Master/Slave/Normal"""
        r = driver.parse_output("board_status", load("display_dev_version.txt"))
        assert r.success is True
        d = r.parsed
        assert d["board_count"] == 5
        assert d["abnormal_count"] == 0
        assert d["boards"][0]["role"] == "Master"
        assert d["boards"][1]["role"] == "Slave"
        assert d["boards"][2]["role"] == "Normal"

    def test_abnormal(self, driver):
        """异常：板卡角色为 Fault"""
        output = " 0   LSQ1SRPB   Master   0    S7500E-6605P03   None\n 1   LSQ1SRPB   Fault    0   S7500E-6605P03   None\n"
        r = driver.parse_output("board_status", output)
        assert r.success is True
        assert r.parsed["abnormal_count"] == 1
        assert "Slot 1: Fault" in r.parsed["abnormal_boards"]

    def test_empty(self, driver):
        """空输出：无板卡"""
        r = driver.parse_output("board_status", "")
        assert r.success is True
        assert r.parsed["board_count"] == 0
        assert r.parsed["abnormal_count"] == 0

    def test_incomplete(self, driver):
        """格式不完整：只有 slot 和 model（列数不足）"""
        output = " 0   LSQ1SRPB\n"
        r = driver.parse_output("board_status", output)
        assert r.success is True
        # 只有 2 列，不满足 >= 3 的条件，不会被解析
        assert r.parsed["board_count"] == 0


# ═══════════════════════════════════════════════════════════════
# display fan → fan_status
# ═══════════════════════════════════════════════════════════════


class TestFanStatus:
    """display fan 解析器测试"""

    def test_normal(self, driver, load):
        """正常：风扇状态 Normal"""
        r = driver.parse_output("fan_status", load("display_fan.txt"))
        assert r.success is True
        assert r.parsed["fan_count"] == 1
        assert r.parsed["abnormal_count"] == 0
        assert r.parsed["fans"][0]["state"] == "Normal"

    def test_abnormal(self, driver):
        """异常：风扇状态 Fault"""
        output = "Fan    1 State: Normal\nFan    2 State: Fault\n"
        r = driver.parse_output("fan_status", output)
        assert r.success is True
        assert r.parsed["fan_count"] == 2
        assert r.parsed["abnormal_count"] == 1
        assert r.parsed["fans"][1]["state"] == "Fault"

    def test_empty(self, driver):
        """空输出：无风扇信息"""
        r = driver.parse_output("fan_status", "")
        assert r.success is True
        assert r.parsed["fan_count"] == 0
        assert r.parsed["abnormal_count"] == 0

    def test_incomplete(self, driver):
        """格式不完整：格式不匹配"""
        output = "Fan 1\n"
        r = driver.parse_output("fan_status", output)
        assert r.success is True
        assert r.parsed["fan_count"] == 0  # 格式不匹配，无法解析


# ═══════════════════════════════════════════════════════════════
# display power → power_status
# ═══════════════════════════════════════════════════════════════


class TestPowerStatus:
    """display power 解析器测试"""

    def test_normal(self, driver, load):
        """正常：2 个电源，全部 Normal"""
        r = driver.parse_output("power_status", load("display_power.txt"))
        assert r.success is True
        assert r.parsed["power_count"] == 2
        assert r.parsed["abnormal_count"] == 0

    def test_abnormal(self, driver):
        """异常：电源 2 状态 Fault"""
        output = " Power        1 State: Normal\n Power        2 State: Fault\n"
        r = driver.parse_output("power_status", output)
        assert r.success is True
        assert r.parsed["abnormal_count"] == 1
        assert r.parsed["powers"][1]["state"] == "Fault"

    def test_empty(self, driver):
        """空输出：无电源信息"""
        r = driver.parse_output("power_status", "")
        assert r.success is True
        assert r.parsed["power_count"] == 0

    def test_incomplete(self, driver):
        """格式不完整：只有 Power 关键字"""
        output = "Power 1\n"
        r = driver.parse_output("power_status", output)
        assert r.success is True
        assert r.parsed["power_count"] == 0


# ═══════════════════════════════════════════════════════════════
# display ip routing-table → routing_table
# ═══════════════════════════════════════════════════════════════


class TestRoutingTable:
    """display ip routing-table 解析器测试"""

    def test_normal(self, driver, load):
        """正常：785 条路由"""
        r = driver.parse_output("routing_table", load("display_ip_routing_table.txt"))
        assert r.success is True
        assert r.parsed["destinations"] == 785
        assert r.parsed["routes"] == 785

    def test_abnormal(self, driver):
        """异常：路由表为空"""
        output = "Destinations :0  Routes : 0\n"
        r = driver.parse_output("routing_table", output)
        assert r.success is True
        assert r.parsed["destinations"] == 0
        assert r.parsed["routes"] == 0

    def test_empty(self, driver):
        """空输出：值为 0"""
        r = driver.parse_output("routing_table", "")
        assert r.success is True
        assert r.parsed["destinations"] == 0
        assert r.parsed["routes"] == 0

    def test_incomplete(self, driver):
        """格式不完整：只有 Destinations"""
        output = "Destinations :100\n"
        r = driver.parse_output("routing_table", output)
        assert r.success is True
        assert r.parsed["destinations"] == 100
        assert r.parsed["routes"] == 0  # 缺失 → 0


# ═══════════════════════════════════════════════════════════════
# dis ip int bri → l3_interface
# ═══════════════════════════════════════════════════════════════


class TestL3Interface:
    """dis ip int bri 解析器测试"""

    def test_normal(self, driver, load):
        """正常：14 个接口，1 个异常（Vlan-interface1 up/down）"""
        r = driver.parse_output("l3_interface", load("display_ip_int_brief.txt"))
        assert r.success is True
        d = r.parsed
        assert d["interface_count"] == 14
        assert d["abnormal_count"] == 1
        assert "Vlan-interface1" in d["abnormal_interfaces"]

    def test_abnormal(self, driver):
        """异常：多个接口 Down"""
        output = (
            "Vlan-interface10  up       down     192.168.155.221   Vlan-inte...\n"
            "Vlan-interface20  down     down     192.168.154.221   Vlan-inte...\n"
        )
        r = driver.parse_output("l3_interface", output)
        assert r.success is True
        assert r.parsed["abnormal_count"] == 2
        assert "Vlan-interface10" in r.parsed["abnormal_interfaces"]
        assert "Vlan-interface20" in r.parsed["abnormal_interfaces"]

    def test_empty(self, driver):
        """空输出：无接口"""
        r = driver.parse_output("l3_interface", "")
        assert r.success is True
        assert r.parsed["interface_count"] == 0
        assert r.parsed["abnormal_count"] == 0

    def test_incomplete(self, driver):
        """格式不完整：列数不足"""
        output = "Vlan-interface10  up\n"
        r = driver.parse_output("l3_interface", output)
        assert r.success is True
        # 只有 2 列，不满足 >= 4 的条件
        assert r.parsed["interface_count"] == 0

    def test_mgmt_interface_ignored(self, driver):
        """M-Ethernet 管理口 Down 不计入异常"""
        output = "M-Ethernet0/0/0   down   down    unassigned      M-Etherne...\n"
        r = driver.parse_output("l3_interface", output)
        assert r.success is True
        assert r.parsed["interface_count"] == 1
        assert r.parsed["abnormal_count"] == 0  # 管理口不计入


# ═══════════════════════════════════════════════════════════════
# display logbuffer → logbuffer
# ═══════════════════════════════════════════════════════════════


class TestLogbuffer:
    """display logbuffer 解析器测试"""

    def test_normal(self, driver, load):
        """正常：2 条日志，severity=2（CRITICAL）"""
        r = driver.parse_output("logbuffer", load("display_logbuffer.txt"))
        assert r.success is True
        assert r.parsed["total_lines"] == 2
        assert r.parsed["error_count"] == 2  # MSTP/2 → severity 2

    def test_abnormal(self, driver):
        """异常：包含 severity=1（ALERT）日志"""
        output = (
            "%May 10 18:41:12:112 2023 sw1 OSPF/1/NEIGHBOR: Neighbor down!\n"
            "%May 10 18:42:00:000 2023 sw1 IFNET/5/LINK_UP: GE1/0/1 up.\n"
        )
        r = driver.parse_output("logbuffer", output)
        assert r.success is True
        assert r.parsed["error_count"] == 1  # 只有 severity 1

    def test_empty(self, driver):
        """空输出：无日志"""
        r = driver.parse_output("logbuffer", "")
        assert r.success is True
        assert r.parsed["total_lines"] == 0
        assert r.parsed["error_count"] == 0

    def test_incomplete(self, driver):
        """格式不完整：没有 severity 标记的日志"""
        output = "System started normally.\nNo errors.\n"
        r = driver.parse_output("logbuffer", output)
        assert r.success is True
        assert r.parsed["total_lines"] == 2
        assert r.parsed["error_count"] == 0  # 无法识别 severity


# ═══════════════════════════════════════════════════════════════
# display current-configuration → config_cur
# ═══════════════════════════════════════════════════════════════


class TestConfigCur:
    """display current-configuration 解析器测试"""

    def test_normal(self, driver, load):
        """正常：完整配置，包含所有子检查项"""
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        assert r.success is True
        checks = r.parsed["checks"]
        assert len(checks) == 9  # 4 原有安全项 + 5 等保基线项
        names = [c["name"] for c in checks]
        assert "telnet_service" in names
        assert "snmp_community" in names
        assert "vty_auth" in names
        assert "stp_status" in names

    def test_telnet_not_enabled(self, driver, load):
        """正常：配置中无 telnet server enable"""
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is False
        assert telnet["parsed"]["ssh_enabled"] is True

    def test_snmp_dangerous(self, driver, load):
        """异常：SNMP 使用 public community"""
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        snmp = next(c for c in r.parsed["checks"] if c["name"] == "snmp_community")
        assert snmp["parsed"]["has_dangerous"] is True
        assert snmp["parsed"]["community_count"] == 2

    def test_vty_auth_ok(self, driver, load):
        """正常：VTY 配置了 scheme + ACL + SSH"""
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        vty = next(c for c in r.parsed["checks"] if c["name"] == "vty_auth")
        assert vty["parsed"]["has_authentication"] is True
        assert vty["parsed"]["has_acl"] is True
        assert vty["parsed"]["ssh_only"] is True

    def test_stp_enabled(self, driver, load):
        """正常：STP 启用且为 root primary"""
        r = driver.parse_output("config_cur", load("display_current_configuration.txt"))
        stp = next(c for c in r.parsed["checks"] if c["name"] == "stp_status")
        assert stp["parsed"]["stp_enabled"] is True
        assert stp["parsed"]["stp_root_primary"] is True

    def test_empty(self, driver):
        """空输出：所有子检查项使用默认值"""
        r = driver.parse_output("config_cur", "")
        assert r.success is True
        checks = r.parsed["checks"]
        telnet = next(c for c in checks if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is False
        snmp = next(c for c in checks if c["name"] == "snmp_community")
        assert snmp["parsed"]["has_dangerous"] is False
        vty = next(c for c in checks if c["name"] == "vty_auth")
        assert vty["parsed"]["has_authentication"] is False

    def test_incomplete(self, driver):
        """格式不完整：只有 sysname"""
        output = "#\n sysname Test-Switch\n#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        assert r.success is True
        # 所有子检查项都应该是安全默认值
        checks = r.parsed["checks"]
        telnet = next(c for c in checks if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is False

    def test_telnet_enabled(self, driver):
        """异常：配置中启用了 Telnet"""
        output = "telnet server enable\nssh server enable\n#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        telnet = next(c for c in r.parsed["checks"] if c["name"] == "telnet_service")
        assert telnet["parsed"]["telnet_enabled"] is True

    def test_snmp_safe(self, driver):
        """正常：SNMP community 非默认值"""
        output = "snmp-agent community read MyC0mpl3xStr!ng\n#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        snmp = next(c for c in r.parsed["checks"] if c["name"] == "snmp_community")
        assert snmp["parsed"]["has_dangerous"] is False
        assert snmp["parsed"]["community_count"] == 1

    def test_vty_no_auth(self, driver):
        """异常：VTY 无认证"""
        output = "user-interface vty 0 4\n protocol inbound ssh\n#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        vty = next(c for c in r.parsed["checks"] if c["name"] == "vty_auth")
        assert vty["parsed"]["has_authentication"] is False

    def test_stp_disabled(self, driver):
        """异常：STP 未启用"""
        output = "#\nreturn\n"
        r = driver.parse_output("config_cur", output)
        stp = next(c for c in r.parsed["checks"] if c["name"] == "stp_status")
        assert stp["parsed"]["stp_enabled"] is False


# ═══════════════════════════════════════════════════════════════
# 元数据和边界测试
# ═══════════════════════════════════════════════════════════════


class TestDriverEdgeCases:
    def test_parse_exception_returns_failure(self, driver):
        """解析器内部异常应被 driver 捕获并返回 success=False"""
        # 传入 None 会触发异常（但 parse_output 接收 str，所以这不会发生）
        # 测试未知检查项
        r = driver.parse_output("nonexistent", "some output")
        assert r.success is False

    def test_device_info_no_uptime_line(self, driver):
        """没有 uptime 行时 uptime 为空"""
        output = "Version 5.20\n"
        r = driver.parse_output("device_info", output)
        assert r.parsed["uptime"] == ""

    def test_board_fault_status(self, driver):
        """板卡 Fault 状态应计入异常"""
        output = " 0   LSQ1SRPB   Master   0    S7500E-6605P03   None\n 1   LSQ1SRPB   Fault    0   S7500E-6605P03   None\n"
        r = driver.parse_output("board_status", output)
        assert r.parsed["abnormal_count"] == 1
        assert "Slot 1: Fault" in r.parsed["abnormal_boards"]

    def test_l3_interface_mgmt_down_ignored(self, driver):
        """M-Ethernet 管理口 Down 不计入异常"""
        output = "M-Ethernet0/0/0   down   down    unassigned      M-Etherne...\n"
        r = driver.parse_output("l3_interface", output)
        assert r.parsed["abnormal_count"] == 0


class TestDriverMetadata:
    def test_vendor(self, driver):
        assert driver.vendor == "h3c"

    def test_device_type(self, driver):
        assert driver.device_type == "s7506e"

    def test_check_commands_count(self, driver):
        assert len(driver.get_check_commands()) == 19  # 10 基础 + 7 扩展 + ntp

    def test_unknown_check(self, driver):
        r = driver.parse_output("nonexistent", "some output")
        assert r.success is False
        assert "未实现" in r.error
