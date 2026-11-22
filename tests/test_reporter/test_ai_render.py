"""报告器渲染 AI 分析章节测试(HTML JSON 字段 + Word 章节 + rebuild)"""
from __future__ import annotations

import json

from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceReport,
    PatrolReport,
)
from patrol.reporter.html import HTMLReporter
from patrol.reporter.rebuild import rebuild_report
from patrol.reporter.word import WordReporter

import pytest


@pytest.fixture
def sample_report(sample_asset) -> PatrolReport:
    """一份带 PASS/FAIL 检查项的示例报告。"""
    device = DeviceReport(asset=sample_asset)
    device.check_items = [
        CheckItem(
            name="cpu", category="CPU", command="display cpu-usage",
            raw_output="CPU 12%", status=CheckStatus.PASS, message="正常",
        ),
        CheckItem(
            name="iface", category="接口", command="display interface brief",
            raw_output="GE1/0/2 DOWN", status=CheckStatus.FAIL,
            message="1 个异常接口",
            details={"severity": "critical", "suggestion": "检查线路"},
        ),
    ]
    return PatrolReport(title="AI渲染测试", devices=[device])

AI_RESULT = {
    "executive_summary": "整体运行平稳,存在少量风险。",
    "health_score": 82,
    "overall_risk": "medium",
    "key_findings": [{
        "device": "测试交换机", "issue": "固件版本过旧",
        "severity": "medium", "impact": "已知漏洞影响",
        "recommendation": "升级至最新补丁版本",
    }],
    "recommendations": ["一个月内完成升级"],
    "maintenance_suggestions": ["建立季度巡检机制"],
    "meta": {"model": "test-model", "analyzed_at": "2026-01-01T00:00:00",
             "device_count": 1},
}


class TestHTMLAISection:
    def test_json_contains_ai(self, sample_report, tmp_path):
        sample_report.ai_analysis = AI_RESULT
        HTMLReporter().generate(sample_report, tmp_path / "r.html")
        data = json.loads(
            (tmp_path / "r.json").read_text(encoding="utf-8")
        )
        assert data["ai_analysis"]["health_score"] == 82

    def test_html_renders_ai_section(self, sample_report, tmp_path):
        sample_report.ai_analysis = AI_RESULT
        HTMLReporter().generate(sample_report, tmp_path / "r.html")
        html = (tmp_path / "r.html").read_text(encoding="utf-8")
        assert "AI 综合分析" in html
        assert "健康评分" in html
        assert "固件版本过旧" in html
        assert "升级至最新补丁版本" in html

    def test_html_without_ai_has_no_section(self, sample_report, tmp_path):
        HTMLReporter().generate(sample_report, tmp_path / "r.html")
        html = (tmp_path / "r.html").read_text(encoding="utf-8")
        assert "AI 综合分析" not in html


class TestWordAISection:
    def test_word_renders_ai_section(self, sample_report, tmp_path):
        from docx import Document

        sample_report.ai_analysis = AI_RESULT
        path = tmp_path / "r.docx"
        WordReporter().generate(sample_report, path)

        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    text += "\n" + cell.text
        assert "AI 综合分析汇总" in text
        assert "固件版本过旧" in text

    def test_word_without_ai_skips_section(self, sample_report, tmp_path):
        from docx import Document

        path = tmp_path / "r.docx"
        WordReporter().generate(sample_report, path)
        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "AI 综合分析汇总" not in text


class TestRebuild:
    def test_rebuild_roundtrip_keeps_ai(self, sample_report, tmp_path):
        sample_report.ai_analysis = AI_RESULT
        HTMLReporter().generate(sample_report, tmp_path / "r.html")
        data = json.loads(
            (tmp_path / "r.json").read_text(encoding="utf-8")
        )
        report = rebuild_report(data)
        assert report.ai_analysis == AI_RESULT
        assert report.devices[0].asset.name == "测试交换机"
        assert report.devices[0].check_items[0].status.value == "PASS"

    def test_rebuild_without_ai(self, sample_report, tmp_path):
        HTMLReporter().generate(sample_report, tmp_path / "r.html")
        data = json.loads(
            (tmp_path / "r.json").read_text(encoding="utf-8")
        )
        assert rebuild_report(data).ai_analysis is None
