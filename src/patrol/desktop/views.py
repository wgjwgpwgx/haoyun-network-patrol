"""桌面小工具工作流面板:概览 / 设备 / 客户 / 任务 / 报告"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from patrol.desktop import service
from patrol.desktop.dialogs import (
    CustomerDialog,
    DeviceDialog,
    ReportPreviewDialog,
)
from patrol.desktop.widgets import (
    COLORS,
    FONTS,
    STAT_COLORS,
    card,
    checked_rows,
    clear_tree,
    colorize_rows,
    insert_row,
    keep_checks,
    make_tree,
    run_in_thread,
    severity_cn,
    target_rows,
)

LOGIN_LABELS = {"ssh": "SSH", "telnet": "Telnet", "web": "Web 页面采集", "api": "API 接口"}
TASK_LABELS = {"pending": "排队中", "running": "巡检中",
               "completed": "完成", "failed": "失败"}


class BasePanel(tk.Frame):
    """面板基类:内容置于可滚动区,窗口矮时滚轮/滚动条可达(底部按钮不被裁)。"""

    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        # 画布滚动容器:self.body 内容超出窗口高度时可滚动浏览
        self._canvas = tk.Canvas(self, bg=COLORS["bg"], highlightthickness=0, bd=0)
        self._vsb = ttk.Scrollbar(self, orient="vertical",
                                  command=self._canvas.yview)
        self.body = tk.Frame(self._canvas, bg=COLORS["bg"])
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self.body, anchor="nw")
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self.body.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._canvas_win, width=e.width))
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(fill="both", expand=True)
        self._scroll_canvas = self._canvas  # 主窗口滚轮统一走这里

    def refresh(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _header(self, title: str, subtitle: str = "") -> tk.Frame:
        bar = tk.Frame(self.body, bg=COLORS["bg"])
        bar.pack(fill="x", pady=(0, 10))
        tk.Label(bar, text=title, font=FONTS["h1"], bg=COLORS["bg"],
                 fg=COLORS["title"], anchor="w").pack(side="left")
        if subtitle:
            tk.Label(bar, text="  " + subtitle, font=FONTS["small"],
                     bg=COLORS["bg"], fg=COLORS["muted"]).pack(side="left", padx=8)
        return bar


# ── 概览(风险汇总) ────────────────────────────────────────────


class DashboardPanel(BasePanel):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._header("风险汇总", "设备、任务与最近报告一览")

        cards = tk.Frame(self.body, bg=COLORS["bg"])
        cards.pack(fill="x")
        self.stat_labels: dict[str, tk.Label] = {}
        for i, (key, title) in enumerate((
            ("devices", "设备总数"), ("customers", "客户总数"),
            ("tasks", "巡检任务"), ("fails", "最近报告风险"),
        )):
            outer, body = card(cards, title)
            body.pack_configure(pady=(2, 10))
            lbl = tk.Label(body, text="—", font=FONTS["num"],
                           bg=COLORS["card"],
                           fg=STAT_COLORS[i % len(STAT_COLORS)])
            lbl.pack(anchor="w")
            self.stat_labels[key] = lbl
            cards.columnconfigure(i, weight=1)
            outer.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))

        # 快捷入口紧跟统计卡:矮窗口下也永不滚出视野
        quick = tk.Frame(self.body, bg=COLORS["bg"])
        quick.pack(fill="x", pady=(12, 0))
        ttk.Button(quick, text="去巡检", style="Accent.TButton",
                   command=lambda: self.app.show("tasks")).pack(side="left")
        ttk.Button(quick, text="新建设备",
                   command=lambda: self.app.show("devices")).pack(side="left", padx=8)
        ttk.Button(quick, text="打开报告目录", command=self._open_output).pack(side="left")

        _, task_body = card(self.body, "近期任务", fill="both", expand=True, pady=(12, 0))
        self.tree_tasks, wrap_tasks = make_tree(task_body, [
            ("device", "设备", 140), ("host", "管理地址", 130),
            ("status", "状态", 80), ("created", "创建时间", 150),
            ("report", "报告", 220),
        ], height=7)
        wrap_tasks.pack(fill="both", expand=True)

        _, fail_body = card(self.body, "最近报告风险项", fill="both", expand=True, pady=(12, 0))
        self.tree_fails, wrap_fails = make_tree(fail_body, [
            ("device", "设备", 140), ("category", "类别", 120),
            ("severity", "级别", 80), ("message", "问题描述", 340),
        ], height=5)
        wrap_fails.pack(fill="both", expand=True)

    def _open_output(self) -> None:
        try:
            service.open_path(Path("output"))
        except RuntimeError as e:
            messagebox.showerror("打开失败", str(e), parent=self)

    def refresh(self) -> None:
        devices = self.app.devices.list()
        customers = self.app.customers.list()
        tasks = sorted(self.app.tasks.list_all(),
                       key=lambda t: t.get("created_at", ""), reverse=True)
        self.stat_labels["devices"].configure(text=str(len(devices)))
        self.stat_labels["customers"].configure(text=str(len(customers)))
        self.stat_labels["tasks"].configure(text=str(len(tasks)))

        clear_tree(self.tree_tasks)
        for t in tasks[:10]:
            self.tree_tasks.insert("", "end", values=(
                t.get("device_name", ""), t.get("device_host", ""),
                TASK_LABELS.get(t.get("status", ""), t.get("status", "")),
                (t.get("created_at") or "")[:19].replace("T", " "),
                t.get("report_file") or t.get("error") or "",
            ))
        colorize_rows(self.tree_tasks)

        # 最近一份报告的风险项
        fails: list[dict] = []
        reports = service.list_reports()
        if reports:
            try:
                summary = service.report_summary(
                    service.load_report_data(reports[0]["name"]))
                fails = summary["fail_items"]
                self.stat_labels["fails"].configure(text=str(len(fails)))
            except (ValueError, FileNotFoundError):
                self.stat_labels["fails"].configure(text="—")
        else:
            self.stat_labels["fails"].configure(text="—")

        clear_tree(self.tree_fails)
        for it in fails[:20]:
            self.tree_fails.insert("", "end", values=(
                it["device_name"], it["category"],
                severity_cn(it["severity"]), it["message"]))
        colorize_rows(self.tree_fails, "severity")


# ── 设备管理 ────────────────────────────────────────────────────


class DevicesPanel(BasePanel):
    VENDOR_LABEL_HINT = "全部厂商"
    STATE_OPTIONS = ("全部状态", "启用", "停用")

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._header("设备管理", "巡检对象清单(在界面中维护,与命令行/定时巡检共用)")

        toolbar = tk.Frame(self.body, bg=COLORS["bg"])
        toolbar.pack(fill="x", pady=(0, 8))
        self.var_q = tk.StringVar()
        self.var_vendor = tk.StringVar(value=self.VENDOR_LABEL_HINT)
        self.var_state = tk.StringVar(value=self.STATE_OPTIONS[0])
        ttk.Entry(toolbar, textvariable=self.var_q, width=18).pack(side="left")
        ttk.Button(toolbar, text="搜索", command=self.refresh).pack(side="left", padx=4)
        self.cb_vendor = ttk.Combobox(toolbar, textvariable=self.var_vendor,
                                      state="readonly", width=16)
        self.cb_vendor.pack(side="left", padx=(12, 4))
        self.cb_vendor.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        cb_state = ttk.Combobox(toolbar, textvariable=self.var_state,
                                values=list(self.STATE_OPTIONS), state="readonly",
                                width=10)
        cb_state.pack(side="left", padx=4)
        cb_state.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        btns = tk.Frame(self.body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="新建设备", style="Accent.TButton",
                   command=self._create).pack(side="left")
        ttk.Button(btns, text="批量导入", command=self._import).pack(
            side="left", padx=6)
        ttk.Button(btns, text="编辑", command=self._edit).pack(side="left", padx=6)
        ttk.Button(btns, text="启用/停用", command=self._toggle).pack(side="left", padx=6)
        ttk.Button(btns, text="删除", style="Danger.TButton",
                   command=self._delete).pack(side="left", padx=6)
        ttk.Button(btns, text="批量删除", style="Danger.TButton",
                   command=self._batch_delete).pack(side="left", padx=6)
        ttk.Button(btns, text="刷新", command=self.refresh).pack(side="right")

        self.tree, wrap = make_tree(self.body, [
            ("name", "设备名称", 150), ("host", "管理地址", 130),
            ("vendor", "厂商", 120), ("dtype", "设备类型", 140),
            ("login", "登录方式", 100), ("customer", "归属客户", 110),
            ("state", "状态", 60),
        ], height=14, checkbox=True)
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit(), add="+")

    # -- 数据 --
    def _filtered(self) -> list[dict]:
        devices = self.app.devices.list()
        q = self.var_q.get().strip().lower()
        if q:
            devices = [d for d in devices
                       if q in d.get("name", "").lower() or q in d.get("host", "").lower()]
        if self.var_vendor.get() != self.VENDOR_LABEL_HINT:
            label = self.var_vendor.get()
            for v in service.vendor_options():
                if v["label"] == label:
                    devices = [d for d in devices if d.get("vendor") == v["value"]]
        if self.var_state.get() == "启用":
            devices = [d for d in devices if d.get("enabled")]
        elif self.var_state.get() == "停用":
            devices = [d for d in devices if not d.get("enabled")]
        return devices

    def _labels(self) -> tuple[dict[str, str], dict[str, str]]:
        vendor_labels: dict[str, str] = {}
        type_labels: dict[str, str] = {}
        for v in service.vendor_options():
            vendor_labels[v["value"]] = v["label"]
            for t in v["device_types"]:
                type_labels[t["value"]] = t["label"]
        return vendor_labels, type_labels

    def refresh(self) -> None:
        opts = service.vendor_options()
        self.cb_vendor.configure(
            values=[self.VENDOR_LABEL_HINT] + [v["label"] for v in opts])
        vendor_labels, type_labels = self._labels()

        kept = checked_rows(self.tree)  # 刷新后勾选不丢
        clear_tree(self.tree)
        for d in self._filtered():
            insert_row(self.tree, (
                d.get("name", ""), d.get("host", ""),
                vendor_labels.get(d.get("vendor", ""), d.get("vendor", "")),
                type_labels.get(d.get("device_type", ""), d.get("device_type", "")),
                LOGIN_LABELS.get(d.get("login_method", ""), d.get("login_method", "")),
                d.get("customer") or "未指定",
                "启用" if d.get("enabled", True) else "停用",
            ), iid=str(d.get("name")))
        keep_checks(self.tree, kept)
        colorize_rows(self.tree, "state")
        self.app.set_status(f"设备 {len(self.app.devices.list())} 台")

    def _selected(self) -> list[str]:
        return list(self.tree.selection())

    # -- 操作 --
    def _import(self) -> None:
        """批量导入台账(xlsx/csv/docx,智能识别字段)。"""
        from patrol.desktop.dialogs import ImportDialog

        dlg = ImportDialog(self, self.app.devices, self.app.customers)
        if dlg.show():
            self.app.set_status("批量导入完成")
            self.app.broadcast_refresh()
            self.refresh()

    def _create(self) -> None:
        dlg = DeviceDialog(self, self.app.devices, self.app.customers)
        if dlg.show():
            self.app.set_status("设备已保存")
            self.refresh()

    def _edit(self) -> None:
        names = self._selected()
        if len(names) != 1:
            messagebox.showinfo("提示", "请先选中一台设备再编辑", parent=self)
            return
        device = self.app.devices.get(names[0])
        if not device:
            return
        dlg = DeviceDialog(self, self.app.devices, self.app.customers, device)
        if dlg.show():
            self.app.set_status("设备已更新")
            self.refresh()

    def _toggle(self) -> None:
        for name in target_rows(self.tree):
            device = self.app.devices.get(name)
            if device:
                self.app.devices.update(
                    name, {"enabled": not device.get("enabled", True)})
        self.refresh()

    def _delete(self) -> None:
        names = target_rows(self.tree)  # 勾选框多选优先,无勾选退回点选
        if not names:
            messagebox.showinfo("提示", "请先勾选或选中要删除的设备", parent=self)
            return
        if not messagebox.askyesno("确认删除", f"确定删除 {len(names)} 台设备?",
                                   parent=self):
            return
        for name in names:
            try:
                self.app.devices.delete(name)
            except KeyError:
                pass
        self.app.set_status(f"已删除 {len(names)} 台设备")
        self.refresh()

    _batch_delete = _delete


# ── 客户管理 ────────────────────────────────────────────────────


class CustomersPanel(BasePanel):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._header("客户管理", "甲方公司档案,设备按归属客户统计")

        btns = tk.Frame(self.body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="新建客户", style="Accent.TButton",
                   command=self._create).pack(side="left")
        ttk.Button(btns, text="编辑", command=self._edit).pack(side="left", padx=6)
        ttk.Button(btns, text="删除", style="Danger.TButton",
                   command=self._delete).pack(side="left", padx=6)
        ttk.Button(btns, text="刷新", command=self.refresh).pack(side="right")

        self.tree, wrap = make_tree(self.body, [
            ("name", "客户名称", 180), ("contact", "联系人", 110),
            ("phone", "联系电话", 130), ("devices", "设备数", 70),
            ("remark", "备注", 240),
        ], height=14, checkbox=True)
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit(), add="+")

    def refresh(self) -> None:
        counts = service.device_count_by_customer(self.app.devices)
        kept = checked_rows(self.tree)  # 刷新后勾选不丢
        clear_tree(self.tree)
        for c in self.app.customers.list():
            insert_row(self.tree, (
                c.get("name", ""), c.get("contact", ""), c.get("phone", ""),
                counts.get(c.get("name", ""), 0), c.get("remark", ""),
            ), iid=str(c.get("name")))
        keep_checks(self.tree, kept)
        self.app.set_status(f"客户 {len(self.app.customers.list())} 家")

    def _selected(self) -> list[str]:
        return list(self.tree.selection())

    def _create(self) -> None:
        dlg = CustomerDialog(self, self.app.customers, self.app.devices)
        if dlg.show():
            self.app.set_status("客户已保存")
            self.app.broadcast_refresh()
            self.refresh()

    def _edit(self) -> None:
        names = self._selected()
        if len(names) != 1:
            messagebox.showinfo("提示", "请先选中一家客户再编辑", parent=self)
            return
        customer = self.app.customers.get(names[0])
        if not customer:
            return
        dlg = CustomerDialog(self, self.app.customers, self.app.devices, customer)
        if dlg.show():
            self.app.set_status("客户已更新(设备归属已同步)")
            self.app.broadcast_refresh()
            self.refresh()

    def _delete(self) -> None:
        names = target_rows(self.tree)  # 勾选框多选优先,无勾选退回点选
        if not names:
            messagebox.showinfo("提示", "请先勾选或选中要删除的客户", parent=self)
            return
        if not messagebox.askyesno("确认删除", f"确定删除 {len(names)} 家客户?",
                                   parent=self):
            return
        for name in names:
            try:
                self.app.customers.delete(name)
            except KeyError:
                pass
        self.app.set_status(f"已删除 {len(names)} 家客户")
        self.refresh()


# ── 巡检任务 ────────────────────────────────────────────────────


class TasksPanel(BasePanel):
    POLL_MS = 1500

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._header("巡检任务", "选中设备一键巡检,自动产出 HTML 报告")
        self._poll_job: str | None = None

        # 报告操作按钮置顶:不放在滚动内容之下,矮窗口也始终可见可点
        self._seen_done: set[str] = set()  # 已提示过完成的任务,避免重复弹窗
        self._inflight: set[str] = set()    # 本次会话内发起的任务,完成才提示

        btns = tk.Frame(self.body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="查看报告(预览)",
                   command=self._preview).pack(side="left")
        ttk.Button(btns, text="打开报告文件",
                   command=self._open_report).pack(side="left", padx=6)
        ttk.Button(btns, text="导出 Word", command=self._export_word).pack(
            side="left")
        ttk.Button(btns, text="导出 Excel", command=self._export_excel).pack(
            side="left", padx=6)
        ttk.Button(btns, text="刷新", command=self._refresh_tasks).pack(side="right")

        top = tk.Frame(self.body, bg=COLORS["bg"])
        top.pack(fill="both", expand=True, pady=(0, 8))

        pick_card, pick_body = card(top, "选择巡检设备(启用中的)")

        # 客户筛选:只巡检某家甲方公司的设备
        cust_bar = tk.Frame(pick_body, bg=COLORS["card"])
        cust_bar.pack(fill="x", pady=(0, 6))
        tk.Label(cust_bar, text="按客户筛选:", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["ui"]).pack(side="left")
        self.cmb_customer = ttk.Combobox(
            cust_bar, state="readonly", width=26, font=FONTS["ui"])
        self.cmb_customer.pack(side="left", padx=(6, 0))
        self.cmb_customer.bind(
            "<<ComboboxSelected>>", lambda e: self._reload_devices())
        ttk.Button(cust_bar, text="巡检本单位", style="Accent.TButton",
                   command=self._run_customer).pack(side="left", padx=10)

        self.list_devices = tk.Listbox(
            pick_body, selectmode="extended", height=6, font=FONTS["ui"],
            bg=COLORS["card"], fg=COLORS["text"], relief="flat",
            highlightthickness=1, highlightbackground=COLORS["border"],
            exportselection=False,
        )
        self.list_devices.pack(fill="both", expand=True)
        # 设备列表自身可滚(滚轮落在列表上时滚动列表,而非整个面板)
        self.list_devices.bind("<MouseWheel>", lambda e: self.list_devices.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))

        ops = tk.Frame(pick_body, bg=COLORS["card"])
        ops.pack(fill="x", pady=(8, 0))
        ttk.Button(ops, text="全选",
                   command=lambda: self.list_devices.select_set(0, "end")).pack(side="left")
        ttk.Button(ops, text="清空选择",
                   command=lambda: self.list_devices.select_clear(0, "end")).pack(
            side="left", padx=6)
        # 开始巡检独占整行撑满卡片宽:窄面板下也完整可见不再被裁
        self.btn_run = ttk.Button(pick_body, text="开始巡检", style="Accent.TButton",
                                  command=self._run)
        self.btn_run.pack(fill="x", pady=(8, 0))

        task_card, task_body = card(top, "任务进度(自动刷新)")
        self.tree, wrap = make_tree(task_body, [
            ("device", "设备", 130), ("host", "管理地址", 120),
            ("status", "状态", 80), ("started", "开始时间", 145),
            ("finished", "完成时间", 145), ("report", "报告/错误", 190),
        ], height=7)
        wrap.pack(fill="both", expand=True)
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=3)
        top.rowconfigure(0, weight=1)
        pick_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        task_card.grid(row=0, column=1, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self._preview())

    def refresh(self) -> None:
        # 客户下拉选项随客户管理增删同步(保持当前筛选)
        names = [c.get("name", "") for c in self.app.customers.list()]
        current = self.cmb_customer.get()
        self.cmb_customer["values"] = ["全部客户"] + names
        if current not in list(self.cmb_customer["values"]):
            current = "全部客户"
        self.cmb_customer.set(current)
        self._reload_devices()
        self._refresh_tasks()
        self._schedule_poll()

    def _reload_devices(self) -> None:
        """按客户筛选填充设备列表(设备名后的括号内附客户名)。"""
        customer = self.cmb_customer.get()
        selected = set(self.list_devices.get(0, "end"))
        self.list_devices.delete(0, "end")
        for d in self.app.devices.list():
            if not d.get("enabled", True):
                continue
            if customer and customer != "全部客户" and d.get("customer", "") != customer:
                continue
            host = d.get("host")
            cname = d.get("customer") or ""
            label = f"{d.get('name')}  ({host} · {cname})" if cname \
                else f"{d.get('name')}  ({host})"
            self.list_devices.insert("end", label)
            if label in selected:
                self.list_devices.selection_set("end")

    def _schedule_poll(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        try:
            self._poll_job = self.after(self.POLL_MS, self._tick)
        except tk.TclError:  # pragma: no cover - 窗口销毁
            pass

    def _tick(self) -> None:
        self._poll_job = None
        if not self.winfo_exists():  # pragma: no cover
            return
        self._refresh_tasks()
        self._schedule_poll()

    def _refresh_tasks(self) -> None:
        tasks = sorted(self.app.tasks.list_all(),
                       key=lambda t: t.get("created_at", ""), reverse=True)
        # 轮询刷新前记住选中行,重插后恢复(否则选中状态每 1.5s 被清空,
        # 用户点"查看报告/打开报告"时会提示未选中任务)
        kept = set(self.tree.selection())
        clear_tree(self.tree)
        for t in tasks:
            self.tree.insert("", "end", iid=t.get("task_id", ""), values=(
                t.get("device_name", ""), t.get("device_host", ""),
                TASK_LABELS.get(t.get("status", ""), t.get("status", "")),
                (t.get("started_at") or "")[:19].replace("T", " "),
                (t.get("finished_at") or "")[:19].replace("T", " "),
                t.get("report_file") or t.get("error") or "",
            ))
        for iid in kept:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        colorize_rows(self.tree)
        running = sum(1 for t in tasks if t.get("status") in ("pending", "running"))
        self.app.set_status(
            f"任务 {len(tasks)} 条" + (f",{running} 条进行中" if running else ""))

        # 本次发起的任务刚完成:一次性提示(每任务只提示一次)
        fresh = [t for t in tasks
                 if t.get("task_id") in self._inflight
                 and t.get("status") in ("completed", "failed")
                 and t.get("task_id") not in self._seen_done]
        for t in fresh:
            self._seen_done.add(t.get("task_id", ""))
            self._inflight.discard(t.get("task_id", ""))
            name = t.get("device_name", "")
            if t.get("status") == "completed":
                bad = int(t.get("error_count") or 0)
                warn = f"\n\n注意:其中 {bad} 台设备采集异常,详见报告。" if bad else ""
                msg = (f"「{name}」巡检完成。{warn}\n\n是否立即预览报告?\n"
                       f"(也可稍后用顶部按钮:预览 / 导出 Word / 导出 Excel)")
                if messagebox.askyesno("巡检完成", msg, parent=self):
                    self._preview()
            else:
                err = t.get("error", "未知原因")
                messagebox.showwarning(
                    "巡检失败", f"「{name}」巡检失败:\n{err}", parent=self)
            break  # 一次只弹一个,余下轮次再提示

    def _run(self) -> None:
        labels = [self.list_devices.get(i) for i in self.list_devices.curselection()]
        if not labels:
            messagebox.showinfo("提示", "请先选中要巡检的设备", parent=self)
            return
        names = [label.split("  (")[0] for label in labels]
        # 合并巡检:选 N 台只产一份整体报告(乙方交付形态)
        try:
            task = self.app.task_manager.create_batch_task(names)
            self._inflight.add(task.task_id)
            self.app.set_status(
                f"已提交合并巡检(共 {len(names)} 台设备),后台执行中…")
        except KeyError as e:
            messagebox.showwarning("无法创建任务", str(e), parent=self)
        self._refresh_tasks()

    def _run_customer(self) -> None:
        """一键巡检当前筛选客户名下的全部启用设备(销号清单 #5)。

        筛选为"全部客户"时即对全部启用设备发起。
        """
        customer = self.cmb_customer.get()
        targets = [d for d in self.app.devices.list()
                   if d.get("enabled", True)
                   and (customer == "全部客户"
                        or d.get("customer", "") == customer)]
        if not targets:
            messagebox.showinfo(
                "提示", f"「{customer}」名下暂无启用的设备", parent=self)
            return
        label = customer if customer != "全部客户" else "全部设备"
        if not messagebox.askyesno(
                "确认巡检",
                f"即将对「{label}」共 {len(targets)} 台设备发起巡检,"
                "合并为一份整体报告,继续?",
                parent=self):
            return
        names = [d.get("name", "") for d in targets]
        try:
            task = self.app.task_manager.create_batch_task(names)
            self._inflight.add(task.task_id)
            self.app.set_status(
                f"已对「{label}」提交合并巡检(共 {len(names)} 台),后台执行中…")
        except KeyError as e:
            messagebox.showwarning("无法创建任务", str(e), parent=self)
        self._refresh_tasks()

    def _selected_task(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _target_report_task(self) -> dict | None:
        """预览/打开的目标任务:优先当前选中行,否则自动取最近一条有报告的完成任务。

        刚跑完巡检的用户意图就是看最新报告,不应被"请先选中"卡住。
        自动命中时把该行设为选中,便于后续操作。
        """
        task_id = self._selected_task()
        task = self.app.tasks.get(task_id) if task_id else None
        if task and task.get("report_file"):
            return task
        for t in sorted(self.app.tasks.list_all(),
                        key=lambda t: t.get("created_at", ""), reverse=True):
            if t.get("status") == "completed" and t.get("report_file"):
                tid = t.get("task_id", "")
                if self.tree.exists(tid):
                    self.tree.selection_set(tid)
                    self.tree.see(tid)
                return t
        return task

    def _no_report_hint(self, task: dict | None) -> str:
        """拿不到报告时按任务状态给出可行动的提示(而非一句'没有报告')。"""
        if not task:
            return ("暂无已产出报告的任务,请先在左侧勾选设备并点击「开始巡检」,"
                    "报告生成后即可查看")
        name = task.get("device_name", "")
        status = task.get("status", "")
        if status in ("pending", "running"):
            return (f"「{name}」的巡检还在进行中,报告生成后自动可用;"
                    "任务表每几秒自动刷新,完成后再点本按钮即可查看")
        if status == "failed":
            return (f"「{name}」的巡检执行失败,没有产出报告:\n"
                    f"{task.get('error') or '未知错误'}")
        return f"「{name}」的任务还没有产出报告"

    def _preview(self) -> None:
        task = self._target_report_task()
        filename = (task or {}).get("report_file")
        if not filename:
            messagebox.showinfo("提示", self._no_report_hint(task), parent=self)
            return
        ReportPreviewDialog(self, filename).show()

    def _open_report(self) -> None:
        task = self._target_report_task()
        filename = (task or {}).get("report_file")
        if not filename:
            messagebox.showinfo("提示", self._no_report_hint(task), parent=self)
            return
        path = Path("output") / filename
        if not path.exists():
            messagebox.showerror(
                "打开失败",
                f"报告文件不存在:\n{path.resolve()}\n\n可能已被删除或移动,"
                "可到「报告管理」查看现有报告。", parent=self)
            return
        try:
            service.open_path(path)
        except (RuntimeError, OSError) as e:
            messagebox.showerror("打开失败", str(e), parent=self)

    def _export_word(self) -> None:
        formal = messagebox.askyesno(
            "报告版本",
            "是否导出为【正式汇报版】?\n\n"
            "是:正式版(封面信息+签字盖章页,不含原始回显,给甲方领导)\n"
            "否:工程明细版(含全部检查明细与原始回显,给双方工程师)",
            parent=self)
        self._export_report("Word", formal=formal)

    def _export_excel(self) -> None:
        self._export_report("Excel")

    def _export_report(self, kind: str, formal: bool = False) -> None:
        """对最近完成的任务导出 Word/Excel(后台线程,完成后可打开)。"""
        task = self._target_report_task()
        filename = (task or {}).get("report_file")
        if not filename:
            messagebox.showinfo("提示", "暂无已产出报告的任务,请先发起巡检", parent=self)
            return

        def work(fname):
            if kind == "Word":
                return service.export_word(fname, formal=formal)
            return service.export_excel(fname)

        def done(path):
            self.app.set_status(f"已生成 {path.name}")
            _maybe_email(path, task)

        def fail(exc):
            messagebox.showerror("导出失败", str(exc), parent=self)

        def _maybe_email(path, task):
            if not messagebox.askyesno(
                    "导出成功",
                    f"已生成 {path.name}\n\n是否打开文件?",
                    parent=self):
                _ask_send(path, task)
                return
            service.open_path(path)
            _ask_send(path, task)

        def _ask_send(path, task):
            """邮件分发:按本次任务涉及的设备汇总各客户接收邮箱(SMTP 启用时逐客户询问)。

            task 是发起导出时锁定的任务:导出期间列表选中项可能已变,
            不能事后再取"目标任务"(否则可能把 A 客户的报告发给 B 客户)。
            """
            try:
                if not service.smtp_config().get("enabled"):
                    return  # SMTP 未启用,静默跳过
                targets = service.email_targets(
                    task, self.app.devices, self.app.customers)
                if not targets:
                    return  # 客户未配邮箱,静默跳过
            except Exception:  # noqa: BLE001
                return

            def send_ok(r):
                self.app.set_status(r["message"])
                messagebox.showinfo("邮件分发", r["message"], parent=self)

            def send_fail(exc):
                messagebox.showerror("邮件分发", str(exc), parent=self)

            for customer, emails in targets.items():
                if not messagebox.askyesno(
                        "邮件分发",
                        f"是否把报告发送给「{customer}」接收邮箱?",
                        parent=self):
                    continue
                run_in_thread(
                    self,
                    lambda c=customer, to=emails: service.send_report_email(
                        to,
                        subject=f"网络设备巡检报告 - {c}",
                        body=(f"{c}:\n\n"
                              "附件为最新网络设备巡检报告,请查收。\n\n"
                              "(本邮件由昊云网络巡检助手自动发送)"),
                        attachments=[path],
                        cc=service.smtp_config().get("cc_boss", []) or []),
                    on_done=send_ok, on_error=send_fail)

        run_in_thread(self, lambda: work(filename), on_done=done, on_error=fail)


# ── 报告管理 ────────────────────────────────────────────────────


class ReportsPanel(BasePanel):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._header("报告管理")  # 页面不放解释性文字

        btns = tk.Frame(self.body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="预览", style="Accent.TButton",
                   command=self._preview).pack(side="left")
        ttk.Button(btns, text="AI 分析", command=self._ai).pack(side="left", padx=6)
        ttk.Button(btns, text="导出 Word", command=self._word).pack(side="left", padx=6)
        ttk.Button(btns, text="导出 Excel", command=self._excel).pack(side="left", padx=6)
        ttk.Button(btns, text="导出 PDF", command=self._pdf).pack(side="left", padx=6)
        ttk.Button(btns, text="打开文件", command=self._open).pack(side="left", padx=6)
        ttk.Button(btns, text="删除", style="Danger.TButton",
                   command=self._delete).pack(side="left", padx=6)
        ttk.Button(btns, text="批量删除", style="Danger.TButton",
                   command=self._delete).pack(side="left", padx=6)
        ttk.Button(btns, text="刷新", command=self.refresh).pack(side="right")

        self.tree, wrap = make_tree(self.body, [
            ("name", "报告文件", 330), ("size", "大小", 90),
            ("modified", "生成时间", 140), ("ai", "AI 分析", 90),
        ], height=15, checkbox=True)
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._preview(), add="+")

    def refresh(self) -> None:
        reports = service.list_reports()
        kept = checked_rows(self.tree)  # 刷新后勾选不丢
        clear_tree(self.tree)
        for r in reports:
            insert_row(self.tree, (
                r["name"], r["size"], r["modified"],
                "已分析" if r["has_ai"] else ("可分析" if r["has_preview"] else "—"),
            ), iid=r["name"])
        keep_checks(self.tree, kept)
        self.app.set_status(f"报告 {len(reports)} 份")

    def _selected(self) -> list[str]:
        return list(self.tree.selection())

    def _need_one(self, action: str) -> str | None:
        names = self._selected()
        if len(names) != 1:
            messagebox.showinfo("提示", f"请先选中一份报告再{action}", parent=self)
            return None
        return names[0]

    def _preview(self) -> None:
        filename = self._need_one("预览")
        if filename:
            ReportPreviewDialog(self, filename).show()

    def _ai(self) -> None:
        filename = self._need_one("分析")
        if not filename:
            return

        def done(_result):
            self.app.set_status(f"AI 分析完成:{filename}")
            self.refresh()
            if messagebox.askyesno("AI 分析完成", "是否查看分析结果?", parent=self):
                ReportPreviewDialog(self, filename).show()

        def fail(exc):
            messagebox.showerror("AI 分析失败", str(exc), parent=self)

        run_in_thread(self, lambda: service.run_ai_analysis(filename),
                      on_done=done, on_error=fail)

    def _export(self, kind: str) -> None:
        filename = self._need_one(f"导出{kind}")
        if not filename:
            return
        work = {"Word": service.export_word,
                "PDF": service.export_pdf,
                "Excel": service.export_excel}[kind]

        def done(path):
            self.app.set_status(f"已生成 {path.name}")
            self.refresh()
            if messagebox.askyesno("导出成功", f"已生成 {path.name},是否打开?",
                                   parent=self):
                service.open_path(path)

        def fail(exc):
            messagebox.showerror("导出失败", str(exc), parent=self)

        run_in_thread(self, lambda: work(filename), on_done=done, on_error=fail)

    def _word(self) -> None:
        self._export("Word")

    def _pdf(self) -> None:
        self._export("PDF")

    def _excel(self) -> None:
        self._export("Excel")

    def _open(self) -> None:
        filename = self._need_one("打开")
        if not filename:
            return
        try:
            service.open_path(Path("output") / filename)
        except RuntimeError as e:
            messagebox.showerror("打开失败", str(e), parent=self)

    def _delete(self) -> None:
        names = target_rows(self.tree)  # 勾选框多选优先,无勾选退回点选
        if not names:
            messagebox.showinfo("提示", "请先勾选或选中要删除的报告", parent=self)
            return
        if not messagebox.askyesno("确认删除",
                                   f"确定删除 {len(names)} 份报告(连同数据文件)?",
                                   parent=self):
            return
        count = service.delete_reports(names)
        self.app.set_status(f"已删除 {count} 份报告")
        self.refresh()
