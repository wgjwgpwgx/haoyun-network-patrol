"""桌面小工具系统设置面板:产品信息 / 软件更新 / AI 大模型 / 账号安全"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from patrol import __version__
from patrol.ai.presets import PRESET_GROUPS, match_preset
from patrol.desktop import service
from patrol.desktop.views import BasePanel
from patrol.desktop.widgets import (
    COLORS,
    FONTS,
    LABEL_W,
    card,
    form_row,
    run_in_thread,
)
from patrol.product import (
    AUTHOR,
    AUTHOR_QQ,
    LICENSE_NAME,
    LICENSE_TEXT,
    PRODUCT_NAME,
    PRODUCT_NAME_EN,
)
from patrol.updater import is_frozen


def _preset_choices() -> tuple[list[str], dict[str, dict]]:
    """厂商预设下拉:「分组 · 预设名」→ 预设。"""
    choices: list[str] = []
    mapping: dict[str, dict] = {}
    for group, items in PRESET_GROUPS:
        for p in items:
            label = f"{group} · {p['name']}"
            choices.append(label)
            mapping[label] = p
    return choices, mapping


class SettingsPanel(BasePanel):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._header("系统设置", "产品信息 / 软件更新 / AI 大模型分析 / 账号安全")

        # 滚动由 BasePanel 统一提供(原独立画布与 bind_all 滚轮已移除,
        # 避免双重滚动);卡片依次 pack 到 self.body

        row = 0
        row = self._build_product(row)
        row = self._build_update(row)
        row = self._build_ai(row)
        row = self._build_account(row)
        row = self._build_schedule(row)
        self._build_tips(row)

    # ── 定时巡检(销号清单 #13b) ───────────────────────────────
    def _build_schedule(self, row: int) -> int:
        from tkinter import ttk

        outer, body = card(self.body, "定时巡检(Windows 计划任务)")
        self.var_sched = tk.StringVar(value="每周三 02:00")
        rb_frame = tk.Frame(body, bg=COLORS["card"])
        rb_frame.pack(fill="x")
        for label in ("每周三 02:00", "每月 1 日 02:00", "禁用(卸载)"):
            ttk.Radiobutton(rb_frame, text=label, value=label,
                            variable=self.var_sched).pack(side="left", padx=8)

        status_lbl = tk.Label(body, text="", bg=COLORS["card"],
                              fg=COLORS["muted"], font=FONTS["small"])
        status_lbl.pack(anchor="w", pady=(6, 0))

        def refresh_status():
            try:
                from patrol.desktop import service
                st = service.schedule_status()
                status_lbl.configure(
                    text="当前状态:已安装(" +
                         ("每周" if st.get("weekly") else "每月") + ")"
                    if st["installed"] else "当前状态:未安装")
            except Exception as e:  # noqa: BLE001
                status_lbl.configure(text=f"状态查询失败:{e}")

        def apply():
            from tkinter import messagebox

            from patrol.desktop import service
            choice = self.var_sched.get()
            try:
                if choice.startswith("禁用"):
                    service.remove_schedule()
                    self.app.set_status("已卸载定时巡检")
                else:
                    service.install_schedule(weekly=choice.startswith("每周"))
                    self.app.set_status(f"已安装定时巡检:{choice}")
                refresh_status()
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("定时巡检", str(e), parent=self)

        ttk.Button(body, text="应用", command=apply).pack(anchor="w",
                                                           pady=(6, 0))
        refresh_status()
        return row + 1

    # ── 产品信息 ────────────────────────────────────────────────
    def _build_product(self, row: int) -> int:
        outer, body = card(self.body, "产品信息")
        outer.pack(fill="x", pady=(0, 12))  # body 内统一 pack(页头也是 pack)
        info = (
            ("产品名称", f"{PRODUCT_NAME}({PRODUCT_NAME_EN})"),
            ("版本", f"v{__version__}"),
            ("作者", AUTHOR),
            ("QQ", AUTHOR_QQ),
            ("开源协议", f"{LICENSE_NAME} — 允许二次开发"),
        )
        for i, (k, v) in enumerate(info):
            # 标签列与 form_row 同宽同字体:各卡片字段上下成一条线
            tk.Label(body, text=k, bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONTS["ui"], width=LABEL_W, anchor="w").grid(
                row=i, column=0, sticky="w", pady=2)
            tk.Label(body, text=v, bg=COLORS["card"], fg=COLORS["text"],
                     font=FONTS["ui"], anchor="w").grid(
                row=i, column=1, sticky="w", pady=2)
        ttk.Button(body, text=f"查看 {LICENSE_NAME} 全文",
                   command=self._show_license).grid(
            row=len(info), column=1, sticky="w", pady=(8, 0))
        return row + 1

    def _show_license(self) -> None:
        from patrol.desktop.dialogs import TextViewerDialog

        TextViewerDialog(self, f"{LICENSE_NAME} 全文", LICENSE_TEXT).show()

    # ── 软件更新 ────────────────────────────────────────────────
    def _build_update(self, row: int) -> int:
        from patrol.update import load_update_url, save_update_url
        from patrol.updater import load_pending

        outer, body = card(self.body, "软件更新")
        outer.pack(fill="x", pady=(0, 12))  # body 内统一 pack(页头也是 pack)

        self.var_update_url = tk.StringVar(value=load_update_url())
        self.lbl_update_result = tk.Label(body, text="", bg=COLORS["card"],
                                          fg=COLORS["muted"], font=FONTS["small"],
                                          anchor="w", justify="left")
        e_url = ttk.Entry(body, textvariable=self.var_update_url, width=52)
        form_row(body, 0, "更新源地址", e_url, "更新清单 manifest 的 URL")

        btns = tk.Frame(body, bg=COLORS["card"])
        btns.grid(row=1, column=1, sticky="w", pady=(6, 0))

        def _save_url():
            save_update_url(self.var_update_url.get())
            self.app.set_status("更新源地址已保存")
            self.lbl_update_result.configure(text="更新源地址已保存",
                                             fg=COLORS["ok"])

        ttk.Button(btns, text="保存地址", command=_save_url).pack(side="left")
        ttk.Button(btns, text="检查更新", command=self._check_update).pack(
            side="left", padx=6)
        ttk.Button(btns, text="下载并安装", style="Accent.TButton",
                   command=self._download_update).pack(side="left", padx=6)
        ttk.Button(btns, text="重启并安装",
                   command=self._install_update).pack(side="left", padx=6)
        self.lbl_update_result.grid(row=2, column=1, sticky="ew", pady=(8, 0))

        pending = load_pending()
        hint = f"当前版本 v{__version__}"
        if not is_frozen():
            hint += " · 开发模式不支持自动安装(绿色版可用)"
        if pending:
            hint += f" · 已暂存更新包 v{pending.get('version', '')}"
        tk.Label(body, text=hint, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"], anchor="w").grid(
            row=3, column=1, sticky="w", pady=(4, 0))
        return row + 1

    def _set_update_result(self, result: dict, error: str = "") -> None:
        msg = error or str(result.get("message") or result.get("status") or "")
        checked = result.get("checked_at")
        if checked:
            msg = f"[{checked}] {msg}"
        self.lbl_update_result.configure(
            text=msg, fg=COLORS["fail"] if error else COLORS["ok"])

    def _check_update(self) -> None:
        def done(result):
            self._set_update_result(result)

        def fail(exc):
            self.lbl_update_result.configure(text=f"检查失败:{exc}",
                                             fg=COLORS["fail"])

        run_in_thread(self, service.check_update, on_done=done, on_error=fail)

    def _download_update(self) -> None:
        def done(result):
            self._set_update_result(result)
            self.app.set_status("更新包已下载并校验")

        def fail(exc):
            self._set_update_result({}, error=str(exc))

        run_in_thread(self, service.download_update, on_done=done, on_error=fail)

    def _install_update(self) -> None:
        if not is_frozen():
            messagebox.showinfo("提示", "开发模式不支持自动安装,绿色版可用", parent=self)
            return
        if not messagebox.askyesno("重启并安装",
                                   "程序将退出并自动完成更新(约 10~30 秒),继续?",
                                   parent=self):
            return

        def done(version):
            self._set_update_result({
                "status": "installing",
                "message": f"正在安装 v{version},程序即将退出并自动重启",
            })
            threading.Timer(3.0, os._exit, (0,)).start()

        def fail(exc):
            self._set_update_result({}, error=str(exc))

        run_in_thread(self, service.install_update, on_done=done, on_error=fail)

    # ── AI 大模型分析 ───────────────────────────────────────────
    def _build_ai(self, row: int) -> int:
        outer, body = card(self.body, "AI 大模型分析(报告决策与摘要)")
        outer.pack(fill="x", pady=(0, 12))  # body 内统一 pack(页头也是 pack)

        raw = service.ai_load_raw()
        choices, mapping = _preset_choices()
        self._preset_mapping = mapping

        self.var_ai_enabled = tk.BooleanVar(value=bool(raw.get("enabled")))
        self.var_preset = tk.StringVar()
        self.var_base_url = tk.StringVar(value=str(raw.get("base_url") or ""))
        self.var_model = tk.StringVar(value=str(raw.get("model") or ""))
        self.var_api_key = tk.StringVar()
        self.lbl_ai_result = tk.Label(body, text="", bg=COLORS["card"],
                                      fg=COLORS["muted"], font=FONTS["small"],
                                      anchor="w", justify="left")

        tk.Checkbutton(body, text="启用 AI 分析(巡检完成后自动分析,报告中展示决策与摘要)",
                       variable=self.var_ai_enabled, bg=COLORS["card"],
                       activebackground=COLORS["card"], anchor="w").grid(
            row=0, column=1, sticky="w", pady=(0, 4))

        cb_preset = ttk.Combobox(body, textvariable=self.var_preset,
                                 values=choices, state="readonly", width=38)
        form_row(body, 1, "厂商预设", cb_preset, "13 家国内/海外/本地厂商")
        cb_preset.bind("<<ComboboxSelected>>", self._on_preset)

        e_base = ttk.Entry(body, textvariable=self.var_base_url, width=52)
        form_row(body, 2, "接口地址", e_base, "OpenAI 兼容 base_url")

        self.cb_model = ttk.Combobox(body, textvariable=self.var_model, width=38)
        form_row(body, 3, "模型名", self.cb_model, "可手填")

        e_key = ttk.Entry(body, textvariable=self.var_api_key, show="●", width=38)
        masked = service.ai_masked_key()
        form_row(body, 4, "API Key", e_key,
                 f"留空保持原值{f'(当前 {masked})' if masked else ''}")

        btns = tk.Frame(body, bg=COLORS["card"])
        btns.grid(row=5, column=1, sticky="w", pady=(6, 0))
        ttk.Button(btns, text="保存配置", style="Accent.TButton",
                   command=self._save_ai).pack(side="left")
        ttk.Button(btns, text="测试连通", command=self._test_ai).pack(side="left", padx=6)
        self.btn_key_url = ttk.Button(btns, text="申请 API Key",
                                      command=self._open_key_url)
        self.btn_key_url.pack(side="left", padx=6)
        self.lbl_ai_result.grid(row=6, column=1, sticky="ew", pady=(8, 0))

        if any(os.environ.get(k) for k in
               ("PATROL_AI_API_KEY", "PATROL_AI_BASE_URL", "PATROL_AI_MODEL")):
            tk.Label(body, text="提示:检测到 PATROL_AI_* 环境变量,运行时优先生效",
                     bg=COLORS["card"], fg=COLORS["warn"],
                     font=FONTS["small"], anchor="w").grid(
                row=7, column=1, sticky="w", pady=(4, 0))

        matched = match_preset(str(raw.get("base_url") or ""))
        if matched:
            for label, p in mapping.items():
                if p["id"] == matched:
                    self.var_preset.set(label)
                    self._fill_models(p)
        return row + 1

    def _on_preset(self, _event=None) -> None:
        preset = self._preset_mapping.get(self.var_preset.get())
        if not preset:
            return
        if preset["base_url"]:
            self.var_base_url.set(preset["base_url"])
        self._fill_models(preset)

    def _fill_models(self, preset: dict) -> None:
        models = preset.get("models") or []
        self.cb_model.configure(values=models)
        if models and not self.var_model.get():
            self.var_model.set(models[0])

    def _open_key_url(self) -> None:
        preset = self._preset_mapping.get(self.var_preset.get()) or {}
        url = preset.get("key_url") or ""
        if not url:
            messagebox.showinfo("提示", "该预设无需申请密钥(Ollama 本地)", parent=self)
            return
        service.open_path(url)

    def _save_ai(self) -> None:
        try:
            service.ai_save(
                self.var_ai_enabled.get(), self.var_base_url.get(),
                self.var_api_key.get(), self.var_model.get(),
            )
        except ValueError as e:
            self.lbl_ai_result.configure(text=str(e), fg=COLORS["fail"])
            return
        self.var_api_key.set("")
        self.lbl_ai_result.configure(text="AI 配置已保存,下次巡检/手动分析即生效",
                                     fg=COLORS["ok"])
        self.app.set_status("AI 配置已保存")

    def _test_ai(self) -> None:
        def done(result):
            self.lbl_ai_result.configure(
                text=result["message"],
                fg=COLORS["ok"] if result["ok"] else COLORS["fail"])

        def fail(exc):
            self.lbl_ai_result.configure(text=f"测试失败:{exc}",
                                         fg=COLORS["fail"])

        run_in_thread(
            self,
            lambda: service.ai_test(self.var_base_url.get(),
                                    self.var_api_key.get(),
                                    self.var_model.get()),
            on_done=done, on_error=fail)

    # ── 账号安全(网页访问模式) ─────────────────────────────────
    def _build_account(self, row: int) -> int:
        outer, body = card(self.body, "账号安全(网页远程访问模式)")
        outer.pack(fill="x", pady=(0, 12))  # body 内统一 pack(页头也是 pack)

        status = service.auth_status()
        if status.get("mode") == "off":
            state_text = "已关闭(运行参数/配置停用了登录)"
        elif status.get("mode") == "env":
            state_text = f"由环境变量管理(PATROL_WEB_USER={status.get('username')})"
        else:
            state_text = f"已启用,当前账号:{status.get('username')}"
        tk.Label(body, text=f"网页登录:{state_text}", bg=COLORS["card"],
                 fg=COLORS["text"], font=FONTS["ui"], anchor="w").grid(
            row=0, column=1, sticky="w", pady=(0, 4))
        tk.Label(body, text="本地小工具无需登录;此账号用于 `启动巡检助手.exe --web` 远程访问",
                 bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"], anchor="w").grid(
            row=1, column=1, sticky="w", pady=(0, 6))

        self.var_cur_pass = tk.StringVar()
        self.var_new_user = tk.StringVar()
        self.var_new_pass = tk.StringVar()
        self.var_new_pass2 = tk.StringVar()
        self.lbl_account_result = tk.Label(body, text="", bg=COLORS["card"],
                                           fg=COLORS["muted"], font=FONTS["small"],
                                           anchor="w", justify="left")

        rows = [
            ("当前密码", ttk.Entry(body, textvariable=self.var_cur_pass, show="●", width=28), "必填"),
            ("新用户名", ttk.Entry(body, textvariable=self.var_new_user, width=28), "留空不改"),
            ("新密码", ttk.Entry(body, textvariable=self.var_new_pass, show="●", width=28), "留空不改"),
            ("确认新密码", ttk.Entry(body, textvariable=self.var_new_pass2, show="●", width=28), ""),
        ]
        for i, (label, widget, note) in enumerate(rows):
            form_row(body, i + 2, label, widget, note)

        ttk.Button(body, text="修改账号", style="Accent.TButton",
                   command=self._change_account).grid(
            row=len(rows) + 2, column=1, sticky="w", pady=(6, 0))
        self.lbl_account_result.grid(row=len(rows) + 3, column=1,
                                     sticky="ew", pady=(8, 0))
        return row + 1

    def _change_account(self) -> None:
        if self.var_new_pass.get() != self.var_new_pass2.get():
            self.lbl_account_result.configure(text="两次输入的新密码不一致",
                                              fg=COLORS["fail"])
            return
        try:
            msg = service.change_account(
                self.var_cur_pass.get(),
                self.var_new_user.get() or None,
                self.var_new_pass.get() or None,
            )
        except ValueError as e:
            self.lbl_account_result.configure(text=str(e), fg=COLORS["fail"])
            return
        for var in (self.var_cur_pass, self.var_new_user,
                    self.var_new_pass, self.var_new_pass2):
            var.set("")
        self.lbl_account_result.configure(text=msg, fg=COLORS["ok"])
        self.app.set_status("网页登录账号已修改")

    # ── 使用提示 ────────────────────────────────────────────────
    def _build_tips(self, row: int) -> None:
        outer, body = card(self.body, "使用提示")
        outer.pack(fill="x", pady=(0, 12))  # body 内统一 pack(页头也是 pack)
        tips = (
            "1. 本工具为本地桌面小程序,双击即用,全程不需要浏览器。",
            "2. 配置文件 config\\devices.yaml,报告目录 output\\,可直接编辑/拷贝。",
            "3. 如需在其他电脑/手机浏览器远程访问:运行 启动巡检助手.exe --web(带登录认证)。",
            "4. 命令行批量巡检:启动巡检助手.exe run -c config\\devices.yaml。",
        )
        for i, tip in enumerate(tips):
            tk.Label(body, text=tip, bg=COLORS["card"], fg=COLORS["text"],
                     font=FONTS["ui"], anchor="w", justify="left").grid(
                row=i, column=0, sticky="w", pady=2)

    def refresh(self) -> None:
        self.app.set_status("系统设置")
