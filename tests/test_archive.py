"""报告归档测试(销号清单 #11)"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.models import DeviceAsset, DeviceReport, PatrolReport
from patrol.utils.archive import archive_report


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_archive_with_customer(sandbox):
    src = Path("output") / "巡检台账_X.xlsx"
    src.parent.mkdir(exist_ok=True)
    src.write_bytes(b"fake")
    dest = archive_report(src, "甲方A公司")
    assert dest is not None and dest.exists()
    assert dest.parent.parent.name == "甲方A公司"
    assert len(dest.parent.name) == 7  # YYYY-MM


def test_archive_without_customer(sandbox):
    src = Path("output") / "a.docx"
    src.parent.mkdir(exist_ok=True)
    src.write_bytes(b"x")
    assert archive_report(src, "") is None
    assert archive_report(Path("output/不存在.docx"), "C") is None
