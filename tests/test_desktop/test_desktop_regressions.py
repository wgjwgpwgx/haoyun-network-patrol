"""桌面端缺陷回归(真实 Tk):后台线程的错误提示、定时巡检卡片、批量导入选文件。"""
from __future__ import annotations

import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from patrol.desktop.app import Application  # noqa: E402
from patrol.desktop.widgets import run_in_thread  # noqa: E402


def _make_root() -> "tk.Tk":
    """创建 Tk 根窗口(紧邻前一个 destroy() 偶发 Tcl 初始化竞态,重试兜底)。"""
    for attempt in range(5):
        try:
            root = tk.Tk()
            root.withdraw()
            return root
        except tk.TclError:
            if attempt == 4:
                raise
            time.sleep(0.3)


def _run_in_mainloop(root, done: threading.Event, timeout_ms: int = 8000) -> None:
    """进入 Tk 主事件循环,直到 done 被置位或超时。

    后台线程投递的回调只有主线程在主循环里才会被处理:tkinter 对"主线程不在
    主循环"的跨线程调用会抛 RuntimeError,所以不能用 update() 手动泵事件。
    """
    def check():
        if not done.is_set():
            root.after(20, check)

    root.after(timeout_ms, root.quit)
    root.after(20, check)
    root.mainloop()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "devices.yaml").write_text("devices: []", encoding="utf-8")
    (cfg / "customers.yaml").write_text("customers: []", encoding="utf-8")
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


class TestBackgroundErrorIsReported:
    """后台线程出错必须回调 on_error——此前回调里引用的 except 变量已被删除,
    实际抛 NameError,导出失败/分析失败的错误提示弹不出来。"""

    def test_error_callback_receives_the_exception(self, app):
        got, done = [], threading.Event()

        def boom():
            raise RuntimeError("导出失败啦")

        def on_error(err):
            got.append(str(err))
            done.set()

        run_in_thread(app.root, boom, on_error=on_error)
        _run_in_mainloop(app.root, done)
        assert got == ["导出失败啦"]

    def test_done_callback_receives_the_result(self, app):
        got, done = [], threading.Event()

        def on_done(result):
            got.append(result)
            done.set()

        run_in_thread(app.root, lambda: 42, on_done=on_done)
        _run_in_mainloop(app.root, done)
        assert got == [42]


def _laid_out_texts(widget, stop) -> list[str]:
    """收集"自身与各级祖先(到 stop 为止)都已布局"的控件文本。"""
    def laid_out(w) -> bool:
        while w is not None and w is not stop:
            if not w.winfo_manager():
                return False
            w = w.master
        return True

    texts: list[str] = []

    def walk(w) -> None:
        if laid_out(w):
            try:
                texts.append(str(w.cget("text")))
            except tk.TclError:
                pass
        for child in w.winfo_children():
            walk(child)

    walk(widget)
    return texts


class TestDashboardListsUnreachableDevices:
    def test_latest_report_with_unreachable_device_shows_it(self, app, tmp_path):
        """设备连不上不产生异常检查项:概览页不能因此显示成 0 个风险。"""
        import json
        stem = tmp_path / "output" / "patrol_latest"
        stem.with_suffix(".json").write_text(json.dumps({
            "title": "t", "devices": [{
                "name": "断-01", "host": "192.0.2.2", "error": "SSH 连接超时",
                "pass_count": 0, "fail_count": 0, "unknown_count": 0,
                "check_items": []}]}, ensure_ascii=False), encoding="utf-8")
        stem.with_suffix(".html").write_text("<html></html>", encoding="utf-8")

        app.show("dashboard")
        panel = app.panels["dashboard"]
        rows = [panel.tree_fails.item(i, "values") for i in panel.tree_fails.get_children()]

        assert rows and rows[0][0] == "断-01" and "未能采集" in rows[0][3]
        assert panel.stat_labels["fails"].cget("text") == "1"


class TestReportPreviewDialog:
    def test_button_row_is_created_only_once(self, app, tmp_path):
        """操作按钮行属于对话框骨架:此前写在"显示选中项"里,每点一个检查项就多一行。"""
        import json

        from patrol.desktop.dialogs import ReportPreviewDialog

        name = "patrol_192.0.2.1_20260101_000000.html"
        data = {"title": "t", "devices": [{
            "name": "核心-01", "customer": "", "host": "192.0.2.1", "vendor": "h3c",
            "device_type": "comware_switch", "pass_count": 1, "fail_count": 1,
            "unknown_count": 0, "check_items": [
                {"name": "cpu_usage", "category": "CPU", "command": "display cpu-usage",
                 "raw_output": "12%", "status": "PASS", "message": "ok", "details": {}},
                {"name": "fan_status", "category": "硬件", "command": "display fan",
                 "raw_output": "Fan 1: FAIL", "status": "FAIL", "message": "风扇故障",
                 "details": {"severity": "critical"}},
            ]}]}
        (tmp_path / "output" / name).write_text("<html></html>", encoding="utf-8")
        (tmp_path / "output" / name.replace(".html", ".json")).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

        dialog = ReportPreviewDialog(app.root, name)
        try:
            for iid in dialog.tree_all.get_children():  # 把每个检查项都点一遍
                dialog._show_item(iid)
            texts = _laid_out_texts(dialog._body, dialog._body)
            assert texts.count("导出 Word") == 1
            assert texts.count("打开 HTML 文件") == 1
        finally:
            dialog.destroy()


class TestImportDialogKeepsWorkingDirectory:
    def test_working_directory_is_restored_after_the_file_dialog(
            self, app, tmp_path, monkeypatch):
        """Windows 原生文件对话框可能改变进程工作目录,而报告与配置都按相对路径读写。"""
        import os

        from openpyxl import Workbook
        from tkinter import filedialog

        from patrol.desktop.dialogs import ImportDialog

        ledger = tmp_path / "台账.xlsx"
        wb = Workbook()
        wb.active.append(["管理地址", "用户名", "密码", "设备名称"])
        wb.active.append(["192.0.2.10", "admin", "pw", "接入-01"])
        wb.save(ledger)
        elsewhere = tmp_path / "somewhere-else"
        elsewhere.mkdir()

        def dialog_that_changes_cwd(**kwargs):
            os.chdir(elsewhere)
            return str(ledger)

        monkeypatch.setattr(filedialog, "askopenfilename", dialog_that_changes_cwd)
        before = os.getcwd()

        dialog = ImportDialog(app.root, app.devices, app.customers)
        try:
            dialog._pick_file()
            # 控件销毁后无法读取,断言要放在 destroy 之前
            assert "台账.xlsx" in dialog._file_label.cget("text")  # 文件确实读到了
            assert os.getcwd() == before
        finally:
            dialog.destroy()


class TestSettingsPanel:
    def test_schedule_card_is_laid_out(self, app):
        """定时巡检卡片此前创建后忘了 pack:功能在,用户永远看不到。"""
        app.show("settings")
        panel = app.panels["settings"]
        shown = "\n".join(_laid_out_texts(panel.body, panel.body))
        assert "定时巡检(Windows 计划任务)" in shown


class TestImportDialog:
    def test_picking_a_ledger_file_fills_the_preview(self, app, tmp_path,
                                                     monkeypatch):
        """选完台账文件后必须能识别字段并填充预览——此前此处 NameError。"""
        from openpyxl import Workbook
        from tkinter import filedialog

        from patrol.desktop.dialogs import ImportDialog

        xlsx = tmp_path / "台账.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["管理地址", "用户名", "密码", "设备名称"])
        ws.append(["192.0.2.10", "admin", "pw", "接入-01"])
        wb.save(xlsx)
        monkeypatch.setattr(filedialog, "askopenfilename", lambda **kw: str(xlsx))

        dialog = ImportDialog(app.root, app.devices, app.customers)
        try:
            dialog._pick_file()
            assert "台账.xlsx" in dialog._file_label.cget("text")
            assert len(dialog._tree.get_children()) == 1
            assert set(dialog._matches) >= {"host", "username", "password"}
        finally:
            dialog.destroy()
