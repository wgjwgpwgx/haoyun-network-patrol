"""网页版批量导入流程 + Excel 台账下载测试"""
from __future__ import annotations

import io
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from patrol.api.app import app
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from pathlib import Path

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "devices.yaml").write_text("devices: []", encoding="utf-8")
    (cfg / "customers.yaml").write_text("customers: []", encoding="utf-8")
    (tmp_path / "output").mkdir()

    ds = DeviceStore(str(cfg / "devices.yaml"))
    cs = CustomerStore(str(cfg / "customers.yaml"))
    ts = TaskStore()
    tm = TaskManager(ds, ts, str(RULES), str(tmp_path / "output"))
    import patrol.api.app as app_module
    import patrol.api.ui as ui_module
    saved = (app_module._device_store, app_module._task_store,
             app_module._task_manager, app_module._customer_store,
             ui_module._device_store, ui_module._task_store,
             ui_module._customer_store)
    app_module._device_store, app_module._task_store = ds, ts
    app_module._task_manager, app_module._customer_store = tm, cs
    ui_module._device_store, ui_module._task_store = ds, ts
    ui_module._customer_store = cs
    yield {"ds": ds, "cs": cs}
    (app_module._device_store, app_module._task_store,
     app_module._task_manager, app_module._customer_store,
     ui_module._device_store, ui_module._task_store,
     ui_module._customer_store) = saved


@pytest.fixture
def client():
    return TestClient(app)


def _xlsx_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


HEADERS = ["设备名称", "管理地址", "登录方式", "账号", "口令", "特权密码"]
ROWS = [
    ["核心交换", "10.1.1.1", "SSH", "admin01", "Pw2026ab", "Sup@1"],
    ["老交换", "10.1.1.2", "Telnet", "netops", "Pw2026cd", ""],
]


class TestImportFlow:
    def test_upload_shows_preview_with_mapping(self, client):
        r = client.post("/ui/devices/import",
                        files={"file": ("台账.xlsx", _xlsx_bytes(HEADERS, ROWS),
                                        "application/vnd...")})
        assert r.status_code == 200
        assert "字段映射" in r.text and "共 2 行数据" in r.text
        # 必填齐全,无缺失警告
        assert "未能自动识别" not in r.text

    def test_commit_creates_devices(self, client, isolated_stores):
        isolated_stores["cs"].create(
            {"name": "演示单位", "contact": "", "phone": "", "remark": ""})
        up = client.post("/ui/devices/import",
                         files={"file": ("台账.xlsx", _xlsx_bytes(HEADERS, ROWS),
                                         "application/octet-stream")})
        token = up.text.split('name="token" value="')[1].split('"')[0]

        r = client.post("/ui/devices/import/commit", data={
            "token": token, "default_customer": "演示单位",
            "map_host": "1", "map_username": "3", "map_password": "4",
            "map_super_password": "5", "map_name": "0", "map_login_method": "2",
        })
        assert r.status_code == 200
        # 页面文案为"成功导入 <b>2</b> 台设备",数字被加粗标签包裹
        assert "成功导入" in r.text and "<b>2</b>" in r.text
        dev = isolated_stores["ds"].get("老交换")
        assert dev["login_method"] == "telnet" and dev["port"] == 23
        assert dev["customer"] == "演示单位"
        # 临时文件已清理
        assert not list((Path("output") / ".import_tmp").glob("*"))

    def test_reject_bad_type(self, client):
        r = client.post("/ui/devices/import",
                        files={"file": ("a.txt", b"hello", "text/plain")})
        assert "不支持的文件类型" in r.text

    def test_expired_token(self, client):
        r = client.post("/ui/devices/import/commit", data={
            "token": "f" * 32, "default_customer": "", "map_host": "0"})
        assert "已过期" in r.text or r.status_code == 303


class TestExcelDownload:
    def _seed_report(self):
        import json as json_mod
        data = {
            "title": "t", "devices": [{
                "name": "设备A", "customer": "演示单位", "host": "10.0.0.1",
                "vendor": "h3c", "device_type": "comware_switch",
                "model": "", "software_version": "", "uptime": "",
                "pass_count": 1, "fail_count": 0, "unknown_count": 0,
                "check_items": [{"name": "cpu_usage", "category": "CPU",
                                 "command": "display cpu-usage", "raw_output": "",
                                 "status": "PASS", "message": "ok", "details": {}}],
            }],
        }
        (Path("output") / "r1.html").write_text("<html></html>", encoding="utf-8")
        (Path("output") / "r1.json").write_text(
            json_mod.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_download_excel(self, client):
        self._seed_report()
        r = client.get("/ui/reports/r1.html/download-excel")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml")
        assert len(r.content) > 4000
