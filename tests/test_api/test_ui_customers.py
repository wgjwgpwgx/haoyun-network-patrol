"""客户管理界面 + 设备表单客户归属/Super 密码 UI 测试"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from patrol.api.app import app
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"


@pytest.fixture(autouse=True)
def isolated_ui_stores(tmp_path):
    config_path = tmp_path / "devices.yaml"
    config_path.write_text("devices: []\n", encoding="utf-8")
    ds = DeviceStore(str(config_path))
    cs = CustomerStore(str(tmp_path / "customers.yaml"))
    ts = TaskStore()
    tm = TaskManager(ds, ts, str(RULES), str(tmp_path / "output"))

    import patrol.api.app as app_module
    import patrol.api.ui as ui_module
    saved = (app_module._device_store, app_module._task_store, app_module._task_manager,
             app_module._customer_store,
             ui_module._device_store, ui_module._task_store, ui_module._customer_store)
    app_module._device_store = ds
    app_module._task_store = ts
    app_module._task_manager = tm
    app_module._customer_store = cs
    ui_module._device_store = ds
    ui_module._task_store = ts
    ui_module._customer_store = cs
    yield {"ds": ds, "cs": cs, "ts": ts, "tm": tm}
    (app_module._device_store, app_module._task_store, app_module._task_manager,
     app_module._customer_store,
     ui_module._device_store, ui_module._task_store, ui_module._customer_store) = saved


@pytest.fixture
def client():
    return TestClient(app)


class TestCustomerPages:
    def test_customer_page_renders_empty(self, client):
        resp = client.get("/ui/customers")
        assert resp.status_code == 200
        assert "客户管理" in resp.text
        assert "暂无客户" in resp.text

    def test_create_customer_via_form(self, client, isolated_ui_stores):
        resp = client.post("/ui/customers/save", data={
            "name": "甲方A", "contact": "张三", "phone": "138", "remark": "VIP",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert isolated_ui_stores["cs"].get("甲方A")["contact"] == "张三"

    def test_edit_page_prefills(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方A", "contact": "张三", "phone": "", "remark": ""})
        resp = client.get(f"/ui/customers?edit={quote('甲方A')}")
        assert resp.status_code == 200
        assert 'value="张三"' in resp.text
        assert 'value="甲方A"' in resp.text

    def test_rename_customer_updates_device_refs(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方A", "contact": "", "phone": "", "remark": ""})
        client.post("/ui/devices/new", data=_device_payload(customer="甲方A"))

        # 重命名客户 → 设备归属引用同步更新
        resp = client.post("/ui/customers/save", data={
            "orig_name": "甲方A", "name": "甲方A集团",
            "contact": "", "phone": "", "remark": "",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert isolated_ui_stores["ds"].get("测试设备")["customer"] == "甲方A集团"

    def test_delete_customer(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方B", "contact": "", "phone": "", "remark": ""})
        resp = client.post(f"/ui/customers/{quote('甲方B')}/delete",
                           follow_redirects=False)
        assert resp.status_code == 303
        assert isolated_ui_stores["cs"].get("甲方B") is None


def _device_payload(**overrides) -> dict:
    payload = {
        "name": "测试设备", "customer": "", "host": "192.168.1.10",
        "vendor": "h3c", "device_type": "comware_switch", "login_method": "ssh",
        "port": 22, "web_port": 443, "username": "admin",
        "password": "secret123", "super_password": "", "timeout": 30,
        "command_timeout": 60, "enabled": "true",
    }
    payload.update(overrides)
    return payload


class TestDeviceFormCustomerAndSuper:
    def test_form_has_customer_select_and_super_field(self, client):
        resp = client.get("/ui/devices/new")
        assert resp.status_code == 200
        assert 'name="customer"' in resp.text
        assert 'name="super_password"' in resp.text

    def test_create_device_with_customer(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方A", "contact": "", "phone": "", "remark": ""})
        resp = client.post("/ui/devices/new",
                           data=_device_payload(customer="甲方A"),
                           follow_redirects=False)
        assert resp.status_code == 303
        dev = isolated_ui_stores["ds"].get("测试设备")
        assert dev["customer"] == "甲方A"

    def test_create_device_with_unknown_customer_rejected(self, client, isolated_ui_stores):
        resp = client.post("/ui/devices/new",
                           data=_device_payload(customer="不存在的客户"),
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]
        assert isolated_ui_stores["ds"].list() == []

    def test_create_device_with_super_password(self, client, isolated_ui_stores):
        client.post("/ui/devices/new",
                    data=_device_payload(super_password="super123"))
        dev = isolated_ui_stores["ds"].get("测试设备")
        assert dev["super_password"] == "super123"

    def test_edit_blank_super_keeps_old(self, client, isolated_ui_stores):
        client.post("/ui/devices/new",
                    data=_device_payload(super_password="super123"))
        name_q = quote("测试设备")
        resp = client.post(f"/ui/devices/{name_q}/edit",
                           data=_device_payload(host="192.168.1.99",
                                                password="", super_password=""),
                           follow_redirects=False)
        assert resp.status_code == 303
        dev = isolated_ui_stores["ds"].get("测试设备")
        assert dev["super_password"] == "super123"  # 留空保持
        assert dev["password"] == "secret123"
        assert dev["host"] == "192.168.1.99"

    def test_edit_form_does_not_echo_super_password(self, client, isolated_ui_stores):
        client.post("/ui/devices/new",
                    data=_device_payload(super_password="super123"))
        resp = client.get("/ui/devices/测试设备/edit")
        assert "super123" not in resp.text
        assert "已配置,留空保持不变" in resp.text

    def test_device_list_customer_filter(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方A", "contact": "", "phone": "", "remark": ""})
        client.post("/ui/devices/new", data=_device_payload(customer="甲方A"))
        client.post("/ui/devices/new", data=_device_payload(
            name="设备B", host="192.168.1.11"))

        resp = client.get("/ui/devices", params={"customer": "甲方A"})
        assert "测试设备" in resp.text
        assert "设备B" not in resp.text
        # 客户名展示在设备行
        assert "甲方A" in resp.text

    def test_dashboard_shows_customer_count(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方A", "contact": "", "phone": "", "remark": ""})
        resp = client.get("/ui")
        assert "客户总数" in resp.text
