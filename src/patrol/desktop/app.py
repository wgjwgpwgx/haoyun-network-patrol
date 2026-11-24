"""桌面小工具主窗口 - 双击即用,无需浏览器

Tkinter 原生窗口(Python 自带库,零第三方依赖),完整覆盖
设备/客户/巡检任务/报告/AI 分析/软件更新闭环。网页远程访问
模式由 launcher 以 `--web` 参数保留。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

from patrol import __version__
from patrol.api.tasks import TaskManager
from patrol.desktop import service
from patrol.desktop.settings_view import SettingsPanel
from patrol.desktop.views import (
    CustomersPanel,
    DashboardPanel,
    DevicesPanel,
    ReportsPanel,
    TasksPanel,
)
from patrol.desktop.widgets import COLORS, FONTS, apply_theme
from patrol.product import PRODUCT_NAME

NAV_ITEMS = [
    ("dashboard", "风险汇总"),
    ("devices", "设备管理"),
    ("customers", "客户管理"),
    ("tasks", "巡检任务"),
    ("reports", "报告管理"),
    ("settings", "系统设置"),
]


class Application:
    """主窗口:侧栏 + 内容区 + 状态栏。"""

    def __init__(self, root: tk.Tk | None = None):
        self.root = root or tk.Tk()
        from patrol.storage.sqlstore import bootstrap
        self.devices, self.customers, self.tasks, self._audit = bootstrap()
        self.task_manager = TaskManager(self.devices, self.tasks)
        # 上次退出时没跑完的任务不会再有结果:标为已中断,而不是永远显示"进行中"
        self.task_manager.reconcile_interrupted()
        self.panels: dict[str, tk.Frame] = {}
        self._nav_buttons: dict[str, tk.Button] = {}
        self._current = ""

    # -- 构建 --
    def build(self) -> None:
        apply_theme(self.root)
        self.root.title(f"{PRODUCT_NAME} v{__version__}")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        if getattr(sys, "frozen", False):
            try:
                # 从 exe 自身提取图标(Windows 支持)
                self.root.iconbitmap(default=sys.executable)
            except tk.TclError:  # pragma: no cover
                pass
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 顶栏(海军蓝):仅当前模块名;产品名只在窗口标题栏出现
        header = tk.Frame(self.root, bg=COLORS["header"], height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        # 底缘 3px 压边:顶栏立体分层
        tk.Frame(header, bg=COLORS["header_edge"], height=3).pack(side="bottom", fill="x")
        self._page_title = tk.Label(header, text="", font=FONTS["h1"],
                                    bg=COLORS["header"], fg="#FFFFFF")
        self._page_title.pack(side="left", padx=(18, 0))

        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)

        # 侧栏(与顶栏同色中蓝):3D 凸起菜单钮,选中=凹陷+左侧主色条(无背景色块)
        sidebar = tk.Frame(body, bg=COLORS["sidebar"], width=180)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        # 右缘 2px 压边:侧栏与内容区分层
        tk.Frame(sidebar, bg=COLORS["sidebar_edge"], width=2).pack(side="right", fill="y")
        for key, label in NAV_ITEMS:
            btn = ttk.Button(sidebar, text=label, style="Nav.TButton",
                             cursor="hand2", command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=10, pady=5)
            self._nav_buttons[key] = btn

        # 内容区
        content = tk.Frame(body, bg=COLORS["bg"])
        content.pack(side="left", fill="both", expand=True)
        self._content = content
        self._build_panels(content)
        # 滚轮统一派发:落在面板/对话框内时滚动其内容区(替代各处 bind_all)
        self.root.bind_all("<MouseWheel>", self._on_wheel)

        # 状态栏(海军蓝,与顶栏一体)+ 上缘 2px 亮边
        self._status = tk.Label(self.root, text="就绪", font=FONTS["small"],
                                bg=COLORS["statusbar"], fg=COLORS["nav_text"],
                                anchor="w", padx=16, pady=6)
        self._status.pack(fill="x", side="bottom")
        tk.Frame(self.root, bg=COLORS["statusbar_edge"], height=2).pack(side="bottom", fill="x")

    def _build_panels(self, content: tk.Frame) -> None:
        classes = {
            "dashboard": DashboardPanel,
            "devices": DevicesPanel,
            "customers": CustomersPanel,
            "tasks": TasksPanel,
            "reports": ReportsPanel,
            "settings": SettingsPanel,
        }
        for key, cls in classes.items():
            panel = cls(content, self)
            panel.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.panels[key] = panel

    # -- 行为 --
    def show(self, key: str) -> None:
        panel = self.panels.get(key)
        if panel is None:
            return
        self._current = key
        panel.lift()
        panel.refresh()
        for k, label in NAV_ITEMS:
            active = k == key
            # 选中=凹陷 3D + 左侧主色条(state["selected"]),不再换背景色
            self._nav_buttons[k].state(["selected"] if active else ["!selected"])
            if active:
                self._page_title.configure(text=label)

    def broadcast_refresh(self) -> None:
        """数据被其他面板改动后,刷新全部面板(下次切页也自刷新)。"""
        for panel in self.panels.values():
            try:
                panel.refresh()
            except Exception:  # noqa: BLE001 - 单面板刷新失败不影响其他
                pass

    def set_status(self, msg: str) -> None:
        self._status.configure(text=msg)

    _WHEEL_SELF = frozenset({"Text", "Listbox", "Entry", "TEntry", "Spinbox",
                             "TSpinbox", "Combobox", "TCombobox"})

    def _on_wheel(self, event) -> None:
        """滚轮:交给控件所属面板/对话框的滚动区;自身可滚的控件不干预。"""
        w = event.widget
        try:
            if w.winfo_class() in self._WHEEL_SELF:
                return
        except tk.TclError:  # pragma: no cover - 控件已销毁
            return
        target = None
        while w is not None:
            canvas = getattr(w, "_scroll_canvas", None)
            if canvas is not None:
                target = canvas
                break
            if isinstance(w, tk.Toplevel):
                return  # 对话框未提供滚动区:不动主面板
            w = getattr(w, "master", None)
        if target is None:
            return
        steps = int(event.delta / 120) or (1 if event.delta > 0 else -1)
        target.yview_scroll(-steps * 3, "units")

    def _on_close(self) -> None:
        running = [t for t in self.tasks.list_all()
                   if t.get("status") in ("pending", "running")]
        if running:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "确认退出",
                f"还有 {len(running)} 个巡检任务进行中,退出将中止执行。确定退出?",
                parent=self.root,
            ):
                return
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def _smoke() -> int:
    """冻结冒烟:构建窗口并遍历全部面板刷新(PATROL_DESKTOP_SMOKE=1)。"""
    steps = [
        "构建主窗口",
        "遍历6个功能面板",
        "厂商/设备类型注册表",
        "报告/AI/更新服务可达",
        "PDF 组件已打包(win32com 可导入)",
    ]
    try:
        app = Application()
        app.build()
        print(f"SMOKE 1/{len(steps)} {steps[0]}", flush=True)
        app.root.update_idletasks()
        for key, _label in NAV_ITEMS:
            app.show(key)
        print(f"SMOKE 2/{len(steps)} {steps[1]}", flush=True)
        opts = service.vendor_options()
        assert opts and opts[0]["device_types"], "厂商选项为空"
        print(f"SMOKE 3/{len(steps)} {steps[2]}:{len(opts)} 家厂商", flush=True)
        service.list_reports()
        service.ai_load_raw()
        service.auth_status()
        print(f"SMOKE 4/{len(steps)} {steps[3]}", flush=True)
        # PDF 导出靠 win32com 调用 Word:打包时漏掉它,成品包里"导出 PDF"直接不可用
        from patrol.reporter.pdf import check_pdf_capability
        assert check_pdf_capability()["win32com"], \
            "PDF 组件(win32com)未打包:这个包将无法导出 PDF"
        print(f"SMOKE 5/{len(steps)} {steps[4]}", flush=True)
        app.task_manager.shutdown()
        app.root.destroy()
        print("DESKTOP_SMOKE_OK", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001 - 冒烟失败必须显形
        import traceback

        traceback.print_exc()
        print(f"DESKTOP_SMOKE_FAIL {e}", flush=True)
        return 1


def run() -> int:
    """程序入口:默认打开桌面小工具窗口。"""
    if os.environ.get("PATROL_DESKTOP_SMOKE") == "1":
        return _smoke()
    app = Application()
    app.build()
    app.show("dashboard")
    try:
        return app.run()
    finally:
        app.task_manager.shutdown()
