"""客户信息模块测试:存储层 + API + 设备归属/Super 密码透传与脱敏"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from patrol.api.app import app
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from pathlib import Path

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
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
    yield {"ds": ds, "cs": cs}
    (app_module._device_store, app_module._task_store, app_module._task_manager,
     app_module._customer_store,
     ui_module._device_store, ui_module._task_store, ui_module._customer_store) = saved


@pytest.fixture
def client():
    return TestClient(app)


# ── 存储层 ────────────────────────────────────────────────────


class TestCustomerStore:
    def test_crud_roundtrip(self, isolated_stores, tmp_path):
        cs: CustomerStore = isolated_stores["cs"]
        cs.create({"name": "甲公司", "contact": "张三", "phone": "13800000000", "remark": ""})
        assert cs.get("甲公司")["contact"] == "张三"

        cs.update("甲公司", {"contact": "李四"})
        assert cs.get("甲公司")["contact"] == "李四"

        # 重命名
        cs.update("甲公司", {"name": "甲公司集团"})
        assert cs.get("甲公司") is None
        assert cs.get("甲公司集团")["name"] == "甲公司集团"

        cs.delete("甲公司集团")
        assert cs.list() == []

    def test_duplicate_rejected(self, isolated_stores):
        cs: CustomerStore = isolated_stores["cs"]
        cs.create({"name": "甲公司", "contact": "", "phone": "", "remark": ""})
        with pytest.raises(ValueError):
            cs.create({"name": "甲公司", "contact": "", "phone": "", "remark": ""})

    def test_persistence(self, tmp_path):
        path = tmp_path / "customers.yaml"
        cs = CustomerStore(str(path))
        cs.create({"name": "乙公司", "contact": "", "phone": "", "remark": "VIP"})
        cs2 = CustomerStore(str(path))  # 重新加载
        assert cs2.get("乙公司")["remark"] == "VIP"


# ── REST API ──────────────────────────────────────────────────


class TestCustomersAPI:
    def test_create_list_update_delete(self, client):
        r = client.post("/customers", json={
            "name": "丙公司", "contact": "王五", "phone": "139", "remark": "x"})
        assert r.status_code == 201
        assert r.json()["name"] == "丙公司"

        assert client.get("/customers").json()[0]["contact"] == "王五"

        r = client.put("/customers/丙公司", json={"contact": "赵六"})
        assert r.status_code == 200 and r.json()["contact"] == "赵六"

        assert client.delete("/customers/丙公司").status_code == 204
        assert client.get("/customers").json() == []

    def test_duplicate_409(self, client):
        client.post("/customers", json={"name": "丁公司"})
        assert client.post("/customers", json={"name": "丁公司"}).status_code == 409

    def test_missing_404(self, client):
        assert client.put("/customers/不存在", json={"contact": "x"}).status_code == 404
        assert client.delete("/customers/不存在").status_code == 404


class TestDeviceCustomerAndSuperPassword:
    def test_device_fields_passthrough_and_masking(self, client):
        """设备创建带 customer/super_password:customer 返回,密码类字段不返回。"""
        client.post("/customers", json={"name": "甲方A"})
        r = client.post("/devices", json={
            "name": "设备1", "customer": "甲方A", "host": "192.168.1.1",
            "username": "u", "password": "login-pw", "super_password": "super-pw",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["customer"] == "甲方A"
        assert "password" not in body
        assert "super_password" not in body
        assert "super-pw" not in str(body)

        # 列表同样脱敏
        listing = client.get("/devices").json()
        assert listing[0]["customer"] == "甲方A"
        assert "super_password" not in listing[0]

    def test_update_super_password(self, client, isolated_stores):
        client.post("/devices", json={
            "name": "设备2", "host": "192.168.1.2",
            "username": "u", "password": "p", "super_password": "old-super"})
        client.put("/devices/设备2", json={"super_password": "new-super"})
        dev = isolated_stores["ds"].get("设备2")
        assert dev["super_password"] == "new-super"
