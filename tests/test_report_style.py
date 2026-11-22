"""报告样式配置测试(销号清单 #10)"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.reporter.word import _style_color, load_report_style


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_default_when_no_config(sandbox):
    assert load_report_style() == {}
    c = _style_color("title_color", None)
    assert c is None  # 默认透传


def test_style_color_applied(sandbox):
    Path("config").mkdir()
    Path("config/report_style.yaml").write_text(
        "title_color: FF0000\n", encoding="utf-8")
    from docx.shared import RGBColor
    c = _style_color("title_color", RGBColor(0, 0, 0))
    assert (c[0], c[1], c[2]) == (255, 0, 0)


def test_invalid_color_falls_back(sandbox):
    Path("config").mkdir()
    Path("config/report_style.yaml").write_text(
        "title_color: xyz\n", encoding="utf-8")
    from docx.shared import RGBColor
    d = RGBColor(1, 2, 3)
    assert _style_color("title_color", d) is d


def test_vendor_company_override(sandbox):
    from patrol.models import DeviceAsset, DeviceReport, PatrolReport
    from patrol.reporter.word import build_report_meta

    Path("config").mkdir()
    Path("config/report_style.yaml").write_text(
        'vendor_company: "某某信息技术有限公司"\n', encoding="utf-8")
    report = PatrolReport(devices=[DeviceReport(asset=DeviceAsset(
        name="d", host="10.0.0.1"))])
    meta = build_report_meta(report)
    assert meta["vendor_company"] == "某某信息技术有限公司"
