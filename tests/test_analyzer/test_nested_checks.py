"""嵌套检查展开与规则匹配测试(问题 002 回归)

背景:parse_config_cur 返回 {"checks": [...]} 嵌套结构,规则引擎按检查名
逐项求值,telnet/snmp/vty/stp 四类安全规则因缺少展开步骤而从未生效。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.analyzer.engine import Rule, RuleEngine, expand_parsed
from patrol.drivers.base import ParsedResult
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "huawei" / "vrp_switch"
RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "vrp_switch.yaml"


class TestExpandParsed:
    def test_plain_result_passthrough(self):
        pr = ParsedResult(name="cpu_usage", category="CPU", command="display cpu",
                          raw_output="...", parsed={"usage_percent": 12})
        assert expand_parsed(pr) == [pr]

    def test_failed_parse_not_expanded(self):
        pr = ParsedResult(name="config_cur", category="配置", command="display cur",
                          raw_output="", parsed={"checks": [{"name": "x"}]},
                          success=False, error="boom")
        assert expand_parsed(pr) == [pr]

    def test_nested_expanded(self):
        pr = ParsedResult(
            name="config_cur", category="配置检查", command="display current-configuration",
            raw_output="config...",
            parsed={"checks": [
                {"name": "telnet_service", "category": "安全", "parsed": {"telnet_enabled": True}},
                {"name": "stp_status", "parsed": {"stp_enabled": False}},
                {"bad": "no-name-entry"},  # 无 name 的条目应被跳过
            ]},
        )
        out = expand_parsed(pr)
        assert [r.name for r in out] == ["telnet_service", "stp_status"]
        assert out[0].parsed == {"telnet_enabled": True}
        assert out[0].category == "安全"
        assert out[1].category == "配置检查"  # 缺省继承外层
        assert out[0].raw_output == "config..."  # 保留原始回显作为证据

    def test_empty_checks_falls_back(self):
        pr = ParsedResult(name="config_cur", category="配置", command="c",
                          raw_output="", parsed={"checks": []})
        assert expand_parsed(pr) == [pr]


class TestNestedRulesTakeEffect:
    """端到端:真实配置回显 → 展开 → 12 条安全规则真正参与判定。"""

    @pytest.fixture
    def config_parsed(self) -> ParsedResult:
        raw = (FIXTURES / "display_current_configuration.txt").read_text(encoding="utf-8")
        return HuaweiVRPSwitchDriver().parse_output("config_cur", raw)

    def test_all_four_security_checks_judged(self, config_parsed):
        engine = RuleEngine(RuleEngine.load_file(str(RULES)))
        items = [engine.evaluate(pr, vendor="huawei", device_type="vrp_switch")
                 for pr in expand_parsed(config_parsed)]

        judged = {i.name: i for i in items}
        for name in ("telnet_service", "snmp_community", "vty_auth", "stp_status"):
            assert name in judged, f"嵌套检查 {name} 未进入判定"
            item = judged[name]
            assert item.status.value in ("PASS", "FAIL"), (
                f"{name} 判定结果异常: {item.status.value} ({item.message})"
            )
            assert "未找到适用规则" not in item.message

    def test_telnet_rule_semantics(self):
        """规则语义:telnet 启用 = 异常(FAIL)。"""
        engine = RuleEngine([Rule(
            id="T900", name="Telnet 已启用", description="",
            severity="warning", vendors=["*"], device_types=["*"],
            check_name="telnet_service", metric="telnet_enabled",
            operator="true", value=None, suggestion="关闭 Telnet",
        )])
        pr = ParsedResult(
            name="telnet_service", category="安全", command="display cur",
            raw_output="", parsed={"telnet_enabled": True},
        )
        item = engine.evaluate(pr)
        assert item.status.value == "FAIL"
        pr_off = ParsedResult(
            name="telnet_service", category="安全", command="display cur",
            raw_output="", parsed={"telnet_enabled": False})
        assert engine.evaluate(pr_off).status.value == "PASS"
