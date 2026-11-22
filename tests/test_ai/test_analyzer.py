"""AI 分析器测试(prompt 构建 / JSON 解析 / 规范化 / 兜底)"""
from __future__ import annotations

import json

import pytest

from patrol.ai.analyzer import (
    AINotConfigured,
    _digest,
    _extract_json,
    _fallback_health_score,
    _fallback_risk,
    _normalize,
    analyze_report,
)
from patrol.ai.client import LLMError
from patrol.ai.config import AIConfig
from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceAsset,
    DeviceReport,
    PatrolReport,
)


@pytest.fixture
def report(sample_asset) -> PatrolReport:
    device = DeviceReport(asset=sample_asset)
    device.check_items = [
        CheckItem(
            name="cpu", category="CPU", command="display cpu",
            raw_output="CPU 12%", status=CheckStatus.PASS, message="正常",
        ),
        CheckItem(
            name="iface", category="接口", command="display int",
            raw_output="password super123\nGE1/0/2 DOWN",
            status=CheckStatus.FAIL, message="1 个接口 DOWN",
            details={"severity": "critical", "suggestion": "检查线路"},
        ),
        CheckItem(
            name="fan", category="风扇", command="display fan",
            raw_output="", status=CheckStatus.UNKNOWN, message="无法获取",
        ),
    ]
    return PatrolReport(title="AI测试报告", devices=[device])


class TestDigest:
    def test_fail_includes_snippet_and_redacts(self, report):
        d = _digest(report)
        checks = d["devices"][0]["checks"]
        fail = next(c for c in checks if c["status"] == "FAIL")
        assert "output_snippet" in fail
        assert "super123" not in fail["output_snippet"]  # 脱敏
        assert "GE1/0/2 DOWN" in fail["output_snippet"]
        # 通过项也携带原始输出(余量补给):AI 需结合设备输出整体融合分析
        pass_item = next(c for c in checks if c["status"] == "PASS")
        assert "CPU 12%" in pass_item.get("output_snippet", "")

    def test_carries_rule_suggestion_and_severity(self, report):
        d = _digest(report)
        fail = next(
            c for c in d["devices"][0]["checks"] if c["status"] == "FAIL"
        )
        assert fail["severity"] == "critical"
        assert fail["rule_suggestion"] == "检查线路"


class TestExtractJson:
    def test_plain(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_prose_wrapped(self):
        text = '好的,以下是分析:\n{"a": 1}\n希望有帮助'
        assert _extract_json(text) == {"a": 1}

    def test_invalid(self):
        with pytest.raises(LLMError):
            _extract_json("完全不是 JSON")

    def test_non_object(self):
        with pytest.raises(LLMError):
            _extract_json("[1, 2, 3]")


class TestNormalize:
    def _parsed(self, **kw):
        base = {
            "executive_summary": "整体健康",
            "health_score": 72,
            "overall_risk": "medium",
            "key_findings": [{
                "device": "sw1", "issue": "接口DOWN", "severity": "high",
                "impact": "业务中断", "recommendation": "检查光模块",
            }],
            "recommendations": ["先处理接口", "再优化告警"],
            "maintenance_suggestions": ["建立季度巡检"],
        }
        base.update(kw)
        return base

    def test_normal_passthrough(self, report):
        out = _normalize(self._parsed(), report)
        assert out["health_score"] == 72
        assert out["overall_risk"] == "medium"
        assert out["key_findings"][0]["severity"] == "high"
        assert out["recommendations"] == ["先处理接口", "再优化告警"]

    def test_bad_score_clamped_or_fallback(self, report):
        out = _normalize(self._parsed(health_score=999), report)
        assert out["health_score"] == 100
        out = _normalize(self._parsed(health_score="abc"), report)
        assert 0 <= out["health_score"] <= 100

    def test_bad_risk_fallback(self, report):
        out = _normalize(self._parsed(overall_risk="terrible"), report)
        # 报告含 critical FAIL → 兜底为 critical
        assert out["overall_risk"] == "critical"

    def test_findings_coercion(self, report):
        out = _normalize(self._parsed(
            key_findings=[{"issue": "x", "severity": "ultra"}, "junk", 3],
            recommendations="只有一条建议",
        ), report)
        assert len(out["key_findings"]) == 1
        assert out["key_findings"][0]["severity"] == "medium"
        assert out["recommendations"] == ["只有一条建议"]


class TestFallbacks:
    def test_health_score_all_pass(self, sample_asset):
        dev = DeviceReport(asset=sample_asset)
        dev.check_items = [CheckItem(
            name="a", category="A", command="c", raw_output="",
            status=CheckStatus.PASS, message="",
        )]
        report = PatrolReport(devices=[dev])
        assert _fallback_health_score(report) == 100

    def test_health_score_fail_penalized(self, report):
        score = _fallback_health_score(report)
        assert score < 100

    def test_risk_critical(self, report):
        assert _fallback_risk(report) == "critical"

    def test_risk_low_when_clean(self, sample_asset):
        dev = DeviceReport(asset=sample_asset)
        dev.check_items = []
        assert _fallback_risk(PatrolReport(devices=[dev])) == "low"


class TestAnalyzeReport:
    def test_not_configured_raises(self, report):
        with pytest.raises(AINotConfigured):
            analyze_report(report, AIConfig())

    def test_full_flow_with_mock_llm(self, report, monkeypatch):
        llm_output = json.dumps({
            "executive_summary": "存在关键接口故障,需尽快处理。",
            "health_score": 58,
            "overall_risk": "high",
            "key_findings": [{
                "device": "测试交换机", "issue": "GE1/0/2 DOWN",
                "severity": "high", "impact": "下联业务中断",
                "recommendation": "display interface gi1/0/2 检查,更换光模块",
            }],
            "recommendations": ["立即排查 DOWN 接口", "建立告警联动"],
            "maintenance_suggestions": ["季度光功率巡检"],
        }, ensure_ascii=False)

        monkeypatch.setattr(
            "patrol.ai.analyzer.LLMClient.chat",
            lambda self, messages, json_mode=False: llm_output,
        )
        cfg = AIConfig(enabled=True, api_key="k")
        result = analyze_report(report, cfg)

        assert result["executive_summary"].startswith("存在关键")
        assert result["health_score"] == 58
        assert result["overall_risk"] == "high"
        assert result["key_findings"][0]["device"] == "测试交换机"
        assert result["meta"]["model"] == cfg.model
        assert result["meta"]["device_count"] == 1

    def test_llm_garbage_raises(self, report, monkeypatch):
        monkeypatch.setattr(
            "patrol.ai.analyzer.LLMClient.chat",
            lambda self, messages, json_mode=False: "抱歉我无法分析",
        )
        with pytest.raises(LLMError):
            analyze_report(report, AIConfig(enabled=True, api_key="k"))
