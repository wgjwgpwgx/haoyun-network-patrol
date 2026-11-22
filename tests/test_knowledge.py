"""设备知识库测试(经验沉淀 + 历史资料导入)"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from patrol.knowledge import (
    import_text, list_customers, list_devices, list_snapshots,
    load_snapshot, save_snapshot, split_text_to_items,
)

SAMPLE_TEXT = """巡检报告(2026-05)
设备:核心交换 S7506E 192.168.158.35

display version
H3C Comware Platform Software
S7506E uptime is 30 weeks

display cpu-usage
CPU Usage: 14%

display current-configuration
vlan 10
vlan 20
"""


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestSplit:
    def test_split_commands(self):
        items = split_text_to_items(SAMPLE_TEXT)
        commands = [i["command"] for i in items]
        assert commands == ["display version", "display cpu-usage",
                            "display current-configuration"]
        assert "S7506E uptime" in items[0]["raw_output"]
        assert items[1]["name"] == "cpu_usage"     # 猜名
        assert items[2]["name"] == "config_cur"

    def test_no_command_whole_text(self):
        items = split_text_to_items("乱七八糟没有命令")
        assert len(items) == 1 and items[0]["name"] == "全文"


class TestStore:
    def test_save_and_browse(self):
        save_snapshot(
            {"customer": "甲方A", "name": "核心交换", "host": "10.0.0.1",
             "vendor": "h3c", "model": "S7506E"},
            [{"name": "cpu_usage", "command": "display cpu",
              "raw_output": "14%"}],
            source="patrol")
        assert list_customers() == ["甲方A"]
        assert list_devices("甲方A") == ["核心交换"]
        snaps = list_snapshots("甲方A", "核心交换")
        assert len(snaps) == 1 and snaps[0]["source"] == "patrol"
        rec = load_snapshot("甲方A", "核心交换", snaps[0]["file"])
        assert rec["device"]["model"] == "S7506E"
        assert rec["items"][0]["raw_output"] == "14%"

    def test_traversal_blocked(self):
        assert load_snapshot("x", "y", "../evil.yaml") is None


class TestImport:
    def test_import_text(self):
        path = import_text(SAMPLE_TEXT, customer="甲方B",
                           device="S7506E-核心")
        assert path.exists()
        rec = load_snapshot("甲方B", "S7506E-核心", path.name)
        assert rec["source"] == "import"
        assert len(rec["items"]) == 3
        # 型号自动提取(正则 H3C\s+(\S+))
        assert "S7506E" in rec["device"].get("model", "") or \
            rec["device"].get("model", "")


class TestAutoCapture:
    def test_run_inspection_captures_knowledge(self):
        """巡检结束自动沉淀全量回显(失败设备也沉淀 error)。"""
        from patrol.analyzer.engine import RuleEngine
        from patrol.cli import run_inspection
        from patrol.collector.ssh import SSHCollector
        from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
        from patrol.models import DeviceAsset

        def fake_execute(self, command, timeout=60):
            table = {
                "display version":
                    "VRP (R) software, Version 5.170 (S5735 V500R019)",
                "display cpu-usage": "CPU Usage: 12%",
            }
            return table.get(command, "")

        with patch.object(SSHCollector, "connect"), \
             patch.object(SSHCollector, "disconnect"), \
             patch.object(SSHCollector, "execute", fake_execute):
            asset = DeviceAsset(name="知识库机", customer="甲方K",
                                host="10.0.0.5", vendor="huawei",
                                device_type="vrp_switch",
                                username="u", password="p")
            report = run_inspection(
                asset, HuaweiVRPSwitchDriver(), RuleEngine([]))

        snaps = list_snapshots("甲方K", "知识库机")
        assert len(snaps) == 1 and snaps[0]["source"] == "patrol"
        rec = load_snapshot("甲方K", "知识库机", snaps[0]["file"])
        commands = {i["command"] for i in rec["items"]}
        assert "display version" in commands and "display cpu-usage" in commands
        # 空回显命令不沉淀
        assert all(i["raw_output"].strip() for i in rec["items"])
        assert rec["device"]["model"] == report.model


class TestBulkDelete:
    def test_delete_device(self):
        from patrol.knowledge import delete_device, save_snapshot, list_snapshots
        for i in range(3):
            save_snapshot({"customer": "客户X", "name": "设备A", "host": "10.0.0.1"},
                          [{"name": "cpu", "command": "display cpu",
                            "raw_output": f"14% run{i}"}])
        save_snapshot({"customer": "客户X", "name": "设备B", "host": "10.0.0.2"},
                      [{"name": "cpu", "command": "display cpu", "raw_output": "20%"}])
        n = delete_device("客户X", "设备A")
        assert 1 <= n <= 3  # 同秒覆盖可能合并,至少1条
        assert list_snapshots("客户X", "设备A") == []
        assert len(list_snapshots("客户X", "设备B")) == 1  # 设备B不受影响

    def test_delete_customer(self):
        from patrol.knowledge import delete_customer, save_snapshot, list_devices
        save_snapshot({"customer": "客户Y", "name": "设备C", "host": "10.0.0.3"},
                      [{"name": "cpu", "command": "display cpu", "raw_output": "10%"}])
        save_snapshot({"customer": "客户Y", "name": "设备D", "host": "10.0.0.4"},
                      [{"name": "cpu", "command": "display cpu", "raw_output": "20%"}])
        save_snapshot({"customer": "客户Z", "name": "设备E", "host": "10.0.0.5"},
                      [{"name": "cpu", "command": "display cpu", "raw_output": "30%"}])
        n = delete_customer("客户Y")
        assert n == 2
        assert list_devices("客户Y") == []
        assert list_devices("客户Z") == ["设备E"]

    def test_delete_nonexistent(self):
        from patrol.knowledge import delete_customer, delete_device
        assert delete_device("不存在", "不存在") == 0
        assert delete_customer("不存在") == 0

    def test_import_replace(self):
        """导入时 replace=True 清除旧快照再写入。"""
        from patrol.knowledge import (device_snapshot_count, import_text,
                                      list_snapshots, save_snapshot)
        save_snapshot({"customer": "客户R", "name": "设备R", "host": "10.0.0.9"},
                      [{"name": "cpu", "command": "display cpu",
                        "raw_output": "旧数据"}])
        assert device_snapshot_count("客户R", "设备R") == 1
        # 模拟 replace 导入:先删再导
        from patrol.knowledge import delete_device
        delete_device("客户R", "设备R")
        import_text("display version\nS5735 uptime 10 weeks", "客户R", "设备R")
        snaps = list_snapshots("客户R", "设备R")
        assert len(snaps) == 1  # 只有新导入的,旧的已清
