"""历史数据存储测试"""
from __future__ import annotations

import pytest

from patrol.storage.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(str(tmp_path / "test.db"))


class TestSaveRun:
    def test_save_and_retrieve(self, store):
        run_id = store.save_run(
            device_name="sw1",
            device_host="10.0.0.1",
            device_type="s7506e",
            vendor="h3c",
            customer="客户A",
            project="项目1",
            pass_count=5,
            fail_count=2,
            unknown_count=1,
            check_items=[
                {"name": "cpu", "category": "CPU", "status": "PASS", "severity": "critical", "message": "ok", "suggestion": ""},
                {"name": "telnet", "category": "管理", "status": "FAIL", "severity": "warning", "message": "Telnet 启用", "suggestion": "关闭 Telnet"},
            ],
        )
        assert run_id > 0

        detail = store.get_run_detail(run_id)
        assert detail is not None
        assert detail["device_name"] == "sw1"
        assert detail["customer"] == "客户A"
        assert len(detail["check_items"]) == 2

    def test_save_with_error(self, store):
        run_id = store.save_run(
            device_name="sw1", device_host="10.0.0.1",
            device_type="s7506e", vendor="h3c",
            customer="", project="",
            pass_count=0, fail_count=0, unknown_count=0,
            check_items=[], error="SSH 连接失败",
        )
        detail = store.get_run_detail(run_id)
        assert detail["error"] == "SSH 连接失败"


class TestGetRuns:
    def test_filter_by_device(self, store):
        store.save_run(device_name="sw1", device_host="10.0.0.1", device_type="s7506e", vendor="h3c", customer="", project="", pass_count=1, fail_count=0, unknown_count=0, check_items=[])
        store.save_run(device_name="sw2", device_host="10.0.0.2", device_type="s7506e", vendor="h3c", customer="", project="", pass_count=2, fail_count=0, unknown_count=0, check_items=[])

        runs = store.get_runs(device_name="sw1")
        assert len(runs) == 1
        assert runs[0]["device_name"] == "sw1"

    def test_filter_by_customer(self, store):
        store.save_run(device_name="sw1", device_host="10.0.0.1", device_type="s7506e", vendor="h3c", customer="客户A", project="项目1", pass_count=1, fail_count=0, unknown_count=0, check_items=[])
        store.save_run(device_name="sw2", device_host="10.0.0.2", device_type="s7506e", vendor="h3c", customer="客户B", project="项目2", pass_count=1, fail_count=0, unknown_count=0, check_items=[])

        runs = store.get_runs(customer="客户A")
        assert len(runs) == 1


class TestTrend:
    def test_trend_data(self, store):
        for i in range(5):
            store.save_run(device_name="sw1", device_host="10.0.0.1", device_type="s7506e", vendor="h3c", customer="", project="", pass_count=10 - i, fail_count=i, unknown_count=0, check_items=[])

        trend = store.get_trend("sw1", limit=3)
        assert len(trend) == 3
        # 按时间正序
        assert trend[0]["fail_count"] <= trend[-1]["fail_count"]


class TestCustomerSummary:
    def test_summary(self, store):
        store.save_run(device_name="sw1", device_host="10.0.0.1", device_type="s7506e", vendor="h3c", customer="客户A", project="项目1", pass_count=5, fail_count=2, unknown_count=0, check_items=[])
        store.save_run(device_name="sw2", device_host="10.0.0.2", device_type="s7506e", vendor="h3c", customer="客户A", project="项目1", pass_count=8, fail_count=1, unknown_count=0, check_items=[])

        summary = store.get_summary_by_customer()
        assert len(summary) == 1
        assert summary[0]["customer"] == "客户A"
        assert summary[0]["run_count"] == 2
