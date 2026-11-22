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
