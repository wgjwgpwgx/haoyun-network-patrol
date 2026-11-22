"""Cisco IOS Driver 测试

fixtures 基于 IOS 15.x 标准输出格式编写(待真机验证标记)。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import patrol.drivers  # noqa: F401
from patrol.analyzer.engine import RuleEngine, expand_parsed
from patrol.cli import run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.cisco.driver import IOSDriver
from patrol.models import CheckStatus, DeviceAsset

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cisco" / "ios"
RULES_DEFAULT = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"
RULES_IOS = Path(__file__).parent.parent.parent / "config" / "rules" / "ios_switch.yaml"


@pytest.fixture
def driver() -> IOSDriver:
    return IOSDriver()


class TestRegistry:
    def test_registered_with_valid_netmiko_type(self):
        from patrol.drivers.registry import get_driver, list_drivers
        assert "cisco/ios_switch" in list_drivers()
        assert get_driver("cisco", "ios_switch").netmiko_device_type == "cisco_ios"


class TestParsers:
    def test_device_info(self, driver):
        raw = (FIXTURES / "show_version.txt").read_text(encoding="utf-8")
        r = driver.parse_output("device_info", raw)
        assert r.success
        assert r.parsed["model"] == "WS-C2960S-48TS-L"
        assert r.parsed["software_version"] == "15.2(2)E9"
        assert "30 weeks" in r.parsed["uptime"]
        assert r.parsed["serial_number"] == "FDO1651H0K4"

    def test_cpu_usage(self, driver):
        raw = (FIXTURES / "processes_cpu.txt").read_text(encoding="utf-8")
        r = driver.parse_output("cpu_usage", raw)
        assert r.parsed["usage_percent"] == 8
        assert r.parsed["usage_1m"] == 5

    def test_memory_usage(self, driver):
        raw = (FIXTURES / "memory_statistics.txt").read_text(encoding="utf-8")
        r = driver.parse_output("memory_usage", raw)
        assert r.parsed["total_bytes"] == 62197760
        assert r.parsed["usage_percent"] == 40

    def test_interface_status(self, driver):
        raw = (FIXTURES / "ip_interface_brief.txt").read_text(encoding="utf-8")
        r = driver.parse_output("interface_status", raw)
        assert r.parsed["total"] == 15
        assert r.parsed["admin_down_count"] == 1  # Gi0/3
        # Vlan20 与 Gi0/4:状态 up 但协议 down
        assert r.parsed["abnormal_count"] == 2

    def test_fan_status_detects_failure(self, driver):
        raw = (FIXTURES / "env_all.txt").read_text(encoding="utf-8")
        r = driver.parse_output("fan_status", raw)
        assert r.parsed["total"] == 2
        assert r.parsed["abnormal_count"] == 1  # Fan 2 Fail

    def test_power_status_all_ok(self, driver):
        raw = (FIXTURES / "env_all.txt").read_text(encoding="utf-8")
        r = driver.parse_output("power_status", raw)
        assert r.parsed["total"] == 2
        assert r.parsed["abnormal_count"] == 0

    def test_logbuffer_counts_severe(self, driver):
        raw = (FIXTURES / "logging.txt").read_text(encoding="utf-8")
        r = driver.parse_output("logbuffer", raw)
        # LINK-3, SPANTREE-2, ENV-3 = 3 条;SYS-5/LINEPROTO-5 不计
        assert r.parsed["error_count"] == 3

    def test_config_cur_nested_checks(self, driver):
        raw = (FIXTURES / "running_config.txt").read_text(encoding="utf-8")
        r = driver.parse_output("config_cur", raw)
        nested = {p.name: p for p in expand_parsed(r)}
        assert set(nested) == {
            "telnet_service", "snmp_community", "vty_auth", "stp_status"}
        # vty 5 15 transport input telnet ssh → telnet 开启
        assert nested["telnet_service"].parsed["telnet_enabled"] is True
        # public/private 团体字
        assert nested["snmp_community"].parsed["has_dangerous"] is True
        assert nested["snmp_community"].parsed["community_count"] == 2
        # aaa new-model 存在
        assert nested["vty_auth"].parsed["has_authentication"] is True
        # spanning-tree mode rapid-pvst
        assert nested["stp_status"].parsed["stp_enabled"] is True


CMD_TO_FILE = {
    "show version": "show_version.txt",
    "show processes cpu": "processes_cpu.txt",
    "show memory statistics": "memory_statistics.txt",
    "show ip interface brief": "ip_interface_brief.txt",
    "show env all": "env_all.txt",
    "show logging": "logging.txt",
    "show running-config": "running_config.txt",
}


def _mock_execute(command: str, timeout: int = 60) -> str:
    f = CMD_TO_FILE.get(command)
    return (FIXTURES / f).read_text(encoding="utf-8") if f else ""


class TestFullInspection:
    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    @patch.object(SSHCollector, "execute", side_effect=_mock_execute)
    def test_ios_full_patrol(self, mock_exec, mock_disc, mock_conn):
        asset = DeviceAsset(
            name="Cisco测试", host="192.0.2.20", vendor="cisco",
            device_type="ios_switch", username="u", password="p",
        )
        rules = RuleEngine.load_file(str(RULES_DEFAULT)) + \
            RuleEngine.load_file(str(RULES_IOS))
        report = run_inspection(asset, IOSDriver(), RuleEngine(rules))

        assert report.error is None
        assert report.model == "WS-C2960S-48TS-L"

        by_name = {i.name: i for i in report.check_items}
        assert by_name["cpu_usage"].status == CheckStatus.PASS  # 8%
        assert by_name["memory_usage"].status == CheckStatus.PASS  # 40%
        assert by_name["interface_status"].status == CheckStatus.FAIL  # 2 异常
        assert by_name["fan_status"].status == CheckStatus.FAIL  # Fan 2 Fail
        assert by_name["power_status"].status == CheckStatus.PASS
        assert by_name["logbuffer"].status == CheckStatus.FAIL  # 3 条严重日志
        assert by_name["telnet_service"].status == CheckStatus.FAIL  # telnet 开启
        assert by_name["snmp_community"].status == CheckStatus.FAIL  # 默认团体字
        assert by_name["vty_auth"].status == CheckStatus.PASS  # aaa new-model
        assert by_name["stp_status"].status == CheckStatus.PASS  # rapid-pvst
        assert mock_disc.called


class TestUnrecognizedOutputUnknown:
    """真机回显格式差异防御:识别不到内容时计数指标置 None,规则引擎判 UNKNOWN 而非误报 PASS"""

    GARBAGE = "Output from a different IOS train\nwith unknown layout"

    def test_env_unrecognized_sets_none(self, driver):
        for name in ("fan_status", "power_status"):
            r = driver.parse_output(name, self.GARBAGE)
            assert r.success
            assert r.parsed["total"] == 0
            assert r.parsed["abnormal_count"] is None

    def test_env_unrecognized_evaluates_unknown(self, driver):
        r = driver.parse_output("power_status", self.GARBAGE)
        engine = RuleEngine(RuleEngine.load_file(str(RULES_IOS)))
        item = engine.evaluate(r, vendor="cisco", device_type="ios_switch")
        assert item.status == CheckStatus.UNKNOWN

    def test_interface_unrecognized_sets_none(self, driver):
        r = driver.parse_output("interface_status", self.GARBAGE)
        assert r.parsed["abnormal_count"] is None
        engine = RuleEngine(RuleEngine.load_file(str(RULES_DEFAULT)))
        item = engine.evaluate(r, vendor="cisco", device_type="ios_switch")
        assert item.status == CheckStatus.UNKNOWN

    def test_logging_header_only_is_valid_zero(self, driver):
        raw = "Syslog logging: enabled (0 messages dropped, md5 checksum)"
        r = driver.parse_output("logbuffer", raw)
        assert r.parsed["error_count"] == 0

    def test_logging_unrecognized_sets_none(self, driver):
        r = driver.parse_output("logbuffer", self.GARBAGE)
        assert r.parsed["error_count"] is None
