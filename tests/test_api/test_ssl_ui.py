"""设备表单 verify_ssl 字段闭环测试(问题 006:勾选跳过证书校验)"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrol.api.app import app
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"


@pytest.fixture(autouse=True)
def stores(tmp_path):
    """隔离 store,并同步替换 app 与 ui 两个模块的全局引用(同 test_ui.py)。"""
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
    yield ds
    (app_module._device_store, app_module._task_store, app_module._task_manager,
     app_module._customer_store,
     ui_module._device_store, ui_module._task_store, ui_module._customer_store) = saved


@pytest.fixture
def client():
    return TestClient(app)


def _payload(**overrides) -> dict:
    data = {
        "name": "ngaf1", "host": "10.2.2.2", "vendor": "sangfor",
        "device_type": "ngaf_firewall", "login_method": "api",
        "port": 22, "web_port": 443, "username": "admin",
        "password": "pw", "super_password": "", "timeout": 30,
        "command_timeout": 120, "enabled": "true",
    }
    data.update(overrides)
    return data


class TestVerifySslForm:
    def test_default_is_verify_on(self, client, stores):
        r = client.post("/ui/devices/new", data=_payload(), follow_redirects=False)
        assert r.status_code == 303
        assert stores.get("ngaf1")["verify_ssl"] is True

    def test_skip_tls_checkbox_disables_verify(self, client, stores):
        r = client.post(
            "/ui/devices/new", data=_payload(skip_tls_verify="true"),
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert stores.get("ngaf1")["verify_ssl"] is False

    def test_edit_form_renders_checkbox_checked(self, client, stores):
        client.post(
            "/ui/devices/new", data=_payload(skip_tls_verify="true"),
            follow_redirects=False,
        )
        r = client.get("/ui/devices/ngaf1/edit")
        assert r.status_code == 200
        assert "跳过 HTTPS 证书校验" in r.text
        seg = r.text.split('id="skipTlsVerify"', 1)[1][:120]
        assert "checked" in seg

    def test_edit_form_checkbox_unchecked_by_default(self, client, stores):
        client.post("/ui/devices/new", data=_payload(), follow_redirects=False)
        r = client.get("/ui/devices/ngaf1/edit")
        seg = r.text.split('id="skipTlsVerify"', 1)[1][:120]
        assert "checked" not in seg
