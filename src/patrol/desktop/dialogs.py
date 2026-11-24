"""桌面小工具对话框:设备/客户表单、报告预览、文本查看"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from patrol.desktop import service
from patrol.desktop.widgets import COLORS, FONTS, card, form_row


class _BaseDialog(tk.Toplevel):
    """模态对话框基类。"""

    def __init__(self, parent: tk.Misc, title: str, width: int = 560, height: int = 0):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.resizable(False, False)
        self.result = False
        self._width = width
        self._auto_height = not height  # 未指定高度 = 按内容自适应
        if height:
            self.geometry(f"{width}x{height}")
        else:
            self.geometry(f"{width}x{self.winfo_screenheight() // 2}")
        # 内容置于可滚动区:表单超长时滚轮可达,底部按钮永不被裁
        outer = tk.Frame(self, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        self._canvas = tk.Canvas(outer, bg=COLORS["bg"], highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._body = tk.Frame(self._canvas, bg=COLORS["bg"])
        self._body_win = self._canvas.create_window(
            (0, 0), window=self._body, anchor="nw")
        self._canvas.configure(yscrollcommand=vsb.set)
        self._body.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._body_win, width=e.width))
        vsb.pack(side="right", fill="y")
        self._canvas.pack(fill="both", expand=True)
        self._scroll_canvas = self._canvas  # 主窗口滚轮统一走这里
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _fit_height(self) -> None:
        """高度随内容自适应(不超出屏幕):表单再长,保存按钮也完整可见。"""
        self.update_idletasks()
        avail = max(self.winfo_screenheight() - 140, 480)
        # _body 请求高度 + 外框上下 padding(16*2)+ 余量
        h = min(self._body.winfo_reqheight() + 34, avail)
        self.geometry(f"{self._width}x{h}")

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    def show(self) -> bool:
        """模态显示,关闭后返回是否保存成功。"""
        if self._auto_height:
            self._fit_height()
        self._center()
        self.wait_window()
        return self.result


class DeviceDialog(_BaseDialog):
    """新增/编辑设备;保存成功 result=True。"""

    def __init__(self, parent, devices, customers, device: dict | None = None):
        super().__init__(parent, "新建设备" if device is None else f"编辑设备 - {device.get('name', '')}", width=640)
        self._devices = devices
        self._customers = customers
        self._device = device or {}
        self._is_edit = device is not None
        self._build()

    # -- 构建 --
    def _build(self) -> None:
        _, body = card(self._body, "设备信息", fill="both", expand=True)
        self._body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        opts = service.vendor_options()
        self._opts = opts
        vendor_labels = [v["label"] for v in opts]

        self.var_name = tk.StringVar(value=str(self._device.get("name", "")))
        self.var_customer = tk.StringVar(value=str(self._device.get("customer", "") or "未指定"))
        self.var_host = tk.StringVar(value=str(self._device.get("host", "")))
        self.var_vendor = tk.StringVar()
        self.var_type = tk.StringVar()
        self.var_login = tk.StringVar(value=str(self._device.get("login_method", "ssh")))
        self.var_port = tk.StringVar(value=str(self._device.get("port", 22)))
        self.var_web_port = tk.StringVar(value=str(self._device.get("web_port", 443)))
        self.var_user = tk.StringVar(value=str(self._device.get("username", "")))
        self.var_pass = tk.StringVar()
        self.var_super = tk.StringVar()
        self.var_timeout = tk.StringVar(value=str(self._device.get("timeout", 30)))
        self.var_cmd_timeout = tk.StringVar(value=str(self._device.get("command_timeout", 120)))
        self.var_skip_tls = tk.BooleanVar(value=not bool(self._device.get("verify_ssl", True)))
        self.var_enabled = tk.BooleanVar(value=bool(self._device.get("enabled", True)) if self._is_edit else True)

        e_name = ttk.Entry(body, textvariable=self.var_name, state="disabled" if self._is_edit else "normal")
        customer_names = ["未指定"] + [c["name"] for c in self._customers.list()]
        cb_customer = ttk.Combobox(body, textvariable=self.var_customer,
                                   values=customer_names, state="readonly")
        e_host = ttk.Entry(body, textvariable=self.var_host)

        cb_vendor = ttk.Combobox(body, textvariable=self.var_vendor,
                                 values=vendor_labels, state="readonly")
        cb_type = ttk.Combobox(body, textvariable=self.var_type, state="readonly")
        self._cb_type = cb_type

        cb_login = ttk.Combobox(body, textvariable=self.var_login,
                                values=["ssh", "telnet", "snmp", "console",
                                        "web", "api"],
                                state="readonly")
        # 登录方式切换联动默认端口(SSH 22 / Telnet 23)
        def _sync_port(*_):
            if self.var_login.get() == "ssh":
                self.var_port.set("22")
            elif self.var_login.get() == "telnet":
                self.var_port.set("23")
            elif self.var_login.get() == "snmp":
                self.var_port.set("161")
        self.var_login.trace_add("write", _sync_port)
        sp_port = ttk.Spinbox(body, from_=1, to=65535, textvariable=self.var_port, width=8)
        sp_web = ttk.Spinbox(body, from_=1, to=65535, textvariable=self.var_web_port, width=8)
        e_user = ttk.Entry(body, textvariable=self.var_user)
        e_pass = ttk.Entry(body, textvariable=self.var_pass, show="●")
        e_super = ttk.Entry(body, textvariable=self.var_super, show="●")
        sp_timeout = ttk.Spinbox(body, from_=1, to=300, textvariable=self.var_timeout, width=8)
        sp_cmd = ttk.Spinbox(body, from_=1, to=600, textvariable=self.var_cmd_timeout, width=8)

        rows = [
            ("设备名称", e_name, "同名设备不可重复"),
            ("归属客户", cb_customer, "需先在客户管理中添加"),
            ("管理地址", e_host, "IP 或主机名"),
            ("厂商", cb_vendor, ""),
            ("设备类型", cb_type, "随厂商联动"),
            ("登录方式", cb_login, "ssh / telnet / web / api"),
            ("登录端口", sp_port, ""),
            ("Web 端口", sp_web, "API/Web 采集用"),
            ("登录用户名", e_user, ""),
            ("登录密码", e_pass, "编辑时留空保持原密码"),
            ("提权密码", e_super, "super,无则留空"),
            ("连接超时(秒)", sp_timeout, ""),
            ("命令超时(秒)", sp_cmd, ""),
        ]
        for i, (label, widget, note) in enumerate(rows):
            form_row(body, i, label, widget, note)
        row = len(rows)
        # 自动识别行(U-2:填 IP+账号密码一键判厂商/型号)
        detect_bar = tk.Frame(body, bg=COLORS["card"])
        detect_bar.grid(row=row, column=1, sticky="w", pady=2)
        self._btn_detect = ttk.Button(detect_bar, text="自动识别",
                                      command=self._autodetect)
        self._btn_detect.pack(side="left")
        self.lbl_detect = tk.Label(detect_bar, text="填好地址/用户名/密码后点击",
                                   bg=COLORS["card"], fg=COLORS["muted"],
                                   font=FONTS["small"])
        self.lbl_detect.pack(side="left", padx=8)
        tk.Checkbutton(body, text="跳过 HTTPS 证书校验(自签名证书)",
                       variable=self.var_skip_tls, bg=COLORS["card"],
                       activebackground=COLORS["card"], anchor="w").grid(
            row=row, column=1, sticky="w", pady=2)
        tk.Checkbutton(body, text="启用该设备(纳入巡检)",
                       variable=self.var_enabled, bg=COLORS["card"],
                       activebackground=COLORS["card"], anchor="w").grid(
            row=row + 1, column=1, sticky="w", pady=2)

        self.lbl_error = tk.Label(self._body, text="", bg=COLORS["error_bg"],
                                  fg=COLORS["fail"], font=FONTS["small"],
                                  anchor="w", padx=10, pady=6)

        btns = tk.Frame(self._body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self._on_ok).pack(side="right", padx=(0, 8))

        cb_vendor.bind("<<ComboboxSelected>>", self._on_vendor_change)

        # 回填当前厂商/类型
        vendor_id = str(self._device.get("vendor") or (opts[0]["value"] if opts else ""))
        self._select_vendor(vendor_id)
        if self._is_edit:
            self._select_type(str(self._device.get("device_type", "")))

    def _select_vendor(self, vendor_id: str) -> None:
        for v in self._opts:
            if v["value"] == vendor_id:
                self.var_vendor.set(v["label"])
                self._fill_types(v)
                return
        if self._opts:
            self.var_vendor.set(self._opts[0]["label"])
            self._fill_types(self._opts[0])

    def _fill_types(self, vendor: dict) -> None:
        types = vendor.get("device_types", [])
        self._cb_type.configure(values=[t["label"] for t in types])
        if types and not self.var_type.get():
            self.var_type.set(types[0]["label"])

    def _select_type(self, type_id: str) -> None:
        for v in self._opts:
            if v["label"] != self.var_vendor.get():
                continue
            for t in v["device_types"]:
                if t["value"] == type_id:
                    self.var_type.set(t["label"])
                    return

    def _on_vendor_change(self, _event=None) -> None:
        for v in self._opts:
            if v["label"] == self.var_vendor.get():
                self.var_type.set("")
                self._fill_types(v)
                return

    # -- 采集 --
    def collect(self) -> dict:
        """收集表单字段(校验转换失败抛 ValueError)。"""
        vendor_id = device_type_id = ""
        for v in self._opts:
            if v["label"] == self.var_vendor.get():
                vendor_id = v["value"]
                for t in v["device_types"]:
                    if t["label"] == self.var_type.get():
                        device_type_id = t["value"]
        try:
            port = int(self.var_port.get())
            web_port = int(self.var_web_port.get())
            timeout = int(self.var_timeout.get())
            cmd_timeout = int(self.var_cmd_timeout.get())
        except ValueError as e:
            raise ValueError(f"端口/超时必须是整数: {e}") from e

        return {
            "name": self.var_name.get().strip(),
            "customer": "" if self.var_customer.get() == "未指定" else self.var_customer.get(),
            "host": self.var_host.get(),
            "vendor": vendor_id or "h3c",
            "device_type": device_type_id or "comware_switch",
            "login_method": self.var_login.get() or "ssh",
            "port": port,
            "web_port": web_port,
            "username": self.var_user.get(),
            "password": self.var_pass.get(),
            "super_password": self.var_super.get(),
            "timeout": timeout,
            "command_timeout": cmd_timeout,
            "verify_ssl": not self.var_skip_tls.get(),
            "enabled": self.var_enabled.get(),
        }

    def _autodetect(self) -> None:
        """后台线程识别,成功后回填厂商/设备类型并提示型号。"""
        from tkinter import messagebox

        host = self.var_host.get().strip()
        user = self.var_user.get().strip()
        pass_ = self.var_pass.get()
        if not (host and user):
            messagebox.showinfo("提示", "请先填写管理地址与用户名", parent=self)
            return
        self._btn_detect.state(["disabled"])
        self.lbl_detect.configure(text="正在连接识别(最长约 30 秒)…",
                                  fg=COLORS["muted"])

        def done(data):
            self._btn_detect.state(["!disabled"])
            if data.get("ok") and data.get("result"):
                r = data["result"]
                for v in self._opts:
                    if v["value"] == r["vendor"]:
                        self.var_vendor.set(v["label"])
                        self.var_type.set("")
                        self._fill_types(v)
                        for t in v["device_types"]:
                            if t["value"] == r["device_type"]:
                                self.var_type.set(t["label"])
                        break
                self.lbl_detect.configure(
                    text=f"识别成功({data.get('method', '').upper()}):"
                         f"{r.get('model') or r['vendor']} "
                         f"{r.get('software_version', '')}",
                    fg=COLORS["text"])
            else:
                msg = data.get("error") or "已登录但无法识别厂商,请人工选择"
                self.lbl_detect.configure(text=msg[:60], fg=COLORS["fail"])

        def fail(exc):
            self._btn_detect.state(["!disabled"])
            self.lbl_detect.configure(text=f"识别失败:{exc}"[:60],
                                      fg=COLORS["fail"])

        from patrol.desktop.widgets import run_in_thread
        run_in_thread(
            self,
            lambda: service.autodetect(
                host, user, pass_,
                login_method=self.var_login.get() or "ssh",
                port=int(self.var_port.get() or 0)),
            on_done=done, on_error=fail)

    def _on_ok(self) -> None:
        try:
            fields = self.collect()
            service.save_device(
                self._devices, self._customers,
                None if not self._is_edit else self._device.get("name"),
                fields,
            )
        except (ValueError, KeyError) as e:
            self.lbl_error.configure(text=str(e))
            self.lbl_error.pack(fill="x", pady=(8, 0))
            if self._auto_height:  # 错误提示占位后重新贴合内容高度
                self._fit_height()
            return
        self.result = True
        self.destroy()


class CustomerDialog(_BaseDialog):
    """新增/编辑客户;保存成功 result=True。"""

    def __init__(self, parent, customers, devices, customer: dict | None = None):
        super().__init__(parent, "新建客户" if customer is None else f"编辑客户 - {customer.get('name', '')}", width=520)
        self._customers = customers
        self._devices = devices
        self._customer = customer or {}
        self._is_edit = customer is not None
        self._build()

    def _build(self) -> None:
        _, body = card(self._body, "客户信息", fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.var_name = tk.StringVar(value=str(self._customer.get("name", "")))
        self.var_contact = tk.StringVar(value=str(self._customer.get("contact", "")))
        self.var_phone = tk.StringVar(value=str(self._customer.get("phone", "")))
        self.var_email = tk.StringVar(value=str(self._customer.get("email", "")))
        self.var_remark = tk.StringVar(value=str(self._customer.get("remark", "")))

        rows = [
            ("客户名称", ttk.Entry(body, textvariable=self.var_name), "甲方公司名,不可重复"),
            ("联系人", ttk.Entry(body, textvariable=self.var_contact), ""),
            ("联系电话", ttk.Entry(body, textvariable=self.var_phone), ""),
            ("报告接收邮箱", ttk.Entry(body, textvariable=self.var_email),
             "巡检报告邮件分发收件人,多个用分号分隔"),
            ("备注", ttk.Entry(body, textvariable=self.var_remark), ""),
        ]
        for i, (label, widget, note) in enumerate(rows):
            form_row(body, i, label, widget, note)

        self.lbl_error = tk.Label(self._body, text="", bg=COLORS["error_bg"],
                                  fg=COLORS["fail"], font=FONTS["small"],
                                  anchor="w", padx=10, pady=6)

        btns = tk.Frame(self._body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self._on_ok).pack(side="right", padx=(0, 8))

    def collect(self) -> dict:
        return {
            "name": self.var_name.get(),
            "contact": self.var_contact.get(),
            "phone": self.var_phone.get(),
            "email": self.var_email.get(),
            "remark": self.var_remark.get(),
        }

    def _on_ok(self) -> None:
        try:
            service.save_customer(
                self._customers, self._devices,
                self._customer.get("name") if self._is_edit else None,
                self.collect(),
            )
        except (ValueError, KeyError) as e:
            self.lbl_error.configure(text=str(e))
            self.lbl_error.pack(fill="x", pady=(8, 0))
            if self._auto_height:  # 错误提示占位后重新贴合内容高度
                self._fit_height()
            return
        self.result = True
        self.destroy()


class TextViewerDialog(_BaseDialog):
    """只读长文本查看器(MIT 协议全文等)。"""

    def __init__(self, parent, title: str, text: str, width: int = 680, height: int = 520):
        super().__init__(parent, title, width=width, height=height)
        self.geometry(f"{width}x{height}")
        self.resizable(True, True)
        txt = tk.Text(self._body, wrap="word", font=("Consolas", 10),
                      bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                      padx=12, pady=12)
        vsb = ttk.Scrollbar(self._body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set, state="normal")
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        # Text 自滚(主窗口滚轮派发对 Text 控件不干预)
        txt.bind("<MouseWheel>", lambda e: txt.yview_scroll(
            -3 if e.delta > 0 else 3, "units"))
        vsb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        ttk.Button(self._body, text="关闭", command=self.destroy).pack(
            side="bottom", pady=(8, 0))


class ReportPreviewDialog(_BaseDialog):
    """报告结构化预览:设备概况 + AI 结论 + 风险项 + 全部检查项 + 原始输出。"""

    def __init__(self, parent, filename: str):
        super().__init__(parent, f"报告预览 - {filename}", width=960, height=640)
        self.geometry("960x640")
        self.resizable(True, True)
        self._filename = filename
        self._raw_map: dict[str, dict] = {}
        try:
            self._build()
        except Exception as e:  # noqa: BLE001 - 绝不留下加载失败的空窗口
            for w in self._body.winfo_children():
                w.destroy()
            tk.Label(self._body, text=f"报告预览加载失败: {e}",
                     bg=COLORS["error_bg"], fg=COLORS["fail"],
                     font=FONTS["ui"], anchor="w", padx=12, pady=10).pack(fill="x")
            ttk.Button(self._body, text="关闭", command=self.destroy).pack(pady=16)
        self._auto_height = True  # 预览高度随内容自适应,操作按钮不沉到折叠线以下

    def _build(self) -> None:
        from patrol.desktop.widgets import colorize_rows, make_tree, severity_cn

        try:
            data = service.load_report_data(self._filename)
        except (ValueError, FileNotFoundError) as e:
            tk.Label(self._body, text=str(e), bg=COLORS["error_bg"],
                     fg=COLORS["fail"], font=FONTS["ui"], anchor="w",
                     padx=12, pady=10).pack(fill="x")
            ttk.Button(self._body, text="关闭", command=self.destroy).pack(pady=16)
            return

        summary = service.report_summary(data)
        ai_text = service.format_ai_conclusion(summary["ai"])
        devices = data.get("devices", [])

        top = tk.Frame(self._body, bg=COLORS["bg"])
        top.pack(fill="x")
        tk.Label(top, text=self._filename, font=FONTS["h2"], bg=COLORS["bg"],
                 fg=COLORS["title"], anchor="w").pack(side="left")
        counts = (f"通过 {summary['total_pass']}    "
                  f"失败 {summary['total_fail']}    "
                  f"未知 {summary['total_unknown']}")
        tk.Label(top, text=counts, font=FONTS["ui_bold"], bg=COLORS["bg"],
                 fg=COLORS["muted"]).pack(side="right")

        # 设备概况:型号/版本/运行时长/采集时间/结果/采集异常全量展示,
        # 设备连接失败的报告(无检查项)也有数据可看
        _, dev_body = card(self._body, f"设备概况({len(devices)})", fill="x", pady=(8, 0))
        tree_dev, wrap_dev = make_tree(dev_body, [
            ("name", "设备", 110), ("host", "管理地址", 105),
            ("model", "型号", 85), ("version", "软件版本", 105),
            ("uptime", "运行时长", 95), ("collected", "采集时间", 115),
            ("counts", "结果", 115), ("error", "采集异常", 160),
        ], height=min(max(len(devices), 1), 5))
        tree_dev.tag_configure("fail", foreground=COLORS["fail"])
        for dev in devices:
            collected = str(dev.get("collected_at") or "")[:16].replace("T", " ")
            error = dev.get("error") or ""
            iid = tree_dev.insert("", "end", values=(
                dev.get("name", ""), dev.get("host", ""),
                dev.get("model") or "—", dev.get("software_version") or "—",
                dev.get("uptime") or "—", collected or "—",
                f"通过 {dev.get('pass_count', 0)}  失败 {dev.get('fail_count', 0)}"
                f"  未知 {dev.get('unknown_count', 0)}",
                error or "—",
            ))
            if error:
                tree_dev.item(iid, tags=("fail",))
        wrap_dev.pack(fill="x")

        if ai_text:
            _, ai_body = card(self._body, "AI 大模型结论", fill="x", pady=(8, 0))
            txt = tk.Text(ai_body, wrap="word", height=8, font=FONTS["ui"],
                          bg=COLORS["card"], fg=COLORS["text"], relief="flat")
            txt.insert("1.0", ai_text)
            txt.configure(state="disabled")
            txt.bind("<MouseWheel>", lambda e: txt.yview_scroll(
                -3 if e.delta > 0 else 3, "units"))
            txt.pack(fill="x")

        _, fail_body = card(self._body, f"风险项({len(summary['fail_items'])})",
                            fill="both", expand=True, pady=(8, 0))
        tree_fail, wrap_fail = make_tree(fail_body, [
            ("device", "设备", 120), ("category", "类别", 110),
            ("severity", "级别", 70), ("message", "问题描述", 380),
        ], height=6)
        for it in summary["fail_items"]:
            tree_fail.insert("", "end", values=(
                it["device_name"], it["category"],
                severity_cn(it["severity"]), it["message"]))
        wrap_fail.pack(fill="both", expand=True)
        colorize_rows(tree_fail, "severity")

        all_items = []
        for dev in devices:
            for item in dev.get("check_items", []):
                all_items.append({
                    "device": dev.get("name", ""),
                    "status": item.get("status", ""),
                    "category": item.get("category", ""),
                    "name": item.get("name", ""),
                    "command": item.get("command", ""),
                    "message": item.get("message", ""),
                    "raw": item.get("raw_output", ""),
                })
        _, all_body = card(self._body, f"全部检查项({len(all_items)})",
                           fill="both", expand=True, pady=(8, 0))
        self.tree_all, wrap_all = make_tree(all_body, [
            ("device", "设备", 105), ("status", "状态", 65),
            ("category", "类别", 90), ("name", "检查项", 120),
            ("command", "命令", 150), ("message", "检查说明", 230),
        ], height=6)
        for it in all_items:
            iid = self.tree_all.insert("", "end", values=(
                it["device"], it["status"], it["category"],
                it["name"], it["command"], it["message"]))
            self._raw_map[iid] = it
        wrap_all.pack(fill="both", expand=True)
        colorize_rows(self.tree_all)

        # 原始输出查看区:选中检查项即显示执行命令与设备回显,数据不再缺项
        _, raw_body = card(self._body, "原始输出", fill="x", pady=(8, 0))
        self.txt_raw = tk.Text(raw_body, wrap="none", height=6,
                               font=("Consolas", 9), bg="#F6F8FB",
                               fg=COLORS["text"], relief="flat", padx=10, pady=8)
        self.txt_raw.insert("1.0", "选中上方检查项,查看执行命令与设备原始输出。")
        self.txt_raw.configure(state="disabled")
        self.txt_raw.bind("<MouseWheel>", lambda e: self.txt_raw.yview_scroll(
            -3 if e.delta > 0 else 3, "units"))
        self.txt_raw.pack(fill="x")
        self.tree_all.bind("<<TreeviewSelect>>", self._on_select_item, add="+")
        if all_items:
            first = self.tree_all.get_children()[0]
            self.tree_all.selection_set(first)
            self.tree_all.see(first)
            self._show_item(first)

    def _on_select_item(self, _event=None) -> None:
        sel = self.tree_all.selection()
        if sel:
            self._show_item(sel[0])

    def _show_item(self, iid: str) -> None:
        it = self._raw_map.get(iid)
        if not it:
            return
        text = (
            f"检查项: {it['name']}    状态: {it['status']}\n"
            f"执行命令: {it['command'] or '—'}\n"
            f"结果说明: {it['message'] or '—'}\n"
            f"\n{it['raw'] or '(该项无原始输出)'}"
        )
        self.txt_raw.configure(state="normal")
        self.txt_raw.delete("1.0", "end")
        self.txt_raw.insert("1.0", text)
        self.txt_raw.configure(state="disabled")

        btns = tk.Frame(self._body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="导出 Word", command=self._export_word).pack(
            side="right", padx=(0, 8))
        ttk.Button(btns, text="打开 HTML 文件", command=self._open_file).pack(side="left")

    def _open_file(self) -> None:
        try:
            service.open_path(Path("output") / self._filename)
        except RuntimeError:
            pass

    def _export_word(self) -> None:
        from tkinter import messagebox

        try:
            path = service.export_word(self._filename)
        except Exception as e:  # noqa: BLE001 - 用户可见的失败提示
            messagebox.showerror("导出失败", str(e), parent=self)
            return
        if messagebox.askyesno("导出成功", f"已生成 {path.name},是否打开?",
                               parent=self):
            service.open_path(path)


class ImportDialog(_BaseDialog):
    """设备台账批量导入:选文件 → 智能识别预览 → 确认映射 → 导入。"""

    _FIELDS = [
        ("host", "登录地址 *"), ("username", "用户名 *"), ("password", "一级密码 *"),
        ("super_password", "Super 密码"), ("name", "设备名称"),
        ("login_method", "登录方式"), ("vendor", "厂商"), ("port", "端口"),
        ("customer", "归属单位"), ("remark", "备注"),
    ]

    def __init__(self, parent, devices, customers):
        super().__init__(parent, "批量导入设备(智能识别)", width=760)
        self._devices = devices
        self._customers = customers
        self._table = None
        self._matches: dict = {}
        self._build()

    def _build(self) -> None:
        _, body = card(self._body, "第 1 步:选择台账文件(xlsx / csv / docx)")
        self._file_label = tk.Label(body, text="未选择文件", anchor="w",
                                    bg=COLORS["card"], fg=COLORS["muted"],
                                    font=FONTS["ui"])
        self._file_label.pack(fill="x")
        ttk.Button(body, text="选择文件…", command=self._pick_file).pack(pady=(6, 0))

        self._map_card, map_body = card(
            self._body, "第 2 步:确认字段映射(自动识别,可修改)", fill="x")
        map_body.columnconfigure(1, weight=1)
        map_body.columnconfigure(3, weight=1)
        self._combos: dict[str, ttk.Combobox] = {}
        for i, (field, label) in enumerate(self._FIELDS):
            r, c = divmod(i, 2)
            tk.Label(map_body, text=label, bg=COLORS["card"], fg=COLORS["text"],
                     font=FONTS["ui"], width=12, anchor="w").grid(
                row=r, column=c * 2, sticky="w", padx=(0, 6), pady=3)
            cb = ttk.Combobox(map_body, state="readonly", font=FONTS["ui"])
            cb.grid(row=r, column=c * 2 + 1, sticky="ew", padx=(0, 12), pady=3)
            self._combos[field] = cb
        # 默认归属单位
        row = len(self._FIELDS) // 2 + 1
        tk.Label(map_body, text="默认归属单位", bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["ui"], width=12, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 6), pady=3)
        self._cb_customer_default = ttk.Combobox(
            map_body, state="readonly", font=FONTS["ui"],
            values=["不指定"] + [c.get("name", "") for c in self._customers.list()])
        self._cb_customer_default.current(0)
        self._cb_customer_default.grid(row=row, column=1, sticky="ew", pady=3)

        self._prev_card, prev_body = card(self._body, "数据预览(前 8 行)", fill="both")
        from patrol.desktop.widgets import make_tree
        self._tree, wrap = make_tree(prev_body, [], height=8)
        wrap.pack(fill="both", expand=True)

        btns = tk.Frame(self._body, bg=COLORS["bg"])
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="开始导入", style="Accent.TButton",
                   command=self._do_import).pack(side="left")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="left", padx=6)
        self._hint = tk.Label(btns, text="", bg=COLORS["bg"], fg=COLORS["muted"],
                              font=FONTS["small"])
        self._hint.pack(side="right")
        self._fit_height()

    def _pick_file(self) -> None:
        from tkinter import filedialog, messagebox

        from patrol.importer import detect_columns, read_table

        path = filedialog.askopenfilename(
            parent=self, title="选择台账文件",
            filetypes=[("台账文件", "*.xlsx *.xlsm *.csv *.docx"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            table = read_table(path)
        except Exception as e:  # noqa: BLE001 - 用户可见
            messagebox.showerror("读取失败", str(e), parent=self)
            return

        self._table = table
        self._file_label.configure(
            text=f"{Path(path).name} · {table.source} · 共 {len(table.rows)} 行",
            fg=COLORS["text"])
        self._matches = detect_columns(table.headers, table.rows)

        # 填充映射下拉:选项 = 各列"第N列:表头",默认选识别结果
        col_labels = [f"第{i+1}列: {h}" for i, h in enumerate(table.headers)]
        col_labels.insert(0, "— 不导入 —")
        for field, cb in self._combos.items():
            cb.configure(values=col_labels)
            m = self._matches.get(field)
            cb.current((m.column + 1) if m else 0)
        # 必填缺失提示
        missing = [lbl for f, lbl in self._FIELDS
                   if f in ("host", "username", "password") and f not in self._matches]
        self._hint.configure(
            text=("注意:请为 * 号必填项指定列" if missing else
                  f"已识别 {len(self._matches)} 个字段,共 {len(table.rows)} 行待导入"))

        # 数据预览表格
        from patrol.desktop.widgets import clear_tree
        self._tree.configure(columns=[f"c{i}" for i in range(len(table.headers))])
        for i, h in enumerate(table.headers):
            self._tree.heading(f"c{i}", text=h)
            self._tree.column(f"c{i}", width=90)
        clear_tree(self._tree)
        for row in table.rows[:8]:
            self._tree.insert("", "end", values=row + [""] * max(
                0, len(table.headers) - len(row)))

    def _do_import(self) -> None:
        from tkinter import messagebox

        from patrol.importer import import_rows

        if self._table is None:
            messagebox.showinfo("提示", "请先选择台账文件", parent=self)
            return
        mapping = {}
        for field, cb in self._combos.items():
            idx = cb.current()
            if idx > 0:  # 0 = 不导入
                mapping[field] = idx - 1
        for req in ("host", "username", "password"):
            if req not in mapping:
                messagebox.showwarning("缺少必填映射",
                                       "请为 地址/用户名/密码 指定对应列", parent=self)
                return
        if not messagebox.askyesno(
                "确认导入", f"即将按当前映射导入 {len(self._table.rows)} 行,继续?",
                parent=self):
            return

        default_customer = self._cb_customer_default.get()
        result = import_rows(
            self._devices, self._customers, self._table, mapping,
            default_customer="" if default_customer == "不指定" else default_customer,
        )
        summary = (f"成功导入 {result['created']} 台"
                   + (f",跳过 {result['skipped']} 行" if result["skipped"] else ""))
        if result["errors"]:
            errs = "\n".join(f"第{e['row']}行 {e['name']}: {e['reason']}"
                             for e in result["errors"][:10])
            messagebox.showwarning("导入完成(部分跳过)",
                                   f"{summary}\n\n跳过明细(前10条):\n{errs}", parent=self)
        else:
            messagebox.showinfo("导入完成", summary, parent=self)
        if result["created"]:
            self.result = True
