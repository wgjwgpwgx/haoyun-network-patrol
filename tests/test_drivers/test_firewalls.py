"""华为 USG / H3C SecPath 防火墙 Driver 测试

复用 VRP/Comware 解析器的部分直接使用既有 fixtures;
会话表与风扇/电源(SecPath)使用本目录新增 fixtures。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import patrol.drivers  # noqa: F401
from patrol.analyzer.engine import RuleEngine
from patrol.cli import run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.h3c.secpath_firewall import H3CSecPathFirewallDriver
from patrol.drivers.huawei.usg_firewall import HuaweiUSGFirewallDriver
from patrol.models import CheckStatus, DeviceAsset

TESTS = Path(__file__).parent.parent
RULES = Path(__file__).parent.parent.parent / "config" / "rules"


class TestRegistry:
    def test_both_firewalls_registered(self):
        from patrol.drivers.registry import list_drivers
        drivers = list_drivers()
        assert "huawei/usg_firewall" in drivers
        assert "h3c/secpath_firewall" in drivers

    def test_netmiko_types(self):
        assert HuaweiUSGFirewallDriver().netmiko_device_type == "huawei"
        assert H3CSecPathFirewallDriver().netmiko_device_type == "hp_comware"


class TestUSG:
    def test_session_table_parser(self):
        raw = (TESTS / "fixtures" / "huawei" / "usg_firewall" /
               "session_table_summary.txt").read_text(encoding="utf-8")
        r = HuaweiUSGFirewallDriver().parse_output("session_table", raw)
        assert r.success
        assert r.parsed["session_count"] == 35800

    def test_reuses_vrp_parsers(self):
        # CPU 解析复用 VRP:用华为交换机 fixture 验证
        raw = (TESTS / "fixtures" / "huawei" / "vrp_switch" /
               "display_cpu_usage.txt").read_text(encoding="utf-8")
        r = HuaweiUSGFirewallDriver().parse_output("cpu_usage", raw)
        assert r.success
        assert r.parsed["usage_percent"] is not None

    def test_full_patrol(self):
        vrp_fix = TESTS / "fixtures" / "huawei" / "vrp_switch"
        usg_fix = TESTS / "fixtures" / "huawei" / "usg_firewall"
        cmd_to_file = {
            "display version": vrp_fix / "display_version.txt",
            "display cpu-usage": vrp_fix / "display_cpu_usage.txt",
            "display memory-usage": vrp_fix / "display_memory_usage.txt",
            "display interface brief": vrp_fix / "display_interface_brief.txt",
            "display fan": vrp_fix / "display_fan.txt",
            "display power": vrp_fix / "display_power.txt",
            "display firewall session table summary":
                usg_fix / "session_table_summary.txt",
            "display current-configuration":
                vrp_fix / "display_current_configuration.txt",
        }

        def mock_exec(command, timeout=60):
            p = cmd_to_file.get(command)
            return p.read_text(encoding="utf-8") if p and p.exists() else ""

        asset = DeviceAsset(name="USG测试", host="192.0.2.30", vendor="huawei",
                            device_type="usg_firewall", username="u", password="p")
        rules = RuleEngine.load_file(str(RULES / "default.yaml")) + \
            RuleEngine.load_file(str(RULES / "usg_firewall.yaml"))

        with patch.object(SSHCollector, "connect", return_value=None), \
             patch.object(SSHCollector, "disconnect", return_value=None), \
             patch.object(SSHCollector, "execute", side_effect=mock_exec):
            report = run_inspection(asset, HuaweiUSGFirewallDriver(),
                                    RuleEngine(rules))

        assert report.error is None
        by_name = {i.name: i for i in report.check_items}
        # 35800 < 500000 → 会话规则 PASS
        assert by_name["session_table"].status == CheckStatus.PASS


class TestSecPath:
    def test_session_table_parser(self):
        raw = (TESTS / "fixtures" / "h3c" / "secpath_firewall" /
               "session_table_summary.txt").read_text(encoding="utf-8")
        r = H3CSecPathFirewallDriver().parse_output("session_table", raw)
        assert r.success
        assert r.parsed["session_count"] == 24568  # 取第一个 Slot

    def test_fan_power_simple_status(self):
        d = H3CSecPathFirewallDriver()
        raw = (TESTS / "fixtures" / "h3c" / "secpath_firewall" /
               "fan.txt").read_text(encoding="utf-8")
        r = d.parse_output("fan_status", raw)
        assert r.success
        assert r.parsed["abnormal_count"] == 0
        assert r.parsed["total"] == 2

    def test_reuses_comware_parsers(self):
        raw = (TESTS / "fixtures" / "h3c" / "comware_switch" /
               "display_cpu_usage.txt").read_text(encoding="utf-8")
        r = H3CSecPathFirewallDriver().parse_output("cpu_usage", raw)
        assert r.success
        assert r.parsed["usage_percent"] is not None

    def test_full_patrol(self):
        h3c_fix = TESTS / "fixtures" / "h3c" / "comware_switch"
        fw_fix = TESTS / "fixtures" / "h3c" / "secpath_firewall"
        cmd_to_file = {
            "display version": h3c_fix / "display_version.txt",
            "display cpu-usage": h3c_fix / "display_cpu_usage.txt",
            "display memory": h3c_fix / "display_memory.txt",
            "display interface brief": h3c_fix / "display_interface_brief.txt",
            "display interface": h3c_fix / "display_interface.txt",
            "display device": fw_fix / "fan.txt",
            "display power": fw_fix / "power.txt",
            "display session table summary": fw_fix / "session_table_summary.txt",
        }

        def mock_exec(command, timeout=60):
            p = cmd_to_file.get(command)
            return p.read_text(encoding="utf-8") if p and p.exists() else ""

        asset = DeviceAsset(name="SecPath测试", host="192.0.2.40", vendor="h3c",
                            device_type="secpath_firewall", username="u", password="p")
        rules = RuleEngine.load_file(str(RULES / "default.yaml")) + \
            RuleEngine.load_file(str(RULES / "secpath_firewall.yaml"))

        with patch.object(SSHCollector, "connect", return_value=None), \
             patch.object(SSHCollector, "disconnect", return_value=None), \
             patch.object(SSHCollector, "execute", side_effect=mock_exec):
            report = run_inspection(asset, H3CSecPathFirewallDriver(),
                                    RuleEngine(rules))

        assert report.error is None
        by_name = {i.name: i for i in report.check_items}
        assert by_name["session_table"].status == CheckStatus.PASS
        assert by_name["fan_status"].status == CheckStatus.PASS


class TestUnrecognizedOutputUnknown:
    """真机回显格式差异防御:识别不到状态词时置 None,规则引擎判 UNKNOWN 而非误报 PASS"""

    GARBAGE = "Slot\tType\tState\tMore detail\n1\tNONE\tEMPTY"

    def test_secpath_fan_unrecognized_sets_none(self):
        d = H3CSecPathFirewallDriver()
        r = d.parse_output("fan_status", self.GARBAGE)
        assert r.success
        assert r.parsed["total"] == 0
        assert r.parsed["abnormal_count"] is None

    def test_secpath_fan_unrecognized_evaluates_unknown(self):
        d = H3CSecPathFirewallDriver()
        r = d.parse_output("power_status", self.GARBAGE)
        engine = RuleEngine(RuleEngine.load_file(str(RULES / "secpath_firewall.yaml")))
        item = engine.evaluate(r, vendor="h3c", device_type="secpath_firewall")
        assert item.status == CheckStatus.UNKNOWN
