"""桌面小工具窗口构建冒烟(真实 Tk,验证面板/对话框可实例化并刷新)"""
from __future__ import annotations

import json

import pytest

tk = pytest.importorskip("tkinter")

from patrol.desktop import service  # noqa: E402
from patrol.desktop.app import Application  # noqa: E402

REPORT_DATA = {
    "title": "网络设备巡检报告",
    "devices": [{
        "name": "核心交换机", "customer": "", "host": "10.0.0.1",
        "vendor": "h3c", "device_type": "comware_switch",
        "pass_count": 1, "fail_count": 1, "unknown_count": 0,
        "check_items": [
            {"name": "风扇状态", "category": "硬件", "command": "dis fan",
             "raw_output": "...", "status": "FAIL", "message": "风扇故障",
             "details": {"severity": "critical"}},
        ],
    }],
}


def _make_root() -> "tk.Tk":
    """创建 Tk 根窗口;Windows 上紧邻前一个 destroy() 偶发 Tcl 初始化竞态,重试兜底。"""
    import time

    for attempt in range(5):
        try:
            root = tk.Tk()
            root.withdraw()
            return root
        except tk.TclError:
            if attempt == 4:
                raise
            time.sleep(0.3)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "devices.yaml").write_text("devices: []", encoding="utf-8")
    (tmp_path / "config" / "customers.yaml").write_text("customers: []", encoding="utf-8")
    (tmp_path / "output").mkdir()

    root = _make_root()
    application = Application(root)
    application.build()
    root.update_idletasks()
    yield application
    application.task_manager.shutdown()
    try:
        root.destroy()
    except tk.TclError:
        pass


def _widget_texts(widget) -> list[str]:
    texts = []
    for w in widget.winfo_children():
        try:
            texts.append(str(w.cget("text")))
        except tk.TclError:
            pass
        texts.extend(_widget_texts(w))
    return texts


def _tree_rows(widget) -> list[tuple]:
    """收集控件树内全部 Treeview 的行值(预览数据断言用)。"""
    rows: list[tuple] = []

    def walk(w) -> None:
        for c in w.winfo_children():
            if c.winfo_class() == "Treeview":
                rows.extend(tuple(c.item(i)["values"]) for i in c.get_children())
            walk(c)

    walk(widget)
    return rows


class TestShell:
    def test_six_panels_built(self, app):
        assert set(app.panels) == {
            "dashboard", "devices", "customers", "tasks", "reports", "settings"}

    def test_show_switches_and_refreshes(self, app):
        for key in app.panels:
            app.show(key)
        assert app._current == "settings"

    def test_title_and_signature_deduplicated(self, app):
        # 产品名只在窗口标题栏;作者署名在界面内(设置-产品信息),标题栏不再重复
        title = app.root.title()
        assert "昊云网络巡检助手" in title
        assert "370428679" not in title and "昊云" not in title.replace("昊云网络巡检助手", "")
        texts = "\n".join(_widget_texts(app.root))
        # 侧栏署名行已按用户要求移除;署名保留在 设置→产品信息 卡(作者/QQ 字段)
        assert "370428679" in texts and "作者" in texts


class TestPanels:
    def test_dashboard_refresh(self, app):
        app.show("dashboard")
        app.root.update_idletasks()
        assert app.panels["dashboard"].stat_labels["devices"].cget("text") == "0"

    def test_devices_panel_lists_saved_device(self, app):
        service.save_device(app.devices, app.customers, None, {
            "name": "核心交换机", "host": "10.0.0.1", "vendor": "h3c",
            "device_type": "comware_switch", "login_method": "ssh",
            "port": 22, "web_port": 443, "username": "admin",
            "password": "p", "timeout": 30, "command_timeout": 120,
        })
        panel = app.panels["devices"]
        app.show("devices")
        assert len(panel.tree.get_children()) == 1
        values = panel.tree.item("核心交换机", "values")
        assert values[0] == "☐"  # 首列为勾选框
        assert values[2] == "10.0.0.1"

    def test_reports_panel_lists_report(self, app, tmp_path):
        out = tmp_path / "output"
        name = "patrol_10.0.0.1_20260101_000000.html"
        (out / name).write_text("<html></html>", encoding="utf-8")
        (out / name.replace(".html", ".json")).write_text(
            json.dumps(REPORT_DATA, ensure_ascii=False), encoding="utf-8")
        panel = app.panels["reports"]
        app.show("reports")
        assert panel.tree.get_children() == (name,)

    def test_settings_panel_shows_product_info(self, app):
        app.show("settings")
        texts = "\n".join(_widget_texts(app.panels["settings"]))
        assert "昊云" in texts and "370428679" in texts
        assert "MIT License" in texts


class TestDialogs:
    def test_device_dialog_collect_and_save(self, app):
        from patrol.desktop.dialogs import DeviceDialog

        dlg = DeviceDialog(app.root, app.devices, app.customers)
        dlg.var_name.set("汇聚交换机")
        dlg.var_host.set("10.0.0.2")
        dlg.var_user.set("admin")
        dlg.var_pass.set("secret")
        dlg.var_skip_tls.set(True)
        fields = dlg.collect()
        assert fields["name"] == "汇聚交换机"
        assert fields["verify_ssl"] is False
        dlg._on_ok()
        assert dlg.result is True
        saved = app.devices.get("汇聚交换机")
        assert saved and saved["verify_ssl"] is False

    def test_device_dialog_shows_inline_error(self, app):
        from patrol.desktop.dialogs import DeviceDialog

        dlg = DeviceDialog(app.root, app.devices, app.customers)
        dlg.var_name.set("坏设备")
        dlg.var_host.set("../evil")
        dlg.var_user.set("admin")
        dlg.var_pass.set("secret")
        dlg._on_ok()
        assert dlg.result is False and dlg.winfo_exists()
        assert "管理地址非法" in dlg.lbl_error.cget("text")
        dlg.destroy()

    def test_customer_dialog_save(self, app):
        from patrol.desktop.dialogs import CustomerDialog

        dlg = CustomerDialog(app.root, app.customers, app.devices)
        dlg.var_name.set("甲公司")
        dlg._on_ok()
        assert dlg.result is True
        assert app.customers.get("甲公司") is not None

    def test_report_preview_builds(self, app, tmp_path):
        from patrol.desktop.dialogs import ReportPreviewDialog

        out = tmp_path / "output"
        name = "patrol_10.0.0.1_20260101_000000.html"
        (out / name).write_text("<html></html>", encoding="utf-8")
        (out / name.replace(".html", ".json")).write_text(
            json.dumps(REPORT_DATA, ensure_ascii=False), encoding="utf-8")
        dlg = ReportPreviewDialog(app.root, name)
        app.root.update_idletasks()
        assert dlg.winfo_exists()
        # 预览必须真实渲染数据(2026-09-23 用户反馈"预览报告没有显示的数据")
        flat = [" ".join(map(str, r)) for r in _tree_rows(dlg._body)]
        assert any("核心交换机" in r and "10.0.0.1" in r for r in flat)  # 设备概况
        assert any("风扇故障" in r for r in flat)                        # 风险项/检查项
        assert any("严重" in r for r in flat)                           # 级别中文
        raw = dlg.txt_raw.get("1.0", "end")
        assert "执行命令" in raw and "dis fan" in raw                   # 原始输出区
        dlg.destroy()

    def test_report_preview_shows_error_device(self, app, tmp_path):
        """设备采集失败(无检查项)的报告也必须显示数据,而非空表。"""
        from patrol.desktop.dialogs import ReportPreviewDialog

        data = {"title": "网络设备巡检报告", "devices": [{
            "name": "坏设备", "customer": "", "host": "10.0.0.2",
            "vendor": "h3c", "device_type": "comware_switch",
            "model": "", "software_version": "", "uptime": "",
            "error": "连接超时", "pass_count": 0, "fail_count": 0,
            "unknown_count": 0, "check_items": [],
        }]}
        out = tmp_path / "output"
        name = "patrol_10.0.0.2_20260101_000000.html"
        (out / name).write_text("<html></html>", encoding="utf-8")
        (out / name.replace(".html", ".json")).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        dlg = ReportPreviewDialog(app.root, name)
        app.root.update_idletasks()
        flat = [" ".join(map(str, r)) for r in _tree_rows(dlg._body)]
        assert any("坏设备" in r and "连接超时" in r for r in flat)
        dlg.destroy()
