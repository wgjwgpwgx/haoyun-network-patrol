"""Web 管理界面(/ui)路由测试 + 安全修复回归

覆盖:H3(编辑页不回显密码)、H4(设备名 XSS)、H5(host 校验)、
KD1(重复设备名友好报错)、厂商下拉框动态渲染。
"""
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
    """为每个测试创建隔离存储,并同步替换 app 与 ui 两个模块的全局引用。"""
    config_path = tmp_path / "devices.yaml"
    config_path.write_text("devices: []\n", encoding="utf-8")
    customers_path = tmp_path / "customers.yaml"

    ds = DeviceStore(str(config_path))
    cs = CustomerStore(str(customers_path))
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


def _form_payload(**overrides) -> dict:
    payload = {
        "name": "测试设备", "host": "192.168.1.10", "vendor": "h3c",
        "device_type": "comware_switch", "login_method": "ssh",
        "port": 22, "web_port": 443, "username": "admin",
        "password": "secret123", "timeout": 30, "command_timeout": 60,
        "enabled": "true",
    }
    payload.update(overrides)
    return payload


# ── 页面渲染 ────────────────────────────────────────────────────


class TestPageRendering:
    def test_dashboard(self, client):
        assert client.get("/ui").status_code == 200

    def test_device_list_renders_all_vendors(self, client):
        """厂商筛选下拉框应包含全部 7 家(修复前只有 H3C)。"""
        resp = client.get("/ui/devices")
        assert resp.status_code == 200
        for label in ("H3C", "华为", "锐捷", "深信服", "迪普", "Juniper", "Cisco"):
            assert label in resp.text, f"厂商筛选缺少: {label}"

    def test_new_form_options_and_no_password_prefill(self, client):
        """新增表单:5 家厂商 + 登录方式字段;密码框不带 value(不回显)。"""
        resp = client.get("/ui/devices/new")
        assert resp.status_code == 200
        assert 'value="h3c"' in resp.text
        assert 'name="login_method"' in resp.text
        assert "留空则" not in resp.text  # 新增模式下无"留空保持原密码"提示
        # 密码框不应有 value 属性(H3 回归)
        import re
        pw_input = re.search(r'<input type="password"[^>]*>', resp.text)
        assert pw_input, "未找到密码输入框"
        assert "value=" not in pw_input.group(0), "新增表单密码框不应有 value"

    def test_edit_form_does_not_echo_password(self, client):
        """H3 回归:编辑页不得把明文密码写进 HTML。"""
        client.post("/ui/devices/new", data=_form_payload())
        resp = client.get("/ui/devices/测试设备/edit")
        assert resp.status_code == 200
        assert "secret123" not in resp.text, "编辑页回显了明文密码"
        assert "留空则保持原密码不变" in resp.text


# ── 表单创建与错误处理 ──────────────────────────────────────────


class TestDeviceCreateViaForm:
    def test_create_success(self, client, isolated_ui_stores):
        resp = client.post("/ui/devices/new", data=_form_payload(), follow_redirects=False)
        assert resp.status_code == 303
        assert isolated_ui_stores["ds"].get("测试设备") is not None

    def test_duplicate_name_shows_friendly_error(self, client, isolated_ui_stores):
        """KD1 回归:重复设备名应重定向回表单并提示,而非 500。"""
        client.post("/ui/devices/new", data=_form_payload())
        resp = client.post("/ui/devices/new", data=_form_payload(), follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/devices/new?error=" in resp.headers["location"]
        # 跟随重定向后错误信息可见
        follow = client.get(resp.headers["location"])
        assert follow.status_code == 200
        assert "已存在" in follow.text

    def test_traversal_host_rejected(self, client, isolated_ui_stores):
        """H5 回归:UI 表单拒绝路径遍历 host。"""
        resp = client.post(
            "/ui/devices/new", data=_form_payload(host="../../evil"),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]
        assert isolated_ui_stores["ds"].list() == []


class TestHostValidationAPI:
    """H5 回归:REST API 层 host 校验。"""

    def test_api_rejects_traversal_host(self, client):
        resp = client.post("/devices", json=_form_payload(host="../../evil"))
        assert resp.status_code == 422

    def test_api_rejects_host_with_slash(self, client):
        resp = client.post("/devices", json=_form_payload(host="a/b"))
        assert resp.status_code == 422

    def test_api_accepts_normal_ip(self, client):
        payload = _form_payload()
        resp = client.post("/devices", json=payload)
        assert resp.status_code == 201


# ── XSS 回归 ──────────────────────────────────────────────────


class TestXssRegression:
    def test_device_name_with_quote_is_safe(self, client):
        """H4 回归:设备名含引号时,列表页不得把名字内插进内联 JS。"""
        evil_name = "x';alert(1);//'"
        client.post("/ui/devices/new", data=_form_payload(name=evil_name))
        resp = client.get("/ui/devices")
        assert resp.status_code == 200
        # 修复前:onclick="showDetail('x';alert(1);//'...')" 直接注入 JS
        assert "showDetail(" not in resp.text, "仍存在内联 JS 注入点"
        # 修复后:名字只出现在 HTML 属性/文本中(自动转义)
        assert "device-detail-link" in resp.text
        assert "data-name=" in resp.text


# ── 设备操作 ──────────────────────────────────────────────────


class TestDeviceOperations:
    def test_toggle(self, client, isolated_ui_stores):
        client.post("/ui/devices/new", data=_form_payload())
        name_q = quote("测试设备")
        resp = client.post(f"/ui/devices/{name_q}/toggle", follow_redirects=False)
        assert resp.status_code == 303
        assert isolated_ui_stores["ds"].get("测试设备")["enabled"] is False

    def test_delete(self, client, isolated_ui_stores):
        client.post("/ui/devices/new", data=_form_payload())
        name_q = quote("测试设备")
        resp = client.post(f"/ui/devices/{name_q}/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert isolated_ui_stores["ds"].get("测试设备") is None

    def test_edit_keeps_password_when_blank(self, client, isolated_ui_stores):
        """编辑时密码留空 = 不修改原密码。"""
        client.post("/ui/devices/new", data=_form_payload())
        name_q = quote("测试设备")
        resp = client.post(
            f"/ui/devices/{name_q}/edit",
            data=_form_payload(host="192.168.1.99", password=""),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        dev = isolated_ui_stores["ds"].get("测试设备")
        assert dev["host"] == "192.168.1.99"
        assert dev["password"] == "secret123"

    def test_edit_invalid_host_shows_error(self, client):
        client.post("/ui/devices/new", data=_form_payload())
        resp = client.post(
            "/ui/devices/测试设备/edit", data=_form_payload(host="../../evil"),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]


# ── 任务与报告页 ──────────────────────────────────────────────


class TestTaskAndReportPages:
    def test_task_page_renders(self, client):
        assert client.get("/ui/tasks").status_code == 200

    def test_task_for_missing_device_no_crash(self, client):
        resp = client.post("/ui/tasks", data={"device_names": "不存在"},
                           follow_redirects=False)
        assert resp.status_code == 303

    def test_reports_page_renders(self, client, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "output"
        out.mkdir(exist_ok=True)
        (out / "patrol_test.html").write_text("<html></html>", encoding="utf-8")
        resp = client.get("/ui/reports")
        assert resp.status_code == 200
        assert "patrol_test.html" in resp.text

    def test_report_traversal_blocked(self, client):
        """路径遍历文件名被拦截:不跟随重定向,断言绝无 200 直出内容。"""
        for bad in ("..%2Fdevices.yaml", "a%2Fb.html", "a%5Cb.html"):
            resp = client.get(f"/ui/reports/{bad}", follow_redirects=False)
            assert resp.status_code != 200, f"路径遍历未拦截: {bad}"
            assert resp.status_code in (303, 404), f"意外状态: {bad} → {resp.status_code}"


class TestReportDelete:
    def _make_reports(self, tmp_path, *names):
        out = tmp_path / "output"
        out.mkdir(exist_ok=True)
        for name in names:
            (out / name).write_text("<html></html>", encoding="utf-8")
        return out

    def test_delete_removes_html_and_json(self, client, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = self._make_reports(tmp_path, "patrol_a.html")
        (out / "patrol_a.json").write_text("{}", encoding="utf-8")

        resp = client.post("/ui/reports/patrol_a.html/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert not (out / "patrol_a.html").exists()
        assert not (out / "patrol_a.json").exists()

    def test_batch_delete(self, client, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = self._make_reports(
            tmp_path, "patrol_a.html", "patrol_b.html", "patrol_keep.html"
        )
        (out / "patrol_a.json").write_text("{}", encoding="utf-8")

        resp = client.post(
            "/ui/reports/batch-delete",
            data={"filenames": ["patrol_a.html", "patrol_b.html"]},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert not (out / "patrol_a.html").exists()
        assert not (out / "patrol_a.json").exists()
        assert not (out / "patrol_b.html").exists()
        assert (out / "patrol_keep.html").exists()

    def test_delete_traversal_and_non_html_blocked(self, client, tmp_path, monkeypatch):
        """路径遍历与非 html 文件名不产生删除副作用。"""
        monkeypatch.chdir(tmp_path)
        out = self._make_reports(tmp_path, "victim.html")
        (tmp_path / "secret.yaml").write_text("keep", encoding="utf-8")
        (out / "data.json").write_text("{}", encoding="utf-8")

        for bad in ("..%2Fsecret.yaml", "data.json", "a%5Cb.html"):
            resp = client.post(f"/ui/reports/{bad}/delete", follow_redirects=False)
            # 404: 客户端已把 ../ 规范化掉,请求未到达该路由,同样安全
            assert resp.status_code in (303, 404), f"意外状态: {bad}"
        assert (tmp_path / "secret.yaml").exists()
        assert (out / "data.json").exists()
        assert (out / "victim.html").exists()


class TestTasksCustomerFilter:
    """销号清单 #5:任务页弹窗按客户筛选设备。"""

    def test_tasks_page_has_customer_filter(self, client, isolated_ui_stores):
        isolated_ui_stores["cs"].create(
            {"name": "甲方A", "contact": "", "phone": "", "remark": ""})
        client.post("/ui/devices/new", data=_form_payload(
            name="A1", customer="甲方A", host="10.1.1.1"))
        client.post("/ui/devices/new", data=_form_payload(
            name="B1", host="10.1.1.2"))

        resp = client.get("/ui/tasks")
        assert resp.status_code == 200
        assert 'id="custFilter"' in resp.text
        assert "全选本客户" in resp.text
        # 设备行带客户标记与归属徽章
        assert 'data-customer="甲方A"' in resp.text
        assert '<span class="badge bg-secondary ms-1">甲方A</span>' in resp.text
