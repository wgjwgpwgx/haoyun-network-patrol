"""Juniper Junos Driver 测试

fixtures 基于 Junos 21.x 标准输出格式编写(待真机验证标记)。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import patrol.drivers  # noqa: F401
from patrol.analyzer.engine import RuleEngine, expand_parsed
from patrol.cli import run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.juniper.driver import JunosDriver
from patrol.models import CheckStatus, DeviceAsset

FIXTURES = Path(__file__).parent.parent / "fixtures" / "juniper" / "junos"
RULES_DEFAULT = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"
RULES_JUNOS = Path(__file__).parent.parent.parent / "config" / "rules" / "junos.yaml"


@pytest.fixture
def driver() -> JunosDriver:
    return JunosDriver()


class TestRegistry:
    def test_registered_with_valid_netmiko_type(self):
        from patrol.drivers.registry import get_driver, list_drivers
        assert "juniper/junos" in list_drivers()
        assert get_driver("juniper", "junos").netmiko_device_type == "juniper_junos"


class TestParsers:
    def test_device_info(self, driver):
        raw = (FIXTURES / "show_version.txt").read_text(encoding="utf-8")
        r = driver.parse_output("device_info", raw)
        assert r.success
        assert r.parsed["model"] == "ex4300-48t"
        assert r.parsed["software_version"] == "21.4R3-S5.2"
        assert r.parsed["device_name"] == "sw-core-01"

    def test_cpu_usage(self, driver):
        raw = (FIXTURES / "chassis_routing_engine.txt").read_text(encoding="utf-8")
        r = driver.parse_output("cpu_usage", raw)
        assert r.success
        assert r.parsed["idle"] == 96
        assert r.parsed["usage_percent"] == 4

    def test_memory_usage(self, driver):
        raw = (FIXTURES / "chassis_routing_engine.txt").read_text(encoding="utf-8")
        r = driver.parse_output("memory_usage", raw)
        assert r.parsed["usage_percent"] == 22

    def test_interface_status(self, driver):
        raw = (FIXTURES / "interfaces_terse.txt").read_text(encoding="utf-8")
        r = driver.parse_output("interface_status", raw)
        assert r.parsed["total"] == 39
        # ge-0/0/2, ge-0/0/7, me0:管理 Up 但链路 Down
        assert r.parsed["abnormal_count"] == 3
        assert r.parsed["admin_down_count"] == 2  # ge-0/0/3, ge-0/0/4

    def test_fan_status_detects_failure(self, driver):
        raw = (FIXTURES / "chassis_environment.txt").read_text(encoding="utf-8")
        r = driver.parse_output("fan_status", raw)
        assert r.parsed["total"] == 3
        assert r.parsed["abnormal_count"] == 1  # Fan Tray 2 Failed

    def test_power_status_all_ok(self, driver):
        raw = (FIXTURES / "chassis_environment.txt").read_text(encoding="utf-8")
        r = driver.parse_output("power_status", raw)
        assert r.parsed["total"] == 2
        assert r.parsed["abnormal_count"] == 0

    def test_system_alarms(self, driver):
        raw = (FIXTURES / "system_alarms.txt").read_text(encoding="utf-8")
        r = driver.parse_output("system_alarms", raw)
        assert r.parsed["active_alarms"] == 2
        assert r.parsed["major_count"] == 1

    def test_config_services_nested(self, driver):
        raw = (FIXTURES / "config_system_services.txt").read_text(encoding="utf-8")
        r = driver.parse_output("config_cur", raw)
        nested = expand_parsed(r)
        assert len(nested) == 1
        assert nested[0].name == "telnet_service"
        assert nested[0].parsed["telnet_enabled"] is True
        assert nested[0].parsed["ssh_enabled"] is True

    def test_unknown_check_name(self, driver):
        r = driver.parse_output("nonexistent", "x")
        assert not r.success
        assert "未实现" in r.error


class TestUnrecognizedOutputUnknown:
    """真机回显格式差异防御:识别不到内容时计数指标置 None,规则引擎判 UNKNOWN 而非误报 PASS"""

    GARBAGE = "Some unexpected output\nfrom a different Junos train\n"

    def test_env_unrecognized_sets_none(self, driver):
        for name in ("fan_status", "power_status"):
            r = driver.parse_output(name, self.GARBAGE)
            assert r.success
            assert r.parsed["total"] == 0
            assert r.parsed["abnormal_count"] is None

    def test_env_unrecognized_evaluates_unknown(self, driver):
        r = driver.parse_output("fan_status", self.GARBAGE)
        engine = RuleEngine(RuleEngine.load_file(str(RULES_JUNOS)))
        item = engine.evaluate(r, vendor="juniper", device_type="junos")
        assert item.status == CheckStatus.UNKNOWN

    def test_interface_unrecognized_sets_none(self, driver):
        r = driver.parse_output("interface_status", self.GARBAGE)
        assert r.parsed["abnormal_count"] is None
        engine = RuleEngine(RuleEngine.load_file(str(RULES_DEFAULT)))
        item = engine.evaluate(r, vendor="juniper", device_type="junos")
        assert item.status == CheckStatus.UNKNOWN

    def test_alarms_no_alarm_line_is_valid_zero(self, driver):
        r = driver.parse_output("system_alarms", "No alarms currently active\n")
        assert r.parsed["major_count"] == 0

    def test_alarms_unrecognized_sets_none(self, driver):
        r = driver.parse_output("system_alarms", self.GARBAGE)
        assert r.parsed["major_count"] is None

    def test_alarms_count_without_detail_sets_none(self, driver):
        raw = "3 alarms currently active\nAlarm time  Class  Description\n???"
        r = driver.parse_output("system_alarms", raw)
        assert r.parsed["active_alarms"] == 3
        assert r.parsed["major_count"] is None


CMD_TO_FILE = {
    "show version": "show_version.txt",
    "show chassis routing-engine": "chassis_routing_engine.txt",
    "show interfaces terse": "interfaces_terse.txt",
    "show chassis environment": "chassis_environment.txt",
    "show system alarms": "system_alarms.txt",
    "show configuration system services": "config_system_services.txt",
}


def _mock_execute(command: str, timeout: int = 60) -> str:
    f = CMD_TO_FILE.get(command)
    return (FIXTURES / f).read_text(encoding="utf-8") if f else ""


class TestFullInspection:
    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    @patch.object(SSHCollector, "execute", side_effect=_mock_execute)
    def test_junos_full_patrol(self, mock_exec, mock_disc, mock_conn):
        asset = DeviceAsset(
            name="Juniper测试", host="192.0.2.10", vendor="juniper",
            device_type="junos", username="u", password="p",
        )
        rules = RuleEngine.load_file(str(RULES_DEFAULT)) + \
            RuleEngine.load_file(str(RULES_JUNOS))
        report = run_inspection(asset, JunosDriver(), RuleEngine(rules))

        assert report.error is None
        assert report.model == "ex4300-48t"
        assert report.software_version == "21.4R3-S5.2"

        by_name = {i.name: i for i in report.check_items}
        # CPU 4% / 内存 22% → PASS
        assert by_name["cpu_usage"].status == CheckStatus.PASS
        assert by_name["memory_usage"].status == CheckStatus.PASS
        # 3 个管理Up链路Down接口 → FAIL
        assert by_name["interface_status"].status == CheckStatus.FAIL
        # Fan Tray 2 Failed → FAIL
        assert by_name["fan_status"].status == CheckStatus.FAIL
        # 电源全部 OK → PASS
        assert by_name["power_status"].status == CheckStatus.PASS
        # 1 条 Major 告警 → FAIL
        assert by_name["system_alarms"].status == CheckStatus.FAIL
        # telnet; 配置存在 → FAIL
        assert by_name["telnet_service"].status == CheckStatus.FAIL
        assert mock_disc.called
