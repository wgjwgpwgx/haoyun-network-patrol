"""YAML 规则引擎 - 从 YAML 文件加载规则，评估检查结果

规则格式见 config/rules/default.yaml。
规则引擎只处理有匹配规则的检查项；device_info 等信息展示项由 CLI 直接处理。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from patrol.drivers.base import ParsedResult
from patrol.models import CheckItem, CheckStatus

logger = logging.getLogger(__name__)


# ── 嵌套检查展开 ─────────────────────────────────────────────────


def expand_parsed(parsed: ParsedResult) -> list[ParsedResult]:
    """把聚合解析结果展开为逐项 ParsedResult 列表。

    parse_config_cur 等聚合解析器返回 {"checks": [{name, category, parsed}, ...]}
    的嵌套结构,而规则按检查名(check_name)逐项匹配——展开后 telnet_service/
    snmp_community/vty_auth/stp_status 等嵌套检查才能与规则对上。

    无嵌套结构(或解析失败)时返回 [parsed] 本身。
    """
    nested = parsed.parsed.get("checks") if parsed.success else None
    if not isinstance(nested, list) or not nested:
        return [parsed]

    results = []
    for item in nested:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        results.append(ParsedResult(
            name=str(item["name"]),
            category=str(item.get("category", parsed.category)),
            command=parsed.command,
            raw_output=parsed.raw_output,
            parsed=item.get("parsed") or {},
            success=True,
        ))
    return results or [parsed]


@dataclass
class Rule:
    """一条分析规则"""
    id: str
    name: str
    description: str
    severity: str
    vendors: list[str]
    device_types: list[str]
    check_name: str
    metric: str
    operator: str
    value: Any
    suggestion: str


@dataclass
class RuleEngine:
    """基于 YAML 的规则分析引擎

    用法::

        rules = RuleEngine.load_file("config/rules/default.yaml")
        engine = RuleEngine(rules)
        item = engine.evaluate(parsed, vendor="h3c", device_type="comware_switch")
    """

    rules: list[Rule]

    @classmethod
    def load_file(cls, path: str | Path) -> list[Rule]:
        """从 YAML 文件加载规则列表。"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"规则文件不存在: {path}")
        with p.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.parse_rules(data)

    @classmethod
    def load_dir(cls, path: str | Path) -> list[Rule]:
        """从规则目录加载:合并目录下全部 *.yaml。

        顶层声明 enabled: false 的文件跳过(未经验证的规则包默认不参与判定)。
        排序后"厂商/类型专用"规则排在"通配(*)"规则之前——引擎取第一条适用
        规则,因此厂商专项规则可以覆盖默认阈值。
        """
        rules: list[Rule] = []
        for f in sorted(Path(path).glob("*.yaml")):
            with f.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if data.get("enabled", True) is False:
                continue
            rules.extend(cls.parse_rules(data))
        return sorted(rules, key=lambda r: ("*" in r.vendors,
                                            "*" in r.device_types))

    @classmethod
    def parse_rules(cls, data: dict[str, Any]) -> list[Rule]:
        """从 YAML 解析后的 dict 构造规则列表。"""
        rules: list[Rule] = []
        for raw in data.get("rules", []):
            rules.append(Rule(
                id=raw["id"],
                name=raw["name"],
                description=raw.get("description", ""),
                severity=raw.get("severity", "warning"),
                vendors=raw.get("vendors", ["*"]),
                device_types=raw.get("device_types", ["*"]),
                check_name=raw.get("check_name", ""),
                metric=raw["metric"],
                operator=raw["operator"],
                value=raw.get("value"),
                suggestion=raw.get("suggestion", ""),
            ))
        return rules

    def evaluate(
        self,
        parsed: ParsedResult,
        vendor: str = "*",
        device_type: str = "*",
    ) -> CheckItem:
        """评估一条解析结果，返回带判定状态的检查项。

        1. 如果 parsed.success == False → UNKNOWN
        2. 在适用规则中找到第一条匹配的
        3. 评估规则条件
        4. 无匹配规则 → UNKNOWN
        """
        # 解析失败直接返回 UNKNOWN
        if not parsed.success:
            return CheckItem(
                name=parsed.name,
                category=parsed.category,
                command=parsed.command,
                raw_output=parsed.raw_output,
                status=CheckStatus.UNKNOWN,
                message=f"解析失败: {parsed.error}",
            )

        # 找到适用规则（匹配 check name、vendor、device_type）
        applicable = self._find_applicable_rules(parsed.name, vendor, device_type)

        if not applicable:
            return CheckItem(
                name=parsed.name,
                category=parsed.category,
                command=parsed.command,
                raw_output=parsed.raw_output,
                status=CheckStatus.UNKNOWN,
                message=f"未找到适用规则: {parsed.name}",
            )

        # 评估第一条适用规则
        rule = applicable[0]
        return self._evaluate_rule(rule, parsed)

    def _find_applicable_rules(
        self, check_name: str, vendor: str, device_type: str
    ) -> list[Rule]:
        """找到适用于当前检查项、厂商、设备类型的规则。

        匹配逻辑：
          1. rule.check_name 必须与 check_name 一致（YAML 中显式声明）
          2. vendor 必须在 rule.vendors 中（或 rule.vendors 包含 "*"）
          3. device_type 必须在 rule.device_types 中（或 rule.device_types 包含 "*"）
        """
        result: list[Rule] = []
        for rule in self.rules:
            if rule.check_name != check_name:
                continue
            if "*" not in rule.vendors and vendor not in rule.vendors:
                continue
            if "*" not in rule.device_types and device_type not in rule.device_types:
                continue
            result.append(rule)
        return result

    def _evaluate_rule(self, rule: Rule, parsed: ParsedResult) -> CheckItem:
        """评估单条规则的条件。

        规则语义：condition 描述的是"异常/问题"状态。
          - condition 为 True → 检测到异常 → FAIL
          - condition 为 False → 正常 → PASS

        例如：
          R001: metric=usage_percent, operator=gt, value=80
            → "CPU > 80 是异常"，12 > 80 = False → PASS
          R005: metric=telnet_enabled, operator=true
            → "Telnet 启用是异常"，True = True → FAIL
        """
        # 从 parsed.parsed 中提取 metric 值
        # parsed.parsed 的结构如 {"usage_percent": 12}，直接用作数据源
        metric_value = _resolve_metric(parsed.parsed, rule.metric)

        # metric 值为 None → 数据缺失 → UNKNOWN。exists 运算符本身就是判断"是否存在",
        # None 是它的有效输入;true/false 则不行——取不到值不等于"未触发",否则
        # 安全类检查(Telnet 是否启用等)在解析不出结果时会被判成"通过"
        if metric_value is None and rule.operator != "exists":
            return CheckItem(
                name=parsed.name,
                category=parsed.category,
                command=parsed.command,
                raw_output=parsed.raw_output,
                status=CheckStatus.UNKNOWN,
                message=f"[{rule.id}] {rule.name}: 无法获取指标值 ({rule.metric})",
                details={
                    **parsed.parsed,
                    "severity": rule.severity,
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "suggestion": "",
                    "metric_value": None,
                },
            )

        # 评估条件：True 表示检测到问题
        try:
            condition_triggered = _evaluate_condition(
                metric_value, rule.operator, rule.value
            )
        except ValueError:
            # 指标值无法按数值比较(问题 010:float() 无保护)→ UNKNOWN 而不是崩溃
            return CheckItem(
                name=parsed.name,
                category=parsed.category,
                command=parsed.command,
                raw_output=parsed.raw_output,
                status=CheckStatus.UNKNOWN,
                message=(
                    f"[{rule.id}] {rule.name}: 指标值无法比较 "
                    f"({rule.metric}={metric_value!r})"
                ),
                details={
                    **parsed.parsed,
                    "severity": rule.severity,
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "suggestion": "",
                    "metric_value": metric_value,
                },
            )

        if condition_triggered:
            status = CheckStatus.FAIL
            message = f"[{rule.id}] {rule.name}: {rule.description}"
        else:
            status = CheckStatus.PASS
            message = f"[{rule.id}] {rule.name}: 检查通过"

        return CheckItem(
            name=parsed.name,
            category=parsed.category,
            command=parsed.command,
            raw_output=parsed.raw_output,
            status=status,
            message=message,
            details={
                **parsed.parsed,
                "severity": rule.severity,
                "rule_id": rule.id,
                "rule_name": rule.name,
                "suggestion": rule.suggestion if condition_triggered else "",
                "metric_value": metric_value,
            },
        )



# ── 辅助函数 ────────────────────────────────────────────────────


def _resolve_metric(data: dict[str, Any], metric: str) -> Any:
    """从嵌套 dict 中按点号路径提取值。

    例如 _resolve_metric({"details": {"usage_percent": 12}}, "details.usage_percent") → 12
    """
    parts = metric.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _as_float(value: Any) -> float | None:
    """安全转 float:失败返回 None(问题 010:float() 无保护)。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evaluate_condition(
    metric_value: Any, operator: str, rule_value: Any
) -> bool:
    """评估条件：metric_value <operator> rule_value

    Returns:
        True 表示检查通过（正常），False 表示检查失败（异常）
    """
    # None 值处理：如果 metric 值为 None，大多数比较都应返回 UNKNOWN
    # 但这里返回 False 让调用方决定
    if operator == "exists":
        return metric_value is not None
    if operator == "true":
        return bool(metric_value) is True
    if operator == "false":
        return bool(metric_value) is False

    if metric_value is None:
        return False

    if operator in ("gt", "lt", "eq", "ne", "gte", "lte"):
        if (
            operator in ("eq", "ne")
            and isinstance(metric_value, str)
            and isinstance(rule_value, str)
        ):
            return (
                metric_value == rule_value
                if operator == "eq"
                else metric_value != rule_value
            )
        left = _as_float(metric_value)
        right = _as_float(rule_value)
        if left is None or right is None:
            # 问题 010:非数值(如 "N/A")无法比较,交给调用方按 UNKNOWN 处理
            raise ValueError(
                f"数值比较需要数字: {metric_value!r} {operator} {rule_value!r}"
            )
        return {
            "gt": left > right,
            "lt": left < right,
            "eq": left == right,
            "ne": left != right,
            "gte": left >= right,
            "lte": left <= right,
        }[operator]
    if operator == "contains":
        return str(rule_value) in str(metric_value)
    if operator == "matches":
        return bool(re.search(str(rule_value), str(metric_value)))
    if operator == "in":
        if isinstance(rule_value, list):
            return metric_value in rule_value
        return False

    logger.warning("未知运算符: %s", operator)
    return False
