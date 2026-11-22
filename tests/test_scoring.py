"""本地健康评分模型测试(销号清单 #3)"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from patrol.models import (
    CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport,
)
from patrol.scoring import _grade, score_device, score_report


def _dev(items: list[tuple[str, str, str]], name="d", error=None) -> DeviceReport:
    """items: (check_name, status, severity)"""
    asset = DeviceAsset(name=name, host="10.0.0.1")
    d = DeviceReport(asset=asset, error=error)
    for n, s, sev in items:
        d.check_items.append(CheckItem(
            name=n, category="x", command="c", raw_output="",
            status=CheckStatus(s),
            message="m",
            details={"severity": sev} if sev else {},
        ))
    return d


FULL = [
    ("fan_status", "PASS", ""), ("cpu_usage", "PASS", ""),
    ("interface_status", "PASS", ""), ("telnet_service", "PASS", ""),
    ("logbuffer", "PASS", ""),
]


class TestScoreDevice:
    def test_all_pass_is_100(self):
        r = score_device(_dev(FULL))
        assert r["score"] == 100 and r["grade"] == "优" and not r["veto"]

    def test_warning_fail_lowers_group(self):
        items = [("fan_status", "FAIL", "warning")] + FULL[1:]
        r = score_device(_dev(items))
        # hardware 组 0 分:0*0.3 + 100*0.7 = 70
        assert r["score"] == 70 and r["grade"] == "关注"
        assert r["groups"]["hardware"]["score"] == 0

    def test_critical_fail_triggers_veto(self):
        items = [("cpu_usage", "FAIL", "critical")] + [FULL[0]] + FULL[2:]
        r = score_device(_dev(items))
        # 常规 80 分,但 critical 否决强制 ≤40
        assert r["veto"] is True
        assert r["score"] <= 40 and r["grade"] == "差"

    def test_unknown_not_in_denominator(self):
        """UNKNOWN 不进分母:组内 1 PASS + 1 UNKNOWN = 100 分。"""
        items = FULL + [("temperature", "UNKNOWN", "")]
        r = score_device(_dev(items))
        assert r["score"] == 100

    def test_weight_renormalize_when_group_empty(self):
        """某组无判定项时权重归一:仅 link 组 1P1F → 50 分。"""
        items = [("interface_status", "PASS", ""),
                 ("interface_errors", "FAIL", "warning")]
        r = score_device(_dev(items))
        assert r["score"] == 50 and set(r["groups"]) == {"link"}

    def test_error_device_zero(self):
        r = score_device(_dev(FULL, error="连接超时"))
        assert r["score"] == 0 and r["grade"] == "差"

    def test_device_info_excluded(self):
        r = score_device(_dev(FULL + [("device_info", "PASS", "")]))
        assert "device_info" not in str(r["groups"]) and r["score"] == 100

    def test_nested_security_items_counted(self):
        """config_cur 展开后的 telnet_service 等安全项计入 security 组。"""
        items = FULL + [("snmp_community", "FAIL", "critical")]
        r = score_device(_dev(items))
        assert r["groups"]["security"]["fail"] == 1 and r["veto"] is True


class TestGradeBoundaries:
    @pytest.mark.parametrize("score,grade", [
        (90, "优"), (89, "良"), (75, "良"), (74, "关注"),
        (60, "关注"), (59, "差"), (0, "差"),
    ])
    def test_boundaries(self, score, grade):
        assert _grade(score) == grade


class TestScoreReport:
    def test_overall_average(self):
        report = PatrolReport(devices=[
            _dev(FULL, name="a"),                       # 100
            _dev([("fan_status", "FAIL", "warning")] + FULL[1:], name="b"),  # 70
        ])
        r = score_report(report)
        assert r["overall"] == 85 and r["overall_grade"] == "良"
        assert set(r["devices"]) == {"a", "b"}

    def test_empty_report(self):
        r = score_report(PatrolReport())
        assert r["overall"] is None and r["overall_grade"] == "—"


class TestReporterIntegration:
    """三报告载体均呈现健康评分。"""

    def _report(self) -> PatrolReport:
        return PatrolReport(devices=[
            _dev(FULL, name="a"),
            _dev([("fan_status", "FAIL", "critical")] + FULL[1:], name="b"),
        ])

    def test_word_contains_scores(self, tmp_path):
        from patrol.reporter.word import WordReporter
        out = tmp_path / "s.docx"
        WordReporter().generate(self._report(), out)
        from docx import Document
        doc = Document(str(out))
        text = "\n".join(p.text for p in doc.paragraphs) + "\n" + \
            "\n".join(c.text for tb in doc.tables for r in tb.rows for c in r.cells)
        assert "全网健康评分" in text and "健康评分" in text
        assert "[存在严重告警,已降档]" in text  # b 设备否决标注

    def test_excel_contains_scores(self, tmp_path):
        from patrol.reporter.excel import ExcelReporter
        out = tmp_path / "s.xlsx"
        ExcelReporter().generate(self._report(), out)
        from openpyxl import load_workbook
        ws = load_workbook(str(out))["设备台账"]
        assert ws.cell(row=1, column=7).value == "健康分"
        assert ws.cell(row=2, column=7).value == "100(优)"

    def test_html_json_contains_scores(self, tmp_path):
        from patrol.reporter.html import HTMLReporter
        out = tmp_path / "s.html"
        HTMLReporter().generate(self._report(), out)
        html = out.read_text(encoding="utf-8")
        assert "健康分" in html and "严重告警降档" in html
        data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        assert data["devices"][0]["health"] == {"score": 100, "grade": "优",
                                                "veto": False}
