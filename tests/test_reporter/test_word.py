"""Word 报告生成器测试"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.models import (
    CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport
)
from patrol.reporter.word import WordReporter


@pytest.fixture
def sample_report(sample_asset) -> PatrolReport:
    device = DeviceReport(asset=sample_asset)
    device.check_items = [
        CheckItem(
            name="telnet_service", category="管理服务",
            command="display current-configuration", raw_output="...",
            status=CheckStatus.FAIL,
            message="Telnet 服务已启用",
            details={"severity": "warning", "suggestion": "关闭 Telnet"},
        ),
        CheckItem(
            name="cpu_usage", category="CPU",
            command="display current-configuration", raw_output="...",
            status=CheckStatus.PASS,
            message="CPU 利用率正常",
            details={"severity": "critical"},
        ),
    ]
    return PatrolReport(title="巡检报告", devices=[device])


class TestWordReporter:
    def test_creates_file(self, sample_report, tmp_path):
        reporter = WordReporter()
        output = reporter.generate(sample_report, tmp_path / "test.docx")
        assert output.exists()
        assert output.stat().st_size > 0

    def test_file_is_valid_docx(self, sample_report, tmp_path):
        from docx import Document
        reporter = WordReporter()
        output = reporter.generate(sample_report, tmp_path / "test.docx")
        doc = Document(str(output))
        assert len(doc.paragraphs) > 0

    def test_contains_device_name(self, sample_report, tmp_path):
        from docx import Document
        reporter = WordReporter()
        output = reporter.generate(sample_report, tmp_path / "test.docx")
        doc = Document(str(output))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "测试交换机" in text

    def test_contains_status(self, sample_report, tmp_path):
        from docx import Document
        reporter = WordReporter()
        output = reporter.generate(sample_report, tmp_path / "test.docx")
        doc = Document(str(output))
        # 状态在表格单元格中，需要搜索全部文本
        all_text = ""
        for p in doc.paragraphs:
            all_text += p.text + "\n"
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    all_text += cell.text + "\n"
        assert "PASS" in all_text
        assert "FAIL" in all_text

    def test_empty_report(self, tmp_path):
        from docx import Document
        report = PatrolReport(title="空报告", devices=[])
        reporter = WordReporter()
        output = reporter.generate(report, tmp_path / "empty.docx")
        doc = Document(str(output))
        assert len(doc.paragraphs) > 0

    def test_raw_output_rows_and_chinese_severity(self, sample_report, tmp_path):
        """原始输出整行平铺进检查结果表;级别中文化展示。"""
        from docx import Document
        reporter = WordReporter()
        output = reporter.generate(sample_report, tmp_path / "raw.docx")
        doc = Document(str(output))
        all_text = ""
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    all_text += cell.text + "\n"
        assert "原始输出" in all_text
        assert "display current-configuration" in all_text
        assert "警告" in all_text and "严重" in all_text
        assert "CRITICAL" not in all_text and "WARNING" not in all_text


# ── 商务交付信息(meta)与正式汇报版 ─────────────────────────────

from patrol.models import DeviceAsset  # noqa: E402
from patrol.reporter.word import build_report_meta  # noqa: E402


def _doc_text(path) -> str:
    from docx import Document as Doc
    return "\n".join(p.text for p in Doc(str(path)).paragraphs) + "\n" + \
        "\n".join(c.text for tb in Doc(str(path)).tables for r in tb.rows for c in r.cells)


def test_build_report_meta_from_customer():
    asset = DeviceAsset(name="d", customer="甲方A公司", host="10.0.0.1")
    report = PatrolReport(devices=[DeviceReport(asset=asset)])
    meta = build_report_meta(report)
    assert meta["customer"] == "甲方A公司"
    assert meta["vendor_company"]          # 乙方非空(产品作者)
    assert meta["report_no"].startswith("XJ-")
    assert meta["formal"] is False


def test_meta_cover_and_signature_page(tmp_path):
    asset = DeviceAsset(name="d", customer="甲方A公司", host="10.0.0.1")
    report = PatrolReport(devices=[DeviceReport(asset=asset)])
    out = tmp_path / "m.docx"
    meta = build_report_meta(report, contract_no="HT-2026-001",
                             inspector="张工", reviewer="李工")
    WordReporter().generate(report, out, meta=meta)
    text = _doc_text(out)
    assert "甲方单位" in text and "甲方A公司" in text      # 封面商务表
    assert "合同编号" in text and "HT-2026-001" in text
    assert "报告编号" in text and "巡检人" in text and "张工" in text
    assert "签字确认" in text                              # 签字页
    assert "乙方(盖章):" in text and "甲方(盖章):" in text  # 盖章区
    assert "巡检人" in text and "甲方接收人" in text


def test_formal_mode_skips_raw_output(tmp_path):
    asset = DeviceAsset(name="d", customer="C", host="10.0.0.1")
    dev = DeviceReport(asset=asset)
    dev.check_items.append(CheckItem(
        name="cpu_usage", category="CPU", command="display cpu-usage",
        raw_output="CPU Usage: 12%", status=CheckStatus.PASS, message="ok"))
    report = PatrolReport(devices=[dev])

    # 工程版:含原始输出
    out_eng = tmp_path / "eng.docx"
    WordReporter().generate(report, out_eng, meta=build_report_meta(report))
    assert "原始输出" in _doc_text(out_eng)

    # 正式版:无原始输出章节,封面标注版本
    out_formal = tmp_path / "formal.docx"
    WordReporter().generate(report, out_formal,
                            meta=build_report_meta(report, formal=True))
    text = _doc_text(out_formal)
    assert "原始输出" not in text
    assert "正式汇报版" in text


def test_risk_severity_ordering(tmp_path):
    asset = DeviceAsset(name="d", host="10.0.0.1")
    dev = DeviceReport(asset=asset)
    dev.check_items += [
        CheckItem(name="a", category="x", command="c", raw_output="",
                  status=CheckStatus.FAIL, message="警告项",
                  details={"severity": "warning"}),
        CheckItem(name="b", category="x", command="c", raw_output="",
                  status=CheckStatus.FAIL, message="严重项",
                  details={"severity": "critical"}),
    ]
    out = tmp_path / "r.docx"
    WordReporter().generate(PatrolReport(devices=[dev]), out)
    text = _doc_text(out)
    assert text.find("严重项") < text.find("警告项")  # critical 排前
