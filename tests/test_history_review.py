"""上期复查与连续期次测试(销号清单 #8)"""
from __future__ import annotations

from pathlib import Path

from patrol.models import (
    CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport,
)
from patrol.storage.history import HistoryStore


def _report(fan_status="FAIL") -> PatrolReport:
    dev = DeviceReport(asset=DeviceAsset(name="核心交换", host="10.0.0.1"))
    dev.check_items = [
        CheckItem(name="cpu_usage", category="CPU", command="c", raw_output="",
                  status=CheckStatus.PASS, message="正常"),
        CheckItem(name="fan_status", category="风扇", command="c", raw_output="",
                  status=CheckStatus(fan_status), message="风扇故障"
                  if fan_status == "FAIL" else "正常",
                  details={"severity": "critical", "suggestion": "更换"}),
    ]
    return PatrolReport(devices=[dev])


def _items(report: PatrolReport) -> list[dict]:
    return [{"name": it.name, "category": it.category,
             "status": it.status.value, "severity":
             str(it.details.get("severity", "")),
             "message": it.message, "suggestion": ""}
            for d in report.devices for it in d.check_items]


def _save(hist: HistoryStore, report: PatrolReport, when: str):
    d = report.devices[0]
    hist.save_run(device_name=d.asset.name, device_host=d.asset.host,
                  device_type="", vendor="h3c", customer="C", project="",
                  pass_count=d.pass_count, fail_count=d.fail_count,
                  unknown_count=d.unknown_count, check_items=_items(report),
                  error=None, report_file=None, run_time=when)


def test_prev_fail_and_streaks(tmp_path: Path):
    hist = HistoryStore(str(tmp_path / "h.db"))
    _save(hist, _report("FAIL"), "2026-11-01T10:00:00")   # 第1期 fan FAIL
    _save(hist, _report("FAIL"), "2026-11-08T10:00:00")   # 第2期 fan FAIL

    # 两期连续 FAIL → 连续期次=2
    assert hist.fail_streaks()[("核心交换", "fan_status")] == 2

    _save(hist, _report("PASS"), "2026-11-15T10:00:00")   # 第3期已修复

    # 在第3期之前看:fan 是上期遗留
    prev = hist.prev_fail_items("2026-11-15T10:00:00", ["核心交换"])
    assert ("核心交换", "fan_status") in prev
    # 修复后连续期次清零
    assert ("核心交换", "fan_status") not in hist.fail_streaks()


def test_word_review_section(tmp_path: Path):
    from docx import Document

    from patrol.reporter.word import WordReporter

    hist = HistoryStore(str(tmp_path / "h.db"))
    _save(hist, _report("FAIL"), "2026-11-01T10:00:00")  # 上期 fan FAIL

    report = _report("PASS")  # 本期已修复
    out = tmp_path / "r.docx"
    WordReporter().generate(report, out, history=hist)
    doc = Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs) + "\n" + \
        "\n".join(c.text for tb in doc.tables for r in tb.rows for c in r.cells)
    assert "上期问题复查" in text and "已解决" in text

    # 本期仍 FAIL → "仍存在"
    report2 = _report("FAIL")
    out2 = tmp_path / "r2.docx"
    WordReporter().generate(report2, out2, history=hist)
    text2 = "\n".join(c.text for tb in Document(str(out2)).tables
                      for r in tb.rows for c in r.cells)
    assert "仍存在" in text2


def test_word_no_history_skips_section(tmp_path: Path, monkeypatch):
    from docx import Document

    from patrol.reporter.word import WordReporter
    # 切到空目录:默认历史库按相对路径定位,确保证实"没有任何历史"
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path / "empty")
    out = tmp_path / "n.docx"
    WordReporter().generate(_report(), out)
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "上期问题复查" not in text  # 无历史数据时不渲染该章节


def test_excel_streak_column(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # excel 内部默认 data/ 相对路径
    (tmp_path / "data").mkdir()
    from openpyxl import load_workbook

    from patrol.reporter.excel import ExcelReporter
    hist = HistoryStore(str(tmp_path / "data/patrol_history.db"))
    _save(hist, _report("FAIL"), "2026-11-01T10:00:00")
    _save(hist, _report("FAIL"), "2026-11-08T10:00:00")

    out = tmp_path / "e.xlsx"
    ExcelReporter().generate(_report("FAIL"), out)
    ws = load_workbook(str(out))["异常跟踪"]
    assert ws.cell(row=1, column=6).value == "连续期次"
    assert ws.cell(row=2, column=6).value == 2
