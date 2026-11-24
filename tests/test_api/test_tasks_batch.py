"""合并巡检任务测试:一次选 N 台 → 一个任务、一份整体报告(乙方交付形态)"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import patrol.drivers  # noqa: F401  注册全部驱动
import patrol.api.tasks as tasks_module
from patrol.api.store import DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from patrol.models import CheckItem, CheckStatus, DeviceReport

REPO_CONFIG = Path(__file__).parent.parent.parent / "config"
RULES = REPO_CONFIG / "rules" / "default.yaml"

DEVICE_A = {"name": "核心交换机", "host": "10.0.0.1", "vendor": "h3c",
            "device_type": "comware_switch", "username": "u", "password": "p"}
DEVICE_B = {"name": "汇聚交换机", "host": "10.0.0.2", "vendor": "h3c",
            "device_type": "comware_switch", "username": "u", "password": "p"}


@pytest.fixture
def manager(tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text("devices: []\n", encoding="utf-8")
    ds = DeviceStore(str(config))
    ts = TaskStore()
    tm = TaskManager(ds, ts, str(RULES), str(tmp_path / "output"))
    return ds, ts, tm


def _fake_run(assets_seen, failing=()):
    """run_inspection 替身:不连真机。failing 中的设备返回采集失败,其余返回一条通过项。"""

    def run(asset, driver, engine):
        assets_seen.append(asset)
        if asset.name in failing:
            return DeviceReport(asset=asset, error="模拟采集失败")
        return DeviceReport(asset=asset, check_items=[CheckItem(
            name="cpu_usage", category="CPU", command="display cpu-usage",
            raw_output="CPU utilization in five seconds: 12%",
            status=CheckStatus.PASS, message="ok",
            details={"usage_percent": 12})])

    return run


def _wait_done(ts, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = ts.get(task_id)
        if t.get("status") in ("completed", "failed"):
            return t
        time.sleep(0.05)
    return ts.get(task_id)


class TestBatchTask:
    def test_two_devices_one_merged_report(self, manager, monkeypatch, tmp_path):
        ds, ts, tm = manager
        ds.create(dict(DEVICE_A))
        ds.create(dict(DEVICE_B))

        assets, saved = [], []
        monkeypatch.setattr(tasks_module, "run_inspection", _fake_run(assets))
        monkeypatch.setattr(
            "patrol.storage.history.HistoryStore.save_run",
            lambda self, **kw: saved.append(kw.get("device_name")))

        out = tm.create_batch_task(["核心交换机", "汇聚交换机"])
        assert "合并巡检" in out.device_name
        assert out.device_host == "共 2 台"
        assert out.status in ("pending", "running")
        assert out.device_names == ["核心交换机", "汇聚交换机"]

        t = _wait_done(ts, out.task_id)
        assert t["status"] == "completed", t.get("error")
        assert t["error_count"] == 0
        filename = t["report_file"]
        assert "2台设备合并" in filename

        outdir = tmp_path / "output"
        html = (outdir / filename).read_text(encoding="utf-8")
        assert "核心交换机" in html and "汇聚交换机" in html

        # 伴生 JSON 为同一份报告数据,含两台设备
        sidecar = (outdir / filename).with_suffix(".json")
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert [d["name"] for d in data["devices"]] == ["核心交换机", "汇聚交换机"]
        assert all(d["collected_at"] for d in data["devices"])

        # 两台各采集一次;巡检历史按设备逐条入库
        assert [a.name for a in assets] == ["核心交换机", "汇聚交换机"]
        assert sorted(saved) == ["核心交换机", "汇聚交换机"]

    def test_single_device_keeps_host_filename(self, manager, monkeypatch):
        ds, ts, tm = manager
        ds.create(dict(DEVICE_A))
        monkeypatch.setattr(tasks_module, "run_inspection", _fake_run([]))
        monkeypatch.setattr(
            "patrol.storage.history.HistoryStore.save_run",
            lambda self, **kw: None)

        out = tm.create_task("核心交换机")  # 单设备兼容入口仍可用
        assert out.device_name == "核心交换机"
        t = _wait_done(ts, out.task_id)
        assert t["status"] == "completed", t.get("error")
        assert t["report_file"].startswith("patrol_10.0.0.1_")

    def test_invalid_names_raise(self, manager):
        ds, ts, tm = manager
        with pytest.raises(KeyError):
            tm.create_batch_task(["不存在"])
        with pytest.raises(KeyError):
            tm.create_batch_task([])


class TestFailureIsReportedHonestly:
    """采集失败不能显示成"完成";但单台失败也不能拖垮整批。"""

    def test_all_devices_unreachable_is_failed_and_keeps_report(
            self, manager, monkeypatch, tmp_path):
        ds, ts, tm = manager
        ds.create(dict(DEVICE_A))
        ds.create(dict(DEVICE_B))
        names = ["核心交换机", "汇聚交换机"]
        monkeypatch.setattr(tasks_module, "run_inspection", _fake_run([], failing=names))
        monkeypatch.setattr(
            "patrol.storage.history.HistoryStore.save_run", lambda self, **kw: None)

        out = tm.create_batch_task(names)
        t = _wait_done(ts, out.task_id)
        assert t["status"] == "failed"
        assert "全部 2 台设备无法采集" in t["error"]
        assert t["error_count"] == 2
        # 报告仍然保留,用户可点开看各台原因
        assert t["report_file"] and (tmp_path / "output" / t["report_file"]).exists()

    def test_partial_failure_completes_with_error_count(self, manager, monkeypatch):
        ds, ts, tm = manager
        ds.create(dict(DEVICE_A))
        ds.create(dict(DEVICE_B))
        monkeypatch.setattr(
            tasks_module, "run_inspection", _fake_run([], failing=["汇聚交换机"]))
        monkeypatch.setattr(
            "patrol.storage.history.HistoryStore.save_run", lambda self, **kw: None)

        out = tm.create_batch_task(["核心交换机", "汇聚交换机"])
        t = _wait_done(ts, out.task_id)
        assert t["status"] == "completed"
        assert t["error_count"] == 1
        assert not t["error"]

    def test_one_uninspectable_device_does_not_fail_the_batch(self, manager, monkeypatch):
        ds, ts, tm = manager
        ds.create(dict(DEVICE_A))
        ds.create({**DEVICE_B, "device_type": "不存在的类型"})  # 如台账导入缺类型
        monkeypatch.setattr(tasks_module, "run_inspection", _fake_run([]))
        monkeypatch.setattr(
            "patrol.storage.history.HistoryStore.save_run", lambda self, **kw: None)

        out = tm.create_batch_task(["核心交换机", "汇聚交换机"])
        t = _wait_done(ts, out.task_id)
        assert t["status"] == "completed", t.get("error")
        assert t["error_count"] == 1

    def test_reconcile_marks_leftover_running_task(self, manager):
        ds, ts, tm = manager
        ts.create("t-running", {"task_id": "t-running", "status": "running"})
        ts.create("t-pending", {"task_id": "t-pending", "status": "pending"})
        ts.create("t-done", {"task_id": "t-done", "status": "completed"})

        assert tm.reconcile_interrupted() == 2
        assert ts.get("t-running")["status"] == "failed"
        assert "中断" in ts.get("t-pending")["error"]
        assert ts.get("t-done")["status"] == "completed"


class TestHistoryAndRules:
    def test_history_saved_before_report_so_trends_include_this_run(
            self, manager, monkeypatch):
        ds, ts, tm = manager
        ds.create(dict(DEVICE_A))
        order = []
        monkeypatch.setattr(tasks_module, "run_inspection", _fake_run([]))
        monkeypatch.setattr(
            "patrol.storage.history.HistoryStore.save_run",
            lambda self, **kw: order.append("save_run"))
        monkeypatch.setattr(
            "patrol.reporter.html.HTMLReporter.generate",
            lambda self, report, path: order.append("render"))

        out = tm.create_batch_task(["核心交换机"])
        _wait_done(ts, out.task_id)
        assert order == ["save_run", "render"]

    def test_rules_dir_merges_vendor_rules_with_dengbao_off(self, manager):
        """规则目录:各厂商专项规则全部生效、等保基线包默认关闭、专用排在通配之前。"""
        ds, ts, tm = manager
        tm_dir = TaskManager(ds, ts, str(REPO_CONFIG / "rules"), "output")
        rules = tm_dir._engine.rules

        vendors = {v for r in rules if r.vendors != ["*"] for v in r.vendors}
        assert {"zte", "maipu", "ruijie", "huawei", "sangfor", "dptech", "h3c"} <= vendors
        check_names = {r.check_name for r in rules}
        assert {"fan_status", "power_status", "logbuffer", "snmp_community",
                "vty_auth", "stp_status"} <= check_names  # 原先恒为 UNKNOWN 的检查项
        # 等保基线包默认不参与(enabled: false)
        assert not any(r.id.startswith("D0") for r in rules)
        assert not {"login_lock", "password_policy"} & check_names
        # 专用规则排在通配规则之前 → 厂商专项规则可覆盖默认阈值
        specific = [i for i, r in enumerate(rules) if "*" not in r.vendors]
        generic = [i for i, r in enumerate(rules) if "*" in r.vendors]
        assert specific and generic and max(specific) < min(generic)

        # 引擎取到的第一条适用规则是厂商专项规则,而非通配兜底
        from patrol.analyzer.engine import RuleEngine
        from patrol.drivers.base import ParsedResult
        engine = RuleEngine(rules)
        item = engine.evaluate(
            ParsedResult(name="cpu_usage", category="CPU", command="show cpu",
                         raw_output="", parsed={"usage_percent": 85}, success=True),
            vendor="zte", device_type="zxr10_switch")
        assert item.details["rule_id"] == "ZT001"
