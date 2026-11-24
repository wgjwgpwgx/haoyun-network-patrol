"""配置快照与 diff 测试(销号清单 #9)"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport
from patrol.utils.config_snapshot import (
    list_snapshots, previous_snapshot, save_config_snapshot,
)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


CFG_V1 = "hostname sw\nvlan 10\nvlan 20\n"
CFG_V2 = "hostname sw\nvlan 10\nvlan 30\n"


def test_snapshot_save_and_prev(sandbox):
    assert save_config_snapshot("核心交换", CFG_V1) is not None
    assert save_config_snapshot("核心交换", "") is None  # 空不存
    assert len(list_snapshots("核心交换")) >= 1  # 同秒重复保存按同名覆盖

    prev = previous_snapshot("核心交换", CFG_V2)
    assert prev is not None and prev[0] == CFG_V1

    # 唯一快照与本期相同 → 无差异历史,返回 None
    assert previous_snapshot("核心交换", CFG_V1) is None
    # 无历史设备
    assert previous_snapshot("不存在", CFG_V1) is None


def test_word_config_diff_section(sandbox):
    from docx import Document

    from patrol.reporter.word import WordReporter

    save_config_snapshot("核心交换", CFG_V1)

    dev = DeviceReport(asset=DeviceAsset(name="核心交换", host="10.0.0.1"))
    dev.check_items.append(CheckItem(
        name="config_cur", category="配置", command="display current",
        raw_output=CFG_V2, status=CheckStatus.PASS, message="ok"))
    out = sandbox / "r.docx"
    WordReporter().generate(PatrolReport(devices=[dev]), out)

    doc = Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "配置变更对比" in text
    assert "-vlan 20" in text and "+vlan 30" in text


def test_word_no_prev_skips_section(sandbox):
    from docx import Document

    from patrol.reporter.word import WordReporter

    dev = DeviceReport(asset=DeviceAsset(name="新设备", host="10.0.0.2"))
    dev.check_items.append(CheckItem(
        name="config_cur", category="配置", command="c", raw_output=CFG_V1,
        status=CheckStatus.PASS, message=""))
    out = sandbox / "n.docx"
    WordReporter().generate(PatrolReport(devices=[dev]), out)
    assert "配置变更对比" not in "\n".join(
        p.text for p in Document(str(out)).paragraphs)


SECRET_CFG = "vlan 10\n local-user admin password simple S3cretK3y\n"


def _docx_text(path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
        c.text for tb in doc.tables for r in tb.rows for c in r.cells)


def test_snapshot_on_disk_is_redacted(sandbox):
    save_config_snapshot("核心交换", SECRET_CFG)
    on_disk = list_snapshots("核心交换")[-1].read_text(encoding="utf-8")
    assert "S3cretK3y" not in on_disk and "vlan 10" in on_disk


def test_export_via_report_json_does_not_diff_report_against_itself(sandbox):
    """界面导出从报告 JSON(已脱敏)重建:本期快照就是本期,不得被当成"上期"
    而报出一堆由脱敏造成的"配置变更"。"""
    import json

    from patrol.reporter.html import HTMLReporter
    from patrol.reporter.rebuild import rebuild_report
    from patrol.reporter.word import WordReporter

    save_config_snapshot("核心交换", SECRET_CFG)  # 巡检时写入的本期快照
    dev = DeviceReport(asset=DeviceAsset(name="核心交换", host="10.0.0.1"))
    dev.check_items.append(CheckItem(
        name="config_cur", category="配置", command="display current",
        raw_output=SECRET_CFG, status=CheckStatus.PASS, message="ok"))
    HTMLReporter().generate(PatrolReport(devices=[dev]), sandbox / "r.html")
    rebuilt = rebuild_report(
        json.loads((sandbox / "r.json").read_text(encoding="utf-8")))
    out = sandbox / "r.docx"
    WordReporter().generate(rebuilt, out)
    assert "配置变更对比" not in _docx_text(out)


def test_word_config_diff_never_prints_secrets(sandbox):
    """早期快照文件是未脱敏原文:diff 的两侧都必须先脱敏再输出。"""
    from patrol.reporter.word import WordReporter

    snap_dir = Path("output/configs/核心交换")
    snap_dir.mkdir(parents=True)
    (snap_dir / "20260101_000000.txt").write_text(
        "vlan 10\n local-user admin password simple OldK3y\n", encoding="utf-8")
    current = "vlan 20\n local-user admin password simple NewK3y\n"
    (snap_dir / "20260102_000000.txt").write_text(current, encoding="utf-8")

    dev = DeviceReport(asset=DeviceAsset(name="核心交换", host="10.0.0.1"))
    dev.check_items.append(CheckItem(
        name="config_cur", category="配置", command="display current",
        raw_output=current, status=CheckStatus.PASS, message="ok"))
    out = sandbox / "d.docx"
    WordReporter().generate(PatrolReport(devices=[dev]), out)
    text = _docx_text(out)
    assert "配置变更对比" in text
    assert "-vlan 10" in text and "+vlan 20" in text
    assert "OldK3y" not in text and "NewK3y" not in text
