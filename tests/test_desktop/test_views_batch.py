"""数据面板勾选框批量删除 + 任务页按钮/提示回归

覆盖 2026-09-23 用户反馈:
- 删除要加选中框,批量删除可多选(设备/客户/报告三个数据面板);
- 开始巡检按钮无法展示全部 → 独占整行;
- 选了设备开始巡检后查看/打开报告无法预览 → 按任务状态给可行动提示。
"""
from __future__ import annotations

import json

import pytest

tk = pytest.importorskip("tkinter")

from patrol.desktop.app import Application  # noqa: E402
from patrol.desktop.widgets import checked_rows, set_check  # noqa: E402

REPORT_DATA = {
    "title": "网络设备巡检报告",
    "devices": [{
        "name": "核心交换机", "customer": "", "host": "10.0.0.1",
        "vendor": "h3c", "device_type": "comware_switch",
        "pass_count": 1, "fail_count": 0, "unknown_count": 0,
        "check_items": [
            {"name": "cpu", "category": "CPU", "command": "dis cpu",
             "raw_output": "12%", "status": "PASS", "message": "正常",
             "details": {}},
        ],
    }],
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "devices.yaml").write_text("devices: []", encoding="utf-8")
    (tmp_path / "config" / "customers.yaml").write_text("customers: []", encoding="utf-8")
    (tmp_path / "output").mkdir()

    import time

    for attempt in range(5):
        try:
            root = tk.Tk()
            root.withdraw()
            break
        except tk.TclError:
            if attempt == 4:
                raise
            time.sleep(0.3)
    application = Application(root)
    application.build()
    root.update_idletasks()
    yield application
    application.task_manager.shutdown()
    try:
        root.destroy()
    except tk.TclError:
        pass


def _write_report(tmp_path, name: str) -> None:
    out = tmp_path / "output"
    (out / name).write_text("<html></html>", encoding="utf-8")
    (out / name.replace(".html", ".json")).write_text(
        json.dumps(REPORT_DATA, ensure_ascii=False), encoding="utf-8")


class TestDevicesBatchDelete:
    def _seed(self, app):
        for i in (1, 2, 3):
            app.devices.create({"name": f"D{i}", "host": f"10.0.0.{i}",
                                "vendor": "h3c", "device_type": "comware_switch"})

    def test_checked_rows_deleted(self, app, monkeypatch):
        self._seed(app)
        panel = app.panels["devices"]
        app.show("devices")
        panel.refresh()
        set_check(panel.tree, "D1", True)
        set_check(panel.tree, "D3", True)
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.askyesno", lambda *a, **k: True)
        panel._delete()
        assert [d["name"] for d in app.devices.list()] == ["D2"]
        assert list(panel.tree.get_children()) == ["D2"]

    def test_selection_fallback_without_checks(self, app, monkeypatch):
        self._seed(app)
        panel = app.panels["devices"]
        app.show("devices")
        panel.refresh()
        panel.tree.selection_set("D2")
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.askyesno", lambda *a, **k: True)
        panel._delete()
        assert sorted(d["name"] for d in app.devices.list()) == ["D1", "D3"]

    def test_checks_survive_refresh(self, app):
        self._seed(app)
        panel = app.panels["devices"]
        app.show("devices")
        panel.refresh()
        set_check(panel.tree, "D2", True)
        panel.refresh()
        assert checked_rows(panel.tree) == ["D2"]


class TestCustomersBatchDelete:
    def test_checked_rows_deleted(self, app, monkeypatch):
        for n in ("甲", "乙", "丙"):
            app.customers.create({"name": n, "contact": "", "phone": "",
                                  "remark": ""})
        panel = app.panels["customers"]
        app.show("customers")
        panel.refresh()
        set_check(panel.tree, "甲", True)
        set_check(panel.tree, "丙", True)
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.askyesno", lambda *a, **k: True)
        panel._delete()
        assert [c["name"] for c in app.customers.list()] == ["乙"]


class TestReportsBatchDelete:
    def test_batch_delete_button_and_checked_rows(self, app, tmp_path, monkeypatch):
        for i in (1, 2, 3):
            _write_report(tmp_path, f"patrol_10.0.0.{i}_20260101_00000{i}.html")
        panel = app.panels["reports"]
        app.show("reports")
        panel.refresh()
        assert len(panel.tree.get_children()) == 3
        # 批量删除按钮存在(与删除同处理器)
        btn_texts = []

        def walk(w):
            for c in w.winfo_children():
                try:
                    btn_texts.append(str(c.cget("text")))
                except tk.TclError:
                    pass
                walk(c)

        walk(panel)
        assert "批量删除" in btn_texts

        set_check(panel.tree, "patrol_10.0.0.1_20260101_000001.html", True)
        set_check(panel.tree, "patrol_10.0.0.3_20260101_000003.html", True)
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.askyesno", lambda *a, **k: True)
        panel._delete()
        assert list(panel.tree.get_children()) == ["patrol_10.0.0.2_20260101_000002.html"]
        remaining = sorted(p.name for p in (tmp_path / "output").glob("*.html"))
        assert remaining == ["patrol_10.0.0.2_20260101_000002.html"]

    def test_checks_survive_refresh(self, app, tmp_path):
        for i in (1, 2):
            _write_report(tmp_path, f"patrol_10.0.0.{i}_20260101_00000{i}.html")
        panel = app.panels["reports"]
        app.show("reports")
        panel.refresh()
        set_check(panel.tree, "patrol_10.0.0.1_20260101_000001.html", True)
        panel.refresh()
        assert checked_rows(panel.tree) == ["patrol_10.0.0.1_20260101_000001.html"]


class TestRunButtonLayout:
    def test_run_button_full_width_own_row(self, app):
        panel = app.panels["tasks"]
        app.show("tasks")
        info = panel.btn_run.pack_info()
        assert info["fill"] == "x"  # 撑满卡片宽,窄面板下完整可见
        # 与设备列表同挂在选择卡片内容区,独占整行
        assert panel.btn_run.master is panel.list_devices.master


class TestReportButtonHints:
    def test_running_task_hint(self, app, monkeypatch):
        panel = app.panels["tasks"]
        app.tasks.create("r1", {"task_id": "r1", "device_name": "核心A",
                                "device_host": "10.0.0.1", "status": "running",
                                "created_at": "2026-09-23T10:00:00"})
        panel._refresh_tasks()
        panel.tree.selection_set("r1")
        calls = []
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.showinfo",
            lambda *a, **k: calls.append(a))
        panel._preview()
        assert calls and "巡检还在进行中" in calls[0][1]

        calls.clear()
        panel._open_report()
        assert calls and "巡检还在进行中" in calls[0][1]

    def test_failed_task_hint(self, app):
        panel = app.panels["tasks"]
        app.tasks.create("f1", {"task_id": "f1", "device_name": "核心B",
                                "device_host": "10.0.0.2", "status": "failed",
                                "created_at": "2026-09-23T10:00:00",
                                "error": "连接超时"})
        panel._refresh_tasks()
        hint = panel._no_report_hint(app.tasks.get("f1"))
        assert "执行失败" in hint and "连接超时" in hint

    def test_none_task_hint(self, app):
        panel = app.panels["tasks"]
        hint = panel._no_report_hint(None)
        assert "开始巡检" in hint
