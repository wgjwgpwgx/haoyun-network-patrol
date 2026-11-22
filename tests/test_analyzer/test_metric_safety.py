"""引擎数值比较安全化测试(问题 010:float() 无保护 → UNKNOWN 而不是崩溃)"""
from __future__ import annotations

from patrol.analyzer.engine import Rule, RuleEngine, _evaluate_condition
from patrol.drivers.base import ParsedResult
from patrol.models import CheckStatus


def _rule(op: str, value) -> Rule:
    return Rule(
        id="T001", name="t", description="d", severity="medium",
        vendors=["*"], device_types=["*"], check_name="cpu_usage",
        metric="usage_percent", operator=op, value=value, suggestion="s",
    )


def _parsed(val) -> ParsedResult:
    return ParsedResult(
        name="cpu_usage", category="性能", command="c",
        raw_output="r", parsed={"usage_percent": val}, success=True,
    )


class TestNoCrashOnGarbage:
    def test_non_numeric_metric_is_unknown_not_crash(self):
        engine = RuleEngine([])
        item = engine._evaluate_rule(_rule("gt", 80), _parsed("N/A"))
        assert item.status == CheckStatus.UNKNOWN
        assert "无法比较" in item.message

    def test_none_rule_value_is_unknown(self):
        engine = RuleEngine([])
        item = engine._evaluate_rule(_rule("gt", None), _parsed(50))
        assert item.status == CheckStatus.UNKNOWN

    def test_empty_string_metric_is_unknown(self):
        engine = RuleEngine([])
        item = engine._evaluate_rule(_rule("lte", 80), _parsed(""))
        assert item.status == CheckStatus.UNKNOWN


class TestNormalBehaviorKept:
    def test_numeric_compare_fail_pass(self):
        engine = RuleEngine([])
        assert engine._evaluate_rule(_rule("gt", 80), _parsed(90)).status \
            == CheckStatus.FAIL
        assert engine._evaluate_rule(_rule("gt", 80), _parsed(10)).status \
            == CheckStatus.PASS

    def test_string_eq_ne_unchanged(self):
        assert _evaluate_condition("abc", "eq", "abc") is True
        assert _evaluate_condition("abc", "ne", "abc") is False

    def test_mixed_numeric_strings_compare_as_numbers(self):
        assert _evaluate_condition(5, "eq", "5") is True
        assert _evaluate_condition("10", "gt", 9) is True

    def test_contains_matches_unaffected(self):
        assert _evaluate_condition("hello world", "contains", "world") is True
        assert _evaluate_condition("abc123", "matches", r"\d+") is True
