"""桌面小工具共用控件与主题(网工专业配色:海军蓝 chrome + 浅内容区 + 科技蓝主色)"""
from __future__ import annotations

import base64
import struct
import threading
import zlib

import tkinter as tk
from tkinter import ttk

COLORS = {
    "bg": "#F5F7FA",         # 商务浅灰(内容区底色,低饱和)
    "card": "#FFFFFF",       # 卡片
    "border": "#DCE3EB",     # 浅灰描边
    "text": "#22303F",       # 深石板灰正文
    "muted": "#66788C",      # 钢灰次要文字
    "title": "#123F72",      # 海军蓝标题(浅底文字色)
    "accent": "#1B5FA8",     # 商务蓝(主色,与 chrome/菜单同族)
    "accent_hover": "#2E74BD",
    "header": "#17508C",     # 顶栏/侧栏/状态栏统一中蓝(界面色彩一致)
    "header_edge": "#0E3A66",    # 顶栏底缘压边(立体分层)
    "sidebar": "#17508C",    # 与顶栏同色
    "sidebar_edge": "#0E3A66",   # 侧栏右缘压边
    "sidebar_hover": "#1F63B0",  # 侧栏悬停(比底色亮一档的中蓝,菜单质感)
    "statusbar_edge": "#2E6BB0",  # 状态栏上缘亮边
    "card_shadow": "#D5DEE9",    # 卡片右下柔投影
    "statusbar": "#17508C",  # 与顶栏同色
    "nav_text": "#D8E6F5",   # 侧栏未选中文字(亮钢青)
    "nav_muted": "#A9C4E0",  # 侧栏署名
    "nav_hover_bg": "#E8F1FF",  # 侧栏悬停淡蓝(不再整块深蓝)
    "ok": "#18A058",         # 运行绿
    "fail": "#E5484D",       # 告警红
    "warn": "#F59E0B",       # 警示橙
    "error_bg": "#FDECEC",
}

# 概览四张统计卡的数字色(商务低饱和:蓝/青/绿/琥珀)
STAT_COLORS = ["#1B5FA8", "#0E7490", "#15803D", "#B45309"]

FONTS = {
    "ui": ("Microsoft YaHei UI", 10),
    "ui_bold": ("Microsoft YaHei UI", 10, "bold"),
    "nav": ("Microsoft YaHei UI", 12),          # 侧栏菜单(与页面视觉匹配,不显小)
    "nav_bold": ("Microsoft YaHei UI", 12, "bold"),
    "h1": ("Microsoft YaHei UI", 14, "bold"),
    "h2": ("Microsoft YaHei UI", 11, "bold"),
    "num": ("Microsoft YaHei UI", 18, "bold"),
    "small": ("Microsoft YaHei UI", 9),
}

STATUS_TAGS = {  # 状态文字 → 颜色键(含报告 severity 英文枚举与中文级别)
    "通过": "ok", "完成": "ok", "启用": "ok", "PASS": "ok", "info": "ok",
    "提示": "ok",
    "失败": "fail", "异常": "fail", "停用": "fail", "FAIL": "fail",
    "error": "fail", "critical": "fail", "严重": "fail",
    "未知": "warn", "巡检中": "warn", "排队中": "warn", "警告": "warn",
    "UNKNOWN": "warn", "warning": "warn",
}

# 报告 severity 英文枚举 → 界面中文级别(数据层保持英文,仅展示层翻译)
SEVERITY_LABELS = {"critical": "严重", "warning": "警告", "info": "提示"}


def severity_cn(value: str) -> str:
    """severity 枚举转中文显示(未知值原样返回)。"""
    return SEVERITY_LABELS.get(str(value), str(value))

# ── 按钮 3D 面(纯 stdlib 生成 PNG:纵向渐变 + 斜面高光/阴影) ────────
_BTN_W, _BTN_H = 18, 26
_BUTTON_IMAGES: list = []  # 持引用防止 PhotoImage 被 GC 回收后按钮掉底

# 元素名 → (渐变上色, 渐变下色, 高光边, 阴影边)
# 内容区按钮统一为同一配色(2026-09-23 用户两轮反馈"颜色不一致"定案):
# 常规/主操作/删除按钮同面同字色,仅以文字与位置区分;立体感由 1px 斜面/按下凹陷承担
_BTN_FACE = ((245, 249, 252), (236, 242, 248), (255, 255, 255), (152, 166, 184))
_BTN_SCHEMES = {name: _BTN_FACE for name in
                ("Btn.face", "BtnAccent.face", "BtnDanger.face")}

# 表单标签列统一字符宽:各卡片/对话框字段起始位置一致
LABEL_W = 12


def _png_rgb(width: int, height: int, pixel_fn) -> bytes:
    """极小 PNG 编码器(RGB8,纯 stdlib):给按钮面生成纹理用。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # 每行 filter=None
        for x in range(width):
            raw.extend(pixel_fn(x, y))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def _face_png(top, bottom, light, dark, pressed: bool = False,
              marker: tuple | None = None,
              w: int = _BTN_W, h: int = _BTN_H) -> bytes:
    """按钮面:纵向渐变填充,1px 左上高光/右下阴影;按下/选中时斜面反向(凹陷感)。

    marker=(宽, 色) 在左侧画竖条——导航选中态标识(不再用背景色块)。
    """

    def px(x: int, y: int):
        if marker is not None and x < marker[0]:
            return marker[1]
        edge_light, edge_dark = (dark, light) if pressed else (light, dark)
        on_dark_edge = x == w - 1 or y == h - 1
        if (x == 0 or y == 0) and not on_dark_edge:
            return edge_light
        if on_dark_edge:
            return edge_dark
        t = y / (h - 1)
        return tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))

    return _png_rgb(w, h, px)


def _shift(color, step: int) -> tuple:
    return tuple(max(0, min(255, c + step)) for c in color)


def apply_theme(root: tk.Tk) -> None:
    """统一 ttk 主题(基于 clam 便于着色)。"""
    root.configure(bg=COLORS["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # pragma: no cover - 无 clam 时退回默认
        pass

    style.configure(".", font=FONTS["ui"], background=COLORS["bg"],
                    foreground=COLORS["text"])
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["card"])
    style.configure("H1.TLabel", font=FONTS["h1"], foreground=COLORS["title"])
    style.configure("H2.TLabel", font=FONTS["h2"], foreground=COLORS["title"])
    style.configure("Muted.TLabel", font=FONTS["small"], foreground=COLORS["muted"])
    style.configure("CardMuted.TLabel", font=FONTS["small"],
                    background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Num.TLabel", font=FONTS["num"], foreground=COLORS["title"],
                    background=COLORS["card"])
    style.configure("Error.TLabel", font=FONTS["small"],
                    foreground=COLORS["fail"], background=COLORS["error_bg"])

    # 三种按钮样式名并存(代码各处已引用),视觉完全同色同字色
    for _bs in ("TButton", "Accent.TButton", "Danger.TButton"):
        style.configure(_bs, padding=(14, 5), background="#E3EAF2",
                        foreground=COLORS["title"])
        style.map(_bs,
                  background=[("active", "#D3DEEA"), ("!disabled", "#E3EAF2")])

    # 按钮 3D:自绘均色/斜面图片元素(常态/悬停/按下/禁用),border=(1,1) 与 1px 斜面精确对位拉伸
    def _btn_element(name: str, scheme) -> None:
        top, bottom, light, dark = scheme
        pngs = [
            _face_png(top, bottom, light, dark),                              # 常态
            _face_png(_shift(top, 12), _shift(bottom, 12), light, dark),      # 悬停
            _face_png(_shift(top, -20), _shift(bottom, -20), light, dark,
                      pressed=True),                                          # 按下
            _face_png((238, 241, 245), (228, 233, 238),
                      (250, 251, 252), (198, 207, 217)),                      # 禁用
        ]
        photos = [tk.PhotoImage(data=base64.b64encode(p), format="png", master=root)
                  for p in pngs]
        _BUTTON_IMAGES.extend(photos)
        try:
            style.element_create(
                name, "image", photos[0],
                ("pressed", photos[2]), ("active", photos[1]),
                ("disabled", photos[3]), border=(1, 1))
        except tk.TclError:
            pass  # 同一解释器重复构建时不重复注册

    for _el_name, _scheme in _BTN_SCHEMES.items():
        _btn_element(_el_name, _scheme)

    def _face_layout(el_name: str):
        return [(el_name, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})]

    style.layout("TButton", _face_layout("Btn.face"))
    style.layout("Accent.TButton", _face_layout("BtnAccent.face"))
    style.layout("Danger.TButton", _face_layout("BtnDanger.face"))

    # 导航按钮 3D:各状态同一面色(2026-09-23 用户反馈"背景颜色不一致/选中不同步"定案):
    # 常态/悬停/选中/按下全部同色同渐变,底色永不失步;选中只以凹陷斜面 + 左侧主色条 + 白粗体区分
    nav_face = (44, 106, 175)
    nav_light, nav_dark = (150, 195, 235), (10, 45, 85)
    nav_flat = _face_png(nav_face, nav_face, nav_light, nav_dark, w=20, h=30)
    nav_pngs = [
        nav_flat,                                                              # 常态(凸)
        nav_flat,                                                              # 悬停(同色,白字提示)
        _face_png(nav_face, nav_face, nav_light, nav_dark,
                  pressed=True, marker=(3, (27, 95, 168)), w=20, h=30),         # 选中(凹+主色条)
        _face_png(nav_face, nav_face, nav_light, nav_dark,
                  pressed=True, w=20, h=30),                                   # 按下(凹)
        _face_png((238, 241, 245), (228, 233, 238),
                  (250, 251, 252), (198, 207, 217), w=20, h=30),               # 禁用
    ]
    nav_photos = [tk.PhotoImage(data=base64.b64encode(p), format="png", master=root)
                  for p in nav_pngs]
    _BUTTON_IMAGES.extend(nav_photos)
    try:
        style.element_create(
            "BtnNav.face", "image", nav_photos[0],
            ("pressed", nav_photos[3]), ("selected", nav_photos[2]),
            ("active", nav_photos[1]), ("disabled", nav_photos[4]),
            border=(1, 1))
    except tk.TclError:
        pass
    style.layout("Nav.TButton", [("BtnNav.face", {"sticky": "nswe", "children": [
        ("Button.padding", {"sticky": "nswe", "children": [
            ("Button.label", {"sticky": "w"})]})]})])
    style.configure("Nav.TButton", padding=(22, 13), font=FONTS["nav"],
                    foreground=COLORS["nav_text"])
    style.map("Nav.TButton",
              font=[("selected", FONTS["nav_bold"])],
              foreground=[("selected", "#FFFFFF"), ("active", "#FFFFFF"),
                          ("pressed", "#FFFFFF"), ("!disabled", COLORS["nav_text"])])

    style.configure("Treeview", rowheight=28, background=COLORS["card"],
                    fieldbackground=COLORS["card"], borderwidth=0)
    style.configure("Treeview.Heading", font=FONTS["ui_bold"],
                    background=COLORS["header"], foreground="#FFFFFF", relief="flat")
    style.map("Treeview.Heading", background=[("active", COLORS["accent"])])
    style.map("Treeview",
              background=[("selected", "#E7F0FF")],
              foreground=[("selected", COLORS["text"])])

    style.configure("TEntry", padding=5, fieldbackground=COLORS["card"])
    style.configure("TCombobox", padding=5)
    style.configure("TCheckbutton", background=COLORS["bg"])
    style.configure("Card.TCheckbutton", background=COLORS["card"])
    style.configure("Vertical.TScrollbar", arrowsize=12)


# ── 表格勾选列(批量删除多选用) ────────────────────────────────
CHECK_COL = "chk"
CHECK_ON = "☑"
CHECK_OFF = "☐"


def make_tree(
    parent: tk.Misc,
    columns: list[tuple[str, str, int]],
    height: int = 10,
    checkbox: bool = False,
) -> tuple[ttk.Treeview, tk.Frame]:
    """建带纵向滚动条的 Treeview。columns: (列id, 标题, 宽度px)。

    checkbox=True 时首列加勾选框(点击切换,表头"全选"整列切换),
    供批量删除多选;点勾选框只改勾选,不改变行选中状态。
    """
    cols = ([ (CHECK_COL, "", 34) ] if checkbox else []) + list(columns)
    wrap = tk.Frame(parent, bg=COLORS["card"])
    tree = ttk.Treeview(
        wrap, columns=[c[0] for c in cols], show="headings",
        height=height, selectmode="extended",
    )
    for col_id, title, width in cols:
        if col_id == CHECK_COL:
            tree.heading(col_id, text="全选", anchor="center",
                         command=lambda t=tree: toggle_all_checks(t))
            tree.column(col_id, width=width, minwidth=width,
                        anchor="center", stretch=False)
            continue
        # 表头与单元格同为左对齐:字段与内容成一条线,阅读不乱
        tree.heading(col_id, text=title, anchor="w")
        tree.column(col_id, width=width, minwidth=40, anchor="w")
    vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    if checkbox:
        # add="+":先于面板自绑的双击处理器触发,返回 "break" 拦掉双击编辑
        tree.bind("<Button-1>",
                  lambda e, t=tree: _check_click(t, e), add="+")
        tree.bind("<Double-1>",
                  lambda e, t=tree: _check_click(t, e), add="+")
    return tree, wrap


def _check_click(tree: ttk.Treeview, event):
    """点勾选列切换勾选并拦截后续绑定;点其他列放行。"""
    if tree.identify_region(event.x, event.y) == "heading":
        return None  # 表头"全选/取消"走 heading command
    if tree.identify_column(event.x) != "#1" or CHECK_COL not in tree["columns"]:
        return None
    iid = tree.identify_row(event.y)
    if iid:
        toggle_check(tree, iid)
    return "break"


def check_has(tree: ttk.Treeview) -> bool:
    return CHECK_COL in tree["columns"]


def insert_row(tree: ttk.Treeview, values, iid: str | None = None, **kwargs):
    """插入一行;有勾选列时自动带未勾选标记,并保持列序。"""
    vals = ([CHECK_OFF] + list(values)) if check_has(tree) else list(values)
    if iid is not None:
        return tree.insert("", "end", iid=iid, values=vals, **kwargs)
    return tree.insert("", "end", values=vals, **kwargs)


def set_check(tree: ttk.Treeview, iid: str, on: bool = True) -> None:
    if check_has(tree) and tree.exists(iid):
        tree.set(iid, CHECK_COL, CHECK_ON if on else CHECK_OFF)


def toggle_check(tree: ttk.Treeview, iid: str) -> None:
    if check_has(tree) and tree.exists(iid):
        set_check(tree, iid, tree.set(iid, CHECK_COL) != CHECK_ON)


def toggle_all_checks(tree: ttk.Treeview) -> None:
    """表头全选/取消:已任一勾选则全部取消,否则全部勾选。"""
    on = not checked_rows(tree)
    for iid in tree.get_children():
        set_check(tree, iid, on)


def checked_rows(tree: ttk.Treeview) -> list[str]:
    """当前勾选的行 iid(无勾选列或均未勾选时为空)。"""
    if not check_has(tree):
        return []
    return [iid for iid in tree.get_children()
            if str(tree.set(iid, CHECK_COL)) == CHECK_ON]


def target_rows(tree: ttk.Treeview) -> list[str]:
    """批量操作目标行:有勾选优先勾选行,否则退回当前选中行。"""
    return checked_rows(tree) or list(tree.selection())


def keep_checks(tree: ttk.Treeview, iids) -> None:
    """刷新重插后按 iid 恢复勾选(行已消失则忽略)。"""
    for iid in iids:
        set_check(tree, iid, True)


def clear_tree(tree: ttk.Treeview) -> None:
    tree.delete(*tree.get_children())


def colorize_rows(tree: ttk.Treeview, col_id: str = "status") -> None:
    """按状态列文字给行着色(STATUS_TAGS)。"""
    if col_id not in tree["columns"]:
        return
    for tag, color in (("ok", COLORS["ok"]), ("fail", COLORS["fail"]),
                       ("warn", COLORS["warn"])):
        tree.tag_configure(tag, foreground=color)
    for iid in tree.get_children():
        text = str(tree.set(iid, col_id) or "")
        key = STATUS_TAGS.get(text)
        if key:
            tree.item(iid, tags=(key,))


def card(parent: tk.Misc, title: str = "", **pack_kwargs) -> tuple[tk.Frame, tk.Frame]:
    """白色卡片容器(右下柔投影 + 标题左侧色条),返回 (外框, 内容区)。pack_kwargs 作用于外框 pack()。"""
    outer = tk.Frame(parent, bg=COLORS["card_shadow"])
    inner = tk.Frame(outer, bg=COLORS["card"])
    inner.pack(fill="both", expand=True, padx=(1, 3), pady=(1, 3))
    if title:
        head = tk.Frame(inner, bg=COLORS["card"])
        head.pack(fill="x", padx=14, pady=(12, 4))
        tk.Frame(head, bg=COLORS["accent"], width=4).pack(
            side="left", fill="y", padx=(0, 8))
        tk.Label(head, text=title, font=FONTS["h2"], bg=COLORS["card"],
                 fg=COLORS["title"], anchor="w").pack(side="left")
    body = tk.Frame(inner, bg=COLORS["card"])
    body.pack(fill="both", expand=True, padx=14, pady=(2, 12))
    if pack_kwargs:
        outer.pack(**pack_kwargs)
    return outer, body


def form_row(parent: tk.Misc, row: int, label: str, widget: tk.Misc,
             note: str = "") -> None:
    """表单一行:标签 + 控件(+ 可选说明),grid 布局。

    标签列定宽(LABEL_W)、控件列同起同止、说明列固定间距——各行字段严格成列。
    """
    tk.Label(parent, text=label, bg=COLORS["card"], fg=COLORS["text"],
             font=FONTS["ui"], anchor="w", width=LABEL_W).grid(
        row=row, column=0, sticky="w", padx=(0, 10), pady=4)
    widget.grid(row=row, column=1, sticky="ew", pady=4)
    if note:
        tk.Label(parent, text=note, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"], anchor="w").grid(
            row=row, column=2, sticky="w", padx=(12, 0), pady=4)
    parent.columnconfigure(1, weight=1)


def run_in_thread(widget: tk.Misc, work, on_done=None, on_error=None) -> None:
    """后台线程执行 work(),结果回 UI 线程;期间鼠标转圈。

    网络类操作(AI 分析/软件更新)必须走这里,避免卡界面。
    """

    def _post(fn, *args):
        try:
            widget.after(0, lambda: fn(*args))
        except (tk.TclError, RuntimeError, AttributeError):
            pass  # 窗口已销毁,丢弃回调

    def _runner():
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - 汇报给界面
            def _fail():
                widget.configure(cursor="")
                if on_error:
                    on_error(exc)
            _post(_fail)
            return

        def _ok():
            widget.configure(cursor="")
            if on_done:
                on_done(result)
        _post(_ok)

    widget.configure(cursor="watch")
    threading.Thread(target=_runner, daemon=True).start()
