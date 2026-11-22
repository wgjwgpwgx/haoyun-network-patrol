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
from patrol.models import DeviceReport

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"

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


def _fake_run(assets_seen):
    """run_inspection 替身:记录采集顺序,返回带 error 的设备报告(不连真机)。"""

    def run(asset, driver, engine):
        assets_seen.append(asset)
        return DeviceReport(asset=asset, error="模拟采集失败")

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

        t = _wait_done(ts, out.task_id)
        assert t["status"] == "completed", t.get("error")
        filename = t["report_file"]
        assert "2台设备合并" in filename

        outdir = tmp_path / "output"
        html = (outdir / filename).read_text(encoding="utf-8")
        assert "核心交换机" in html and "汇聚交换机" in html

        # 伴生 JSON 为同一份报告数据,含两台设备
        sidecar = (outdir / filename).with_suffix(".json")
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert [d["name"] for d in data["devices"]] == ["核心交换机", "汇聚交换机"]

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
