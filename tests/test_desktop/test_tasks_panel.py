"""巡检任务面板修复回归测试

覆盖 2026-09-23 两个用户报告问题的修复:
1. 报告查看/打开:任务表轮询刷新不再丢失选中;无选中时自动定位最近
   完成且有报告的任务;报告文件缺失时给出明确错误。
2. 客户设备巡检:设备选择面板支持按客户筛选,条目显示归属客户。
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from patrol.desktop.app import Application  # noqa: E402


def _make_root() -> "tk.Tk":
    """创建 Tk 根窗口(重试兜底,同 test_app_smoke)。"""
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
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "devices.yaml").write_text("devices: []", encoding="utf-8")
    (cfg / "customers.yaml").write_text("customers: []", encoding="utf-8")
    (tmp_path / "output").mkdir()

    root = _make_root()
    application = Application(root)
    application.build()
    application.show("tasks")
    root.update_idletasks()
    yield application
    application.task_manager.shutdown()
    try:
        root.destroy()
    except tk.TclError:
        pass


def _seed(app, devices, customers):
    for c in customers:
        app.customers.create(c)
    for d in devices:
        app.devices.create(d)


def _panel(app):
    return app.panels["tasks"]


class TestCustomerFilter:
    def test_filter_by_customer(self, app):
        _seed(app,
              devices=[
                  {"name": "A1", "customer": "甲方A", "host": "10.0.0.1"},
                  {"name": "A2", "customer": "甲方A", "host": "10.0.0.2"},
                  {"name": "B1", "customer": "甲方B", "host": "10.0.0.3"},
                  {"name": "N1", "customer": "", "host": "10.0.0.4"},
              ],
              customers=[
                  {"name": "甲方A", "contact": "", "phone": "", "remark": ""},
                  {"name": "甲方B", "contact": "", "phone": "", "remark": ""},
              ])
        panel = _panel(app)
        panel.refresh()

        # 默认全部客户:4 台,条目含归属客户名
        labels = list(panel.list_devices.get(0, "end"))
        assert len(labels) == 4
        assert any("甲方A" in x for x in labels)
        assert any(x.startswith("N1  (10.0.0.4)") for x in labels)  # 无客户不带 ·

        # 选甲方A → 只剩 2 台
        panel.cmb_customer.set("甲方A")
        panel._reload_devices()
        labels = list(panel.list_devices.get(0, "end"))
        assert len(labels) == 2
        assert all("甲方A" in x for x in labels)

        # 回到全部客户恢复 4 台
        panel.cmb_customer.set("全部客户")
        panel._reload_devices()
        assert len(panel.list_devices.get(0, "end")) == 4

    def test_label_keeps_device_name_parseable(self, app):
        """设备条目带客户名后,_run 的 split 解析仍得到纯设备名。"""
        _seed(app,
              devices=[{"name": "A1", "customer": "甲方A", "host": "10.0.0.1"}],
              customers=[{"name": "甲方A", "contact": "", "phone": "", "remark": ""}])
        panel = _panel(app)
        panel.refresh()
        label = panel.list_devices.get(0)
        assert label.split("  (")[0] == "A1"

    def test_customer_options_follow_store(self, app):
        _seed(app, devices=[{"name": "A1", "host": "10.0.0.1"}],
              customers=[{"name": "甲方A", "contact": "", "phone": "", "remark": ""}])
        panel = _panel(app)
        panel.refresh()
        assert list(panel.cmb_customer["values"]) == ["全部客户", "甲方A"]
        app.customers.create(
            {"name": "甲方C", "contact": "", "phone": "", "remark": ""})
        panel.refresh()
        assert "甲方C" in list(panel.cmb_customer["values"])


class TestTaskSelectionSurvivesRefresh:
    def test_selection_kept_across_poll_refresh(self, app):
        panel = _panel(app)
        app.tasks.create("t1", {"task_id": "t1", "device_name": "d1",
                                "device_host": "10.0.0.1", "status": "completed",
                                "created_at": "2026-09-23T10:00:00",
                                "report_file": "r1.html"})
        app.tasks.create("t2", {"task_id": "t2", "device_name": "d2",
                                "device_host": "10.0.0.2", "status": "completed",
                                "created_at": "2026-09-23T10:01:00",
                                "report_file": "r2.html"})
        panel._refresh_tasks()
        panel.tree.selection_set("t2")
        panel._refresh_tasks()  # 模拟 1.5s 轮询
        assert set(panel.tree.selection()) == {"t2"}


class TestReportButtons:
    def test_falls_back_to_latest_completed(self, app):
        """未选中任务时,自动定位最近完成且有报告的任务。"""
        panel = _panel(app)
        app.tasks.create("old", {"task_id": "old", "device_name": "d1",
                                 "device_host": "10.0.0.1", "status": "completed",
                                 "created_at": "2026-09-23T10:00:00",
                                 "report_file": "old.html"})
        app.tasks.create("new", {"task_id": "new", "device_name": "d2",
                                 "device_host": "10.0.0.2", "status": "completed",
                                 "created_at": "2026-09-23T10:05:00",
                                 "report_file": "new.html"})
        panel._refresh_tasks()

        task = panel._target_report_task()
        assert task["task_id"] == "new"
        assert set(panel.tree.selection()) == {"new"}  # 行被自动选中

    def test_selected_failed_task_falls_back(self, app):
        """选中的是失败任务(无报告)时,回落到最近完成的任务。"""
        panel = _panel(app)
        app.tasks.create("fail", {"task_id": "fail", "device_name": "d1",
                                  "device_host": "10.0.0.1", "status": "failed",
                                  "created_at": "2026-09-23T10:06:00",
                                  "error": "连接超时"})
        app.tasks.create("ok", {"task_id": "ok", "device_name": "d2",
                                "device_host": "10.0.0.2", "status": "completed",
                                "created_at": "2026-09-23T10:05:00",
                                "report_file": "ok.html"})
        panel._refresh_tasks()
        panel.tree.selection_set("fail")

        task = panel._target_report_task()
        assert task["task_id"] == "ok"

    def test_open_report_missing_file_shows_error(self, app, monkeypatch, tmp_path):
        """报告文件不存在时给明确错误,而非无反应/异常。"""
        panel = _panel(app)
        app.tasks.create("t1", {"task_id": "t1", "device_name": "d1",
                                "device_host": "10.0.0.1", "status": "completed",
                                "created_at": "2026-09-23T10:00:00",
                                "report_file": "gone.html"})
        panel._refresh_tasks()

        calls = []
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.showerror",
            lambda *a, **k: calls.append(a))
        panel._open_report()
        assert calls, "应弹出错误提示"
        assert "不存在" in calls[0][1]

    def test_open_report_opens_existing_file(self, app, monkeypatch):
        (app.root.winfo_toplevel() if False else None)  # noqa: B018
        import pathlib
        report = pathlib.Path("output") / "ok.html"
        report.write_text("<html></html>", encoding="utf-8")

        panel = _panel(app)
        app.tasks.create("t1", {"task_id": "t1", "device_name": "d1",
                                "device_host": "10.0.0.1", "status": "completed",
                                "created_at": "2026-09-23T10:00:00",
                                "report_file": "ok.html"})
        panel._refresh_tasks()

        opened = []
        monkeypatch.setattr(
            "patrol.desktop.service.open_path", lambda p: opened.append(p))
        monkeypatch.setattr(
            "patrol.desktop.views.messagebox.showerror",
            lambda *a, **k: pytest.fail("不应报错"))
        panel._open_report()
        assert opened and opened[0].name == "ok.html"


class TestRunCustomer:
    """销号清单 #5:「巡检本单位」一键发起。"""

    def _seed(self, app):
        app.customers.create(
            {"name": "甲方A", "contact": "", "phone": "", "remark": ""})
        for name, customer in (("A1", "甲方A"), ("A2", "甲方A"), ("B1", "")):
            app.devices.create({"name": name, "customer": customer,
                                "host": f"10.0.0.{len(name)}", "enabled": True})

    def test_runs_only_selected_customer(self, app, monkeypatch):
        from types import SimpleNamespace

        self._seed(app)
        created = []
        monkeypatch.setattr(app.task_manager, "create_batch_task",
                            lambda names: (created.append(list(names)),
                                           SimpleNamespace(task_id=f"t{len(created)}"))[-1])
        monkeypatch.setattr("patrol.desktop.views.messagebox.askyesno",
                            lambda *a, **k: True)

        panel = _panel(app)
        panel.refresh()
        panel.cmb_customer.set("甲方A")
        panel._run_customer()
        # 合并巡检:一次调用、一份报告,只含甲方A 的两台
        assert created == [["A1", "A2"]]

    def test_all_customers_runs_all(self, app, monkeypatch):
        from types import SimpleNamespace

        self._seed(app)
        created = []
        monkeypatch.setattr(app.task_manager, "create_batch_task",
                            lambda names: (created.append(list(names)),
                                           SimpleNamespace(task_id=f"t{len(created)}"))[-1])
        monkeypatch.setattr("patrol.desktop.views.messagebox.askyesno",
                            lambda *a, **k: True)

        panel = _panel(app)
        panel.refresh()
        panel.cmb_customer.set("全部客户")
        panel._run_customer()
        assert created == [["A1", "A2", "B1"]]

    def test_empty_customer_shows_hint(self, app, monkeypatch):
        app.customers.create(
            {"name": "空客户", "contact": "", "phone": "", "remark": ""})
        created = []
        monkeypatch.setattr(app.task_manager, "create_batch_task",
                            lambda names: created.append(list(names)))
        infos = []
        monkeypatch.setattr("patrol.desktop.views.messagebox.showinfo",
                            lambda *a, **k: infos.append(a))

        panel = _panel(app)
        panel.refresh()
        panel.cmb_customer.set("空客户")
        panel._run_customer()
        assert not created and infos  # 提示而非空跑


class TestRunMerged:
    """合并巡检:多选设备只发起一个任务、只出一份整体报告。"""

    def _seed(self, app):
        for i, name in enumerate(("S1", "S2", "S3"), start=1):
            app.devices.create({"name": name, "customer": "",
                                "host": f"10.0.0.{i}", "enabled": True})

    def test_multi_select_creates_single_batch_task(self, app, monkeypatch):
        from types import SimpleNamespace

        self._seed(app)
        created = []
        monkeypatch.setattr(app.task_manager, "create_batch_task",
                            lambda names: (created.append(list(names)),
                                           SimpleNamespace(task_id="t1"))[-1])

        panel = _panel(app)
        panel.refresh()
        panel.list_devices.selection_set(0, 1)  # 选中前两台
        panel._run()
        assert created == [["S1", "S2"]]

    def test_no_selection_shows_hint(self, app, monkeypatch):
        self._seed(app)
        created = []
        monkeypatch.setattr(app.task_manager, "create_batch_task",
                            lambda names: created.append(list(names)))
        infos = []
        monkeypatch.setattr("patrol.desktop.views.messagebox.showinfo",
                            lambda *a, **k: infos.append(a))

        panel = _panel(app)
        panel.refresh()
        panel._run()
        assert not created and infos
