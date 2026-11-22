"""九大类扩展检查测试(销号清单 #2)

华为 vrp/usg 与 H3C comware/s7506e/secpath 五驱动:
温度/光模块DDM/OSPF邻居/ARP规模/存储/配置一致性/重启原因。
fixtures 基于标准输出格式(待真机验证标记)。
"""
from __future__ import annotations

from pathlib import Path

import patrol.drivers  # noqa: F401
from patrol.analyzer.engine import RuleEngine
from patrol.drivers.registry import get_driver

FIX_HUAWEI = Path(__file__).parent.parent / "fixtures" / "huawei" / "vrp_switch"
FIX_H3C = Path(__file__).parent.parent / "fixtures" / "h3c" / "comware_switch"
RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"


def _fx(fix_dir: Path, name: str) -> str:
    return (fix_dir / f"{name}.txt").read_text(encoding="utf-8")


class TestCommandCoverage:
    def test_all_cli_drivers_have_extended_checks(self):
        """五个 CLI 驱动全部挂载 7 项扩展检查。"""
        for key in ("huawei/vrp_switch", "huawei/usg_firewall",
                    "h3c/comware_switch", "h3c/s7506e", "h3c/secpath_firewall"):
            names = {c.name for c in get_driver(*key.split("/")).get_check_commands()}
            for ext in ("temperature", "transceiver", "ospf_neighbor",
                        "arp_count", "storage", "config_diff", "reboot_reason"):
                assert ext in names, f"{key} 缺少 {ext}"


class TestHuaweiExtendedParsers:
    """华为解析器(vrp 与 usg 共用)。"""

    def test_all(self):
        d = get_driver("huawei", "vrp_switch")

        r = d.parse_output("temperature", _fx(FIX_HUAWEI, "display_temperature"))
        assert r.parsed["value"] == 38 and r.parsed["abnormal_count"] == 0

        r = d.parse_output("transceiver", _fx(FIX_HUAWEI, "display_transceiver_diagnosis"))
        assert r.parsed["total"] == 3
        assert r.parsed["abnormal_count"] == 1  # GE0/0/2 Rx -18.76 越下限

        r = d.parse_output("ospf_neighbor", _fx(FIX_HUAWEI, "display_ospf_peer"))
        assert r.parsed["total"] == 3 and r.parsed["full_count"] == 2
        assert r.parsed["abnormal_count"] == 1  # Init 邻居

        r = d.parse_output("arp_count", _fx(FIX_HUAWEI, "display_arp_all"))
        assert r.parsed["arp_count"] == 1247

        r = d.parse_output("storage", _fx(FIX_HUAWEI, "dir"))
        assert r.parsed["total_kb"] == 255872 and r.parsed["free_kb"] == 128932
        assert r.parsed["used_percent"] == 50

        r = d.parse_output("config_diff",
                           _fx(FIX_HUAWEI, "compare_configuration_same"))
        assert r.parsed["has_diff"] is False
        r = d.parse_output("config_diff",
                           _fx(FIX_HUAWEI, "compare_configuration_diff"))
        assert r.parsed["has_diff"] is True

        r = d.parse_output("reboot_reason", _fx(FIX_HUAWEI, "display_reboot_info"))
        assert r.parsed["reason"] == "power-on" and r.parsed["abnormal_count"] == 0
        r = d.parse_output("reboot_reason",
                           "The last reboot reason: system crash\n")
        assert r.parsed["abnormal_count"] == 1

    def test_usg_shares_parsers(self):
        d = get_driver("huawei", "usg_firewall")
        r = d.parse_output("ospf_neighbor", _fx(FIX_HUAWEI, "display_ospf_peer"))
        assert r.success and r.parsed["abnormal_count"] == 1


class TestH3CExtendedParsers:
    """H3C 三驱动:s7506e/comware 各自实现,secpath 继承 comware。"""

    def test_s7506e(self):
        d = get_driver("h3c", "s7506e")
        r = d.parse_output("temperature", _fx(FIX_H3C, "display_environment"))
        assert r.parsed["max_value"] == 41 and r.parsed["abnormal_count"] == 0
        r = d.parse_output("transceiver", _fx(FIX_H3C, "display_transceiver_diagnosis"))
        assert r.parsed["abnormal_count"] == 1
        r = d.parse_output("config_diff", _fx(FIX_H3C, "compare_configuration_diff"))
        assert r.parsed["has_diff"] is True

    def test_comware(self):
        d = get_driver("h3c", "comware_switch")
        r = d.parse_output("temperature", _fx(FIX_H3C, "display_environment"))
        assert r.parsed["values"] == [38, 41]
        r = d.parse_output("storage", _fx(FIX_H3C, "dir"))
        assert r.parsed["used_percent"] == 50
        r = d.parse_output("arp_count", _fx(FIX_H3C, "display_arp_all"))
        assert r.parsed["arp_count"] == 1247

    def test_secpath_inherits(self):
        d = get_driver("h3c", "secpath_firewall")
        r = d.parse_output("temperature", _fx(FIX_H3C, "display_environment"))
        assert r.success and r.parsed["abnormal_count"] == 0
        r = d.parse_output("ospf_neighbor", _fx(FIX_H3C, "display_ospf_peer"))
        assert r.parsed["abnormal_count"] == 1


class TestExtendedRules:
    """R006~R012 规则对新检查项的端到端判定。"""

    def _engine(self):
        return RuleEngine(RuleEngine.load_file(str(RULES)))

    def test_rule_judgements(self):
        engine = self._engine()
        d = get_driver("huawei", "vrp_switch")

        cases = [
            ("transceiver", "display_transceiver_diagnosis", "FAIL"),   # 1 越限
            ("ospf_neighbor", "display_ospf_peer", "FAIL"),             # 1 Init
            ("arp_count", "display_arp_all", "PASS"),                   # 1247<5000
            ("storage", "dir", "PASS"),                                 # 50%<80
            ("config_diff", "compare_configuration_diff", "FAIL"),      # 未保存
        ]
        for name, fixture, expect in cases:
            parsed = d.parse_output(name, _fx(FIX_HUAWEI, fixture))
            item = engine.evaluate(parsed, vendor="huawei", device_type="vrp_switch")
            assert item.status.value == expect, (
                f"{name}: 期望 {expect} 实际 {item.status.value} ({item.message})")

        same = d.parse_output("config_diff",
                              _fx(FIX_HUAWEI, "compare_configuration_same"))
        item = engine.evaluate(same, vendor="huawei", device_type="vrp_switch")
        assert item.status.value == "PASS"

    def test_rules_count(self):
        rules = RuleEngine.load_file(str(RULES))
        names = {r.check_name for r in rules}
        assert {"temperature", "transceiver", "ospf_neighbor", "arp_count",
                "storage", "config_diff", "reboot_reason"} <= names
