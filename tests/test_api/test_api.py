"""API 接口测试 - 使用 FastAPI TestClient"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrol.api.app import app, _device_store, _task_store, _task_manager
from patrol.api.store import DeviceStore, TaskStore
from patrol.api.tasks import TaskManager


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    """为每个测试创建隔离的存储实例。"""
    config_path = tmp_path / "devices.yaml"
    config_path.write_text("devices: []\n", encoding="utf-8")
    rules_path = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"
    output_dir = tmp_path / "output"

    ds = DeviceStore(str(config_path))
    ts = TaskStore()
    tm = TaskManager(ds, ts, str(rules_path), str(output_dir))

    def _fake_inspection(asset, driver, engine, incremental=False):
        """巡检替身:即时返回空报告,不让任务线程经 netmiko 连接外部地址。"""
        from patrol.models import DeviceReport
        return DeviceReport(asset=asset)

    monkeypatch.setattr("patrol.api.tasks.run_inspection", _fake_inspection)

    # 替换全局实例
    import patrol.api.app as app_module
    old_ds = app_module._device_store
    old_ts = app_module._task_store
    old_tm = app_module._task_manager
    app_module._device_store = ds
    app_module._task_store = ts
    app_module._task_manager = tm

    yield {"device_store": ds, "task_store": ts, "task_manager": tm, "output_dir": output_dir}

    app_module._device_store = old_ds
    app_module._task_store = old_ts
    app_module._task_manager = old_tm
    tm.shutdown()


@pytest.fixture
def client():
    return TestClient(app)


SAMPLE_DEVICE = {
    "name": "测试交换机",
    "host": "192.168.1.1",
    "vendor": "h3c",
    "device_type": "comware_switch",
    "port": 22,
    "username": "admin",
    "password": "secret123",
    "enabled": True,
    "timeout": 30,
    "command_timeout": 60,
}


# ── 设备列表查询 ────────────────────────────────────────────────


class TestListDevices:
    def test_empty_list(self, client):
        resp = client.get("/devices")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.get("/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "测试交换机"


# ── 新增设备 ────────────────────────────────────────────────────


class TestCreateDevice:
    def test_create_success(self, client):
        resp = client.post("/devices", json=SAMPLE_DEVICE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "测试交换机"
        assert data["host"] == "192.168.1.1"
        # 密码不能出现在响应中
        assert "password" not in data

    def test_create_duplicate(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.post("/devices", json=SAMPLE_DEVICE)
        assert resp.status_code == 409

    def test_create_missing_name(self, client):
        bad = {**SAMPLE_DEVICE, "name": ""}
        resp = client.post("/devices", json=bad)
        assert resp.status_code == 422

    def test_create_missing_password(self, client):
        bad = {k: v for k, v in SAMPLE_DEVICE.items() if k != "password"}
        resp = client.post("/devices", json=bad)
        assert resp.status_code == 422

    def test_create_invalid_port(self, client):
        bad = {**SAMPLE_DEVICE, "port": 0}
        resp = client.post("/devices", json=bad)
        assert resp.status_code == 422

    def test_create_port_too_large(self, client):
        bad = {**SAMPLE_DEVICE, "port": 70000}
        resp = client.post("/devices", json=bad)
        assert resp.status_code == 422


# ── 修改设备 ────────────────────────────────────────────────────


class TestUpdateDevice:
    def test_update_success(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.put("/devices/测试交换机", json={"host": "10.0.0.1"})
        assert resp.status_code == 200
        assert resp.json()["host"] == "10.0.0.1"

    def test_update_not_found(self, client):
        resp = client.put("/devices/不存在", json={"host": "10.0.0.1"})
        assert resp.status_code == 404

    def test_update_rename(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.put("/devices/测试交换机", json={"name": "新名字"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名字"

    def test_update_password_not_returned(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.put("/devices/测试交换机", json={"password": "newpass"})
        assert resp.status_code == 200
        assert "password" not in resp.json()


# ── 删除设备 ────────────────────────────────────────────────────


class TestDeleteDevice:
    def test_delete_success(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.delete("/devices/测试交换机")
        assert resp.status_code == 204

    def test_delete_not_found(self, client):
        resp = client.delete("/devices/不存在")
        assert resp.status_code == 404

    def test_delete_verifies_gone(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        client.delete("/devices/测试交换机")
        resp = client.get("/devices")
        assert len(resp.json()) == 0


# ── 巡检任务 ────────────────────────────────────────────────────


class TestCreateTask:
    def test_create_task(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        resp = client.post("/tasks", json={"device_name": "测试交换机"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["device_name"] == "测试交换机"
        assert data["status"] in ("pending", "running")
        assert "task_id" in data

    def test_create_task_device_not_found(self, client):
        resp = client.post("/tasks", json={"device_name": "不存在"})
        assert resp.status_code == 404

    def test_create_task_missing_device_name(self, client):
        resp = client.post("/tasks", json={})
        assert resp.status_code == 422


class TestGetTask:
    def test_get_task(self, client):
        client.post("/devices", json=SAMPLE_DEVICE)
        create_resp = client.post("/tasks", json={"device_name": "测试交换机"})
        task_id = create_resp.json()["task_id"]

        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == task_id

    def test_get_task_not_found(self, client):
        resp = client.get("/tasks/nonexistent")
        assert resp.status_code == 404


# ── 报告 ────────────────────────────────────────────────────────


class TestReports:
    def test_get_report_task_not_completed(self, client, isolated_stores):
        """任务未完成时不能查看报告。"""
        client.post("/devices", json=SAMPLE_DEVICE)
        create_resp = client.post("/tasks", json={"device_name": "测试交换机"})
        task_id = create_resp.json()["task_id"]

        resp = client.get(f"/tasks/{task_id}/report")
        # 任务可能还在 running 或已 failed（连接不上设备）
        assert resp.status_code in (400, 404)

    def test_download_report_not_found(self, client):
        resp = client.get("/reports/nonexistent.html")
        assert resp.status_code == 404

    def test_download_report_path_traversal(self, client):
        # URL 中的 ../ 会被 HTTP 客户端规范化，可能到达 400 或 404
        resp = client.get("/reports/../../../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_download_report_with_dots(self, client):
        resp = client.get("/reports/..%2F..%2Fetc%2Fpasswd")
        # FastAPI 会解码 %2F，但我们的检查会拦截 ..
        assert resp.status_code in (400, 404)
