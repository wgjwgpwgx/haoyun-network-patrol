"""P1 第三批功能测试:增量巡检/知识库搜索/一键交接"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestIncremental:
    ALL = ["device_info", "cpu_usage", "memory_usage", "temperature",
           "power_status", "fan_status", "lldp_neighbor", "config_cur",
           "storage", "ospf_neighbor", "arp_count"]
    CORE = {"device_info", "cpu_usage", "memory_usage", "temperature",
            "power_status", "fan_status"}

    @staticmethod
    def _checks():
        from patrol.drivers.base import CheckCommand
        return [CheckCommand(name=n, category="x", command=f"cmd_{n}")
                for n in TestIncremental.ALL]

    @staticmethod
    def _save_history(statuses: dict[str, str]) -> None:
        from patrol.storage.history import HistoryStore
        HistoryStore().save_run(
            device_name="d", device_host="192.0.2.1", device_type="vrp_switch",
            vendor="huawei", customer="", project="", run_time="2026-11-01T10:00:00",
            pass_count=0, fail_count=0, unknown_count=0,
            check_items=[{"name": n, "status": s} for n, s in statuses.items()])

    @classmethod
    def _selected(cls) -> set[str]:
        from patrol.incremental import get_incremental_checks
        return {c.name for c in get_incremental_checks("huawei", "vrp_switch", cls._checks())}

    def test_no_history_runs_everything(self):
        assert self._selected() == set(self.ALL)  # 首次巡检没有可参考的历史,跑全量

    def test_core_plus_checks_that_failed_or_were_unknown_last_time(self):
        """此前增量模式因访问不存在的属性而永远退化为全量,这条路径从未真正执行过。"""
        self._save_history({"cpu_usage": "PASS", "fan_status": "FAIL",
                            "ospf_neighbor": "UNKNOWN", "lldp_neighbor": "PASS",
                            "config_cur": "PASS"})
        assert self._selected() == self.CORE | {"fan_status", "ospf_neighbor"}

    def test_all_pass_last_time_runs_core_only(self):
        self._save_history({"cpu_usage": "PASS", "lldp_neighbor": "PASS",
                            "config_cur": "PASS"})
        assert self._selected() == self.CORE

    def test_quick_mode_field(self):
        from patrol.models import DeviceAsset
        a = DeviceAsset(name="t", host="10.0.0.1")
        assert a.quick_mode is False  # 默认全量


class TestKnowledgeSearch:
    def test_search(self):
        from patrol.knowledge import save_snapshot, search

        save_snapshot(
            {"customer": "客户S", "name": "交换S1", "host": "10.0.0.1"},
            [{"name": "cpu_usage", "command": "display cpu-usage",
              "raw_output": "CPU Usage: 14% Huawei S5735"}],
            source="patrol")
        results = search("S5735")
        assert len(results) == 1
        assert results[0]["customer"] == "客户S"
        assert "CPU" in results[0]["snippet"]

    def test_search_no_match(self):
        from patrol.knowledge import search
        assert search("不存在的关键词xyz") == []
        assert search("") == []


class TestExportImport:
    def test_export_creates_zip(self):
        from patrol.knowledge import export_all, save_snapshot

        save_snapshot(
            {"customer": "客户E", "name": "设备E", "host": "10.0.0.1"},
            [{"name": "cpu", "command": "display cpu", "raw_output": "10%"}])
        Path("config/parser_copilot").mkdir(parents=True, exist_ok=True)
        Path("config/parser_copilot/huawei_vrp.yaml").write_text(
            "parsers: {}", encoding="utf-8")
        Path("config/report_style.yaml").write_text("title_color: FF0000",
                                                    encoding="utf-8")

        zip_path = export_all()
        assert zip_path.exists() and zip_path.suffix == ".zip"

        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert any(n.startswith("knowledge/") for n in names)
        assert any(n.startswith("parser_copilot/") for n in names)
        assert "config/report_style.yaml" in names

    def test_roundtrip(self):
        from patrol.knowledge import export_all, import_all, save_snapshot, list_devices

        save_snapshot(
            {"customer": "客户R", "name": "设备R", "host": "10.0.0.9"},
            [{"name": "cpu", "command": "display cpu", "raw_output": "20%"}])
        zip_path = export_all()

        # 清空知识库再导入
        import shutil
        from patrol.knowledge import KNOWLEDGE_DIR
        if KNOWLEDGE_DIR.exists():
            shutil.rmtree(KNOWLEDGE_DIR)
        assert list_devices("客户R") == []

        counts = import_all(zip_path)
        assert counts["knowledge"] >= 1
        assert list_devices("客户R") == ["设备R"]


class TestExportRoute:
    def test_export_endpoint(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        from fastapi.testclient import TestClient
        import patrol.api.app as am
        r = TestClient(am.app).post("/ui/knowledge/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
