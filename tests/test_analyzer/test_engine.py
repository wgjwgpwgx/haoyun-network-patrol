"""规则引擎单元测试"""
from __future__ import annotations

import pytest

from patrol.analyzer.engine import RuleEngine, _evaluate_condition, _resolve_metric
from patrol.drivers.base import ParsedResult
from patrol.drivers.h3c.comware_switch import H3CComwareSwitchDriver
from patrol.models import CheckStatus


# ── 辅助函数测试 ────────────────────────────────────────────────


class TestResolveMetric:
    def test_simple_path(self):
        data = {"usage_percent": 12}
        assert _resolve_metric(data, "usage_percent") == 12

    def test_nested_path(self):
        data = {"details": {"abnormal_count": 3}}
        assert _resolve_metric(data, "details.abnormal_count") == 3

    def test_missing_key(self):
        data = {}
        assert _resolve_metric(data, "missing") is None

    def test_missing_intermediate(self):
        data = {}
        assert _resolve_metric(data, "details.usage_percent") is None

    def test_boolean_value(self):
        data = {"telnet_enabled": True}
        assert _resolve_metric(data, "telnet_enabled") is True


class TestEvaluateCondition:
    def test_gt_pass(self):
        assert _evaluate_condition(12, "gt", 80) is False  # 12 > 80 is False

    def test_gt_fail(self):
        assert _evaluate_condition(95, "gt", 80) is True  # 95 > 80 is True

    def test_lt_pass(self):
        assert _evaluate_condition(50, "lt", 80) is True

    def test_lt_fail(self):
        assert _evaluate_condition(90, "lt", 80) is False

    def test_eq(self):
        assert _evaluate_condition(80, "eq", 80) is True

    def test_ne(self):
        assert _evaluate_condition(80, "ne", 90) is True

    def test_gte(self):
        assert _evaluate_condition(80, "gte", 80) is True
        assert _evaluate_condition(79, "gte", 80) is False

    def test_lte(self):
        assert _evaluate_condition(80, "lte", 80) is True
        assert _evaluate_condition(81, "lte", 80) is False

    def test_contains(self):
        assert _evaluate_condition("hello world", "contains", "world") is True
        assert _evaluate_condition("hello", "contains", "world") is False

    def test_matches(self):
        assert _evaluate_condition("GE1/0/1", "matches", r"^GE\d") is True
        assert _evaluate_condition("Vlan1", "matches", r"^GE\d") is False

    def test_in(self):
        assert _evaluate_condition("h3c", "in", ["h3c", "huawei"]) is True
        assert _evaluate_condition("zte", "in", ["h3c", "huawei"]) is False

    def test_exists(self):
        assert _evaluate_condition(12, "exists", None) is True
        assert _evaluate_condition(None, "exists", None) is False

    def test_true_op(self):
        assert _evaluate_condition(True, "true", None) is True
        assert _evaluate_condition(False, "true", None) is False
        assert _evaluate_condition(None, "true", None) is False

    def test_false_op(self):
        assert _evaluate_condition(False, "false", None) is True
        assert _evaluate_condition(True, "false", None) is False

    def test_none_value(self):
        assert _evaluate_condition(None, "gt", 80) is False
        assert _evaluate_condition(None, "contains", "x") is False

    def test_unknown_operator(self):
        assert _evaluate_condition(1, "unknown_op", 2) is False


# ── 规则加载测试 ────────────────────────────────────────────────


class TestRuleLoading:
    def test_load_default_rules(self, rule_engine):
        assert len(rule_engine.rules) == 13  # +R013 LLDP 信息项

    def test_rule_ids(self, rule_engine):
        ids = [r.id for r in rule_engine.rules]
        assert "R001" in ids
        assert "R002" in ids
        assert "R003" in ids
        assert "R004" in ids
        assert "R005" in ids

    def test_parse_rules(self):
        data = {
            "rules": [{
                "id": "TEST",
                "check_name": "cpu_usage",
                "name": "test",
                "description": "test rule",
                "severity": "warning",
                "vendors": ["h3c"],
                "device_types": ["*"],
                "metric": "usage_percent",
                "operator": "gt",
                "value": 0,
                "suggestion": "fix it",
            }]
        }
        rules = RuleEngine.parse_rules(data)
        assert len(rules) == 1
        assert rules[0].id == "TEST"
        assert rules[0].check_name == "cpu_usage"
        assert rules[0].vendors == ["h3c"]


# ── 规则评估测试 ────────────────────────────────────────────────


class TestEvaluateCPU:
    def test_cpu_normal_is_pass(self, rule_engine, driver, load_fixture):
        """CPU 12% < 80 阈值 → condition False → PASS"""
        output = load_fixture("display_cpu_usage.txt")
        parsed = driver.parse_output("cpu_usage", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.PASS
        assert "R001" in item.message
        assert item.details["severity"] == "critical"

    def test_cpu_high_is_fail(self, rule_engine, driver):
        """CPU 95% > 80 阈值 → condition True → FAIL"""
        output = "Slot 0 CPU 0 usage:\n       95% in last 5 seconds"
        parsed = driver.parse_output("cpu_usage", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.FAIL
        assert "R001" in item.message
        assert len(item.details["suggestion"]) > 0

    def test_cpu_unknown(self, rule_engine, driver):
        """CPU 值为 None → UNKNOWN"""
        output = "No CPU information."
        parsed = driver.parse_output("cpu_usage", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.UNKNOWN
        assert "无法获取" in item.message


class TestEvaluateMemory:
    def test_memory_normal_is_pass(self, rule_engine, driver, load_fixture):
        """内存 35% < 80 阈值 → PASS"""
        output = load_fixture("display_memory.txt")
        parsed = driver.parse_output("memory_usage", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.PASS
        assert "R002" in item.message

    def test_memory_high_is_fail(self, rule_engine, driver):
        """内存 92% > 80 阈值 → FAIL"""
        output = "Used Rate: 92%"
        parsed = driver.parse_output("memory_usage", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.FAIL
        assert item.details["severity"] == "critical"


class TestEvaluateInterface:
    def test_interfaces_with_down_is_fail(self, rule_engine, driver, load_fixture):
        """有 DOWN 接口 → abnormal_count > 0 → FAIL"""
        output = load_fixture("display_interface_brief.txt")
        parsed = driver.parse_output("interface_status", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.FAIL
        assert "R003" in item.message
        assert item.details["severity"] == "warning"

    def test_interfaces_all_up_is_pass(self, rule_engine, driver):
        """全部 UP → abnormal_count = 0 → PASS"""
        output = """Interface            Link Speed   Duplex  Type PVID
GE1/0/1              UP   1G      full    A    1
GE1/0/2              UP   100M    full    A    1
"""
        parsed = driver.parse_output("interface_status", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.PASS


class TestEvaluateInterfaceErrors:
    def test_errors_detected(self, rule_engine, driver, load_fixture):
        """有错误包 → error_count > 0 → FAIL"""
        output = load_fixture("display_interface.txt")
        parsed = driver.parse_output("interface_errors", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.FAIL
        assert "R004" in item.message
        assert item.details["error_count"] > 0

    def test_no_errors(self, rule_engine, driver):
        """无错误包 → error_count = 0 → PASS"""
        output = """GigabitEthernet1/0/1
Current state: UP
Input:  100 packets, 5000 bytes
        0 errors, 0 CRC, 0 giants, 0 throttles
Output: 200 packets, 6000 bytes
        0 errors, 0 aborted, 0 deferred
"""
        parsed = driver.parse_output("interface_errors", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.PASS


class TestEvaluateTelnet:
    def test_telnet_enabled_is_fail(self, rule_engine, driver, load_fixture):
        """Telnet 启用 → telnet_enabled = True → condition True → FAIL"""
        output = load_fixture("display_tcp_status.txt")
        parsed = driver.parse_output("telnet_service", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.FAIL
        assert "R005" in item.message
        assert item.details["telnet_enabled"] is True

    def test_telnet_disabled_is_pass(self, rule_engine, driver, load_fixture):
        """Telnet 未启用 → telnet_enabled = False → condition False → PASS"""
        output = load_fixture("display_tcp_status_no_telnet.txt")
        parsed = driver.parse_output("telnet_service", output)
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.PASS
        assert item.details["telnet_enabled"] is False


# ── 过滤测试 ────────────────────────────────────────────────────


class TestFiltering:
    def test_vendor_filter(self, driver):
        """规则 R004 只适用于 h3c，其他厂商应返回 UNKNOWN。"""
        rules = RuleEngine.parse_rules({
            "rules": [{
                "id": "R004",
                "name": "test",
                "description": "",
                "severity": "warning",
                "vendors": ["h3c"],
                "device_types": ["*"],
                "check_name": "interface_errors",
                "metric": "error_count",
                "operator": "gt",
                "value": 0,
                "suggestion": "",
            }]
        })
        engine = RuleEngine(rules)

        output = "GigabitEthernet1/0/1\nInput: 100 packets\n  5 errors\nOutput: 100 packets\n  0 errors"
        parsed = driver.parse_output("interface_errors", output)
        item = engine.evaluate(parsed, "huawei", "comware_switch")

        assert item.status == CheckStatus.UNKNOWN

    def test_device_type_filter(self, driver):
        """规则只适用于 comware_switch，其他类型应返回 UNKNOWN。"""
        rules = RuleEngine.parse_rules({
            "rules": [{
                "id": "R004",
                "name": "test",
                "description": "",
                "severity": "warning",
                "vendors": ["*"],
                "device_types": ["comware_switch"],
                "check_name": "interface_errors",
                "metric": "error_count",
                "operator": "gt",
                "value": 0,
                "suggestion": "",
            }]
        })
        engine = RuleEngine(rules)

        output = "GigabitEthernet1/0/1\nInput: 100 packets\n  5 errors\nOutput: 100 packets\n  0 errors"
        parsed = driver.parse_output("interface_errors", output)
        item = engine.evaluate(parsed, "h3c", "vrp_switch")

        assert item.status == CheckStatus.UNKNOWN

    def test_wildcard_matches_all(self, driver):
        """vendors=["*"] 应匹配所有厂商。"""
        rules = RuleEngine.parse_rules({
            "rules": [{
                "id": "R001",
                "name": "CPU check",
                "description": "",
                "severity": "critical",
                "vendors": ["*"],
                "device_types": ["*"],
                "check_name": "cpu_usage",
                "metric": "usage_percent",
                "operator": "gt",
                "value": 80,
                "suggestion": "",
            }]
        })
        engine = RuleEngine(rules)

        output = "95% in last 5 seconds"
        parsed = driver.parse_output("cpu_usage", output)
        item = engine.evaluate(parsed, "any_vendor", "any_type")

        assert item.status == CheckStatus.FAIL


# ── 解析失败测试 ────────────────────────────────────────────────


class TestParseFailure:
    def test_parse_failure_is_unknown(self, rule_engine):
        parsed = ParsedResult(
            name="cpu_usage",
            category="CPU",
            command="display cpu-usage",
            raw_output="some output",
            success=False,
            error="解析失败",
        )
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.UNKNOWN
        assert "解析失败" in item.message

    def test_no_matching_rule_is_unknown(self, rule_engine):
        parsed = ParsedResult(
            name="nonexistent_check",
            category="未知",
            command="some command",
            raw_output="output",
            success=True,
            parsed={},
        )
        item = rule_engine.evaluate(parsed, "h3c", "comware_switch")

        assert item.status == CheckStatus.UNKNOWN
        assert "未找到适用规则" in item.message


# ── 驱动 fixture ────────────────────────────────────────────────


@pytest.fixture
def driver() -> H3CComwareSwitchDriver:
    return H3CComwareSwitchDriver()
