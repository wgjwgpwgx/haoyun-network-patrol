"""Web 管理界面路由 - 服务端渲染

所有 /ui/* 路由返回 HTML 页面，不修改现有 /api 接口。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from patrol.api.store import CustomerStore, DeviceStore, TaskStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["管理界面"])

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)

# 全局存储引用（在 app.py 中注入）
_device_store: DeviceStore = None  # type: ignore
_task_store: TaskStore = None  # type: ignore
_customer_store: CustomerStore = None  # type: ignore


def init_ui(ds: DeviceStore, ts: TaskStore, cs: CustomerStore) -> None:
    """注入存储实例。"""
    global _device_store, _task_store, _customer_store
    _device_store = ds
    _task_store = ts
    _customer_store = cs


def _ctx(request: Request, **kwargs) -> dict:
    """构造模板上下文。"""
    from patrol.api.auth import auth_enabled
    return {"request": request, "auth_on": auth_enabled(), **kwargs}


# 厂商/设备类型显示名（顺序即下拉框顺序，值与 drivers 注册表一致）
_VENDOR_LABELS = {
    "h3c": "H3C (新华三)",
    "huawei": "华为",
    "ruijie": "锐捷",
    "sangfor": "深信服",
    "dptech": "迪普",
    "zte": "中兴",
    "maipu": "迈普",
}
_DEVICE_TYPE_LABELS = {
    "comware_switch": "Comware 交换机",
    "s7506e": "S7506E 核心交换机",
    "secpath_firewall": "SecPath 防火墙",
    "vrp_switch": "VRP 交换机",
    "usg_firewall": "USG 防火墙",
    "rgos_switch": "RGOS 交换机",
    "ngaf_firewall": "NGAF 下一代防火墙",
    "fw_firewall": "FW 防火墙",
    "zxr10_switch": "ZXR10 交换机",
    "mypower_switch": "MyPower 交换机",
}


def _vendor_options() -> list[dict]:
    """从 Driver 注册表生成厂商/设备类型选项。

    返回结构: [{"value": "h3c", "label": "H3C (新华三)",
                "device_types": [{"value": "s7506e", "label": "S7506E 核心交换机"}, ...]}, ...]
    """
    # 确保全部驱动已注册(drivers/__init__.py 统一导入)
    import patrol.drivers  # noqa: F401
    from patrol.drivers.registry import list_drivers

    registered: dict[str, set[str]] = {}
    for key in list_drivers():
        vendor, device_type = key.split("/", 1)
        registered.setdefault(vendor, set()).add(device_type)

    options = []
    for vendor, label in _VENDOR_LABELS.items():
        if vendor not in registered:
            continue
        options.append({
            "value": vendor,
            "label": label,
            "device_types": [
                {"value": dt, "label": _DEVICE_TYPE_LABELS.get(dt, dt)}
                for dt in sorted(registered[vendor])
            ],
        })
    return options


# ── 仪表盘 ──────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request):
    """风险汇总首页。"""
    devices = _device_store.list()
    all_tasks = _task_store.list_all()

    recent_tasks = sorted(all_tasks, key=lambda t: t.get("created_at", ""), reverse=True)[:10]

    stats = {
        "device_count": len(devices),
        "customer_count": len(_customer_store.list()),
        "pass_total": 0,
        "fail_total": 0,
        "unknown_total": 0,
    }

    return templates.TemplateResponse("ui/index.html", _ctx(
        request, active="dashboard", stats=stats,
        fail_items=[], recent_tasks=recent_tasks,
    ))


# ── 设备管理 ────────────────────────────────────────────────────


@router.get("/devices", response_class=HTMLResponse)
def device_list(
    request: Request,
    q: str = "",
    vendor: str = "",
    customer: str = "",
    enabled: str = "",
    page: int = 1,
):
    """设备列表（支持筛选、分页）。"""
    devices = _device_store.list()

    # 筛选
    if q:
        q_lower = q.lower()
        devices = [d for d in devices
                   if q_lower in d.get("name", "").lower()
                   or q_lower in d.get("host", "").lower()]
    if vendor:
        devices = [d for d in devices if d.get("vendor") == vendor]
    if customer:
        devices = [d for d in devices if d.get("customer", "") == customer]
    if enabled:
        want = enabled == "true"
        devices = [d for d in devices if d.get("enabled") == want]

    # 分页
    per_page = 20
    total = len(devices)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    devices_page = devices[start:start + per_page]

    return templates.TemplateResponse("ui/devices.html", _ctx(
        request, active="devices",
        devices_page=devices_page, q=q, vendor=vendor, customer=customer,
        enabled=enabled, page=page, total_pages=total_pages,
        vendor_options=_vendor_options(),
        customers=_customer_store.list(),
    ))


@router.post("/devices/batch-delete")
def device_batch_delete(names: list[str] = Form(default=[])):
    """批量删除设备。"""
    for name in names:
        try:
            _device_store.delete(name)
        except KeyError:
            pass
    return RedirectResponse("/ui/devices", status_code=303)


@router.get("/devices/new", response_class=HTMLResponse)
def device_new_form(request: Request, error: str = ""):
    """新增设备表单。"""
    return templates.TemplateResponse("ui/device_form.html", _ctx(
        request, active="devices", device=None,
        vendor_options=_vendor_options(), error=error,
        customers=_customer_store.list(),
    ))


@router.post("/devices/new")
def device_create(
    name: str = Form(...),
    customer: str = Form(""),
    host: str = Form(...),
    vendor: str = Form("h3c"),
    device_type: str = Form("comware_switch"),
    login_method: str = Form("ssh"),
    port: int = Form(22),
    web_port: int = Form(443),
    username: str = Form(...),
    password: str = Form(...),
    super_password: str = Form(""),
    timeout: int = Form(30),
    command_timeout: int = Form(120),
    enabled: str = Form("true"),
    skip_tls_verify: str = Form(""),
):
    """创建设备。"""
    from urllib.parse import quote

    try:
        from patrol.models import validate_host
        validate_host(host)
        if customer and _customer_store.get(customer) is None:
            raise ValueError(f"归属客户不存在: {customer},请先在客户管理中添加")
        _device_store.create({
            "name": name, "customer": customer, "host": host, "vendor": vendor,
            "device_type": device_type, "login_method": login_method,
            "port": port, "web_port": web_port,
            "username": username, "password": password,
            "super_password": super_password,
            "timeout": timeout, "command_timeout": command_timeout,
            "verify_ssl": skip_tls_verify != "true",
            "enabled": enabled == "true",
        })
    except ValueError as e:
        return RedirectResponse(
            f"/ui/devices/new?error={quote(str(e))}", status_code=303
        )
    return RedirectResponse("/ui/devices", status_code=303)


@router.get("/devices/{name}/edit", response_class=HTMLResponse)
def device_edit_form(request: Request, name: str, error: str = ""):
    """编辑设备表单。"""
    device = _device_store.get(name)
    if not device:
        return RedirectResponse("/ui/devices", status_code=303)
    return templates.TemplateResponse("ui/device_form.html", _ctx(
        request, active="devices", device=device,
        vendor_options=_vendor_options(), error=error,
        customers=_customer_store.list(),
    ))


@router.post("/devices/{name}/edit")
def device_update(
    name: str,
    customer: str = Form(""),
    host: str = Form(...),
    vendor: str = Form("h3c"),
    device_type: str = Form("comware_switch"),
    login_method: str = Form("ssh"),
    port: int = Form(22),
    web_port: int = Form(443),
    username: str = Form(...),
    password: str = Form(""),
    super_password: str = Form(""),
    timeout: int = Form(30),
    command_timeout: int = Form(120),
    enabled: str = Form("true"),
    skip_tls_verify: str = Form(""),
):
    """更新设备。"""
    from urllib.parse import quote

    updates = {
        "customer": customer, "host": host, "vendor": vendor,
        "device_type": device_type,
        "login_method": login_method,
        "port": port, "web_port": web_port, "username": username,
        "timeout": timeout, "command_timeout": command_timeout,
        "verify_ssl": skip_tls_verify != "true",
        "enabled": enabled == "true",
    }
    if password:
        updates["password"] = password
    if super_password:
        updates["super_password"] = super_password
    try:
        from patrol.models import validate_host
        validate_host(host)
        if customer and _customer_store.get(customer) is None:
            raise ValueError(f"归属客户不存在: {customer}")
        _device_store.update(name, updates)
    except (KeyError, ValueError) as e:
        return RedirectResponse(
            f"/ui/devices/{quote(name)}/edit?error={quote(str(e))}",
            status_code=303,
        )
    return RedirectResponse("/ui/devices", status_code=303)


@router.post("/devices/{name}/delete")
def device_delete(name: str):
    """删除设备。"""
    try:
        _device_store.delete(name)
    except KeyError:
        pass
    return RedirectResponse("/ui/devices", status_code=303)


@router.post("/devices/{name}/toggle")
def device_toggle(name: str):
    """启用/停用设备。"""
    device = _device_store.get(name)
    if device:
        try:
            _device_store.update(name, {"enabled": not device.get("enabled", True)})
        except (KeyError, ValueError):
            pass
    return RedirectResponse("/ui/devices", status_code=303)


# ── 客户管理 ────────────────────────────────────────────────────


@router.get("/customers", response_class=HTMLResponse)
def customer_list(request: Request, edit: str = "", error: str = ""):
    """客户列表与新增/编辑表单(?edit=名称 时表单回填该客户)。"""
    customers = _customer_store.list()
    editing = _customer_store.get(edit) if edit else None

    # 统计各客户名下设备数
    device_counts: dict[str, int] = {}
    for d in _device_store.list():
        cname = d.get("customer", "")
        if cname:
            device_counts[cname] = device_counts.get(cname, 0) + 1

    return templates.TemplateResponse("ui/customers.html", _ctx(
        request, active="customers",
        customers=customers, editing=editing, error=error,
        device_counts=device_counts,
    ))


@router.post("/customers/save")
def customer_save(
    name: str = Form(...),
    orig_name: str = Form(""),
    contact: str = Form(""),
    phone: str = Form(""),
    remark: str = Form(""),
):
    """新增或修改客户(orig_name 非空为修改)。"""
    from urllib.parse import quote

    data = {"name": name, "contact": contact, "phone": phone, "remark": remark}
    try:
        if orig_name:
            updated = _customer_store.update(orig_name, data)
            # 客户重命名时同步更新设备上的归属引用
            if updated["name"] != orig_name:
                for d in _device_store.list():
                    if d.get("customer") == orig_name:
                        _device_store.update(d["name"], {"customer": updated["name"]})
        else:
            _customer_store.create(data)
    except (KeyError, ValueError) as e:
        return RedirectResponse(
            f"/ui/customers?error={quote(str(e))}", status_code=303
        )
    return RedirectResponse("/ui/customers", status_code=303)


@router.post("/customers/{name}/delete")
def customer_delete(name: str):
    """删除客户(设备上的归属引用保留,显示为未指定)。"""
    try:
        _customer_store.delete(name)
    except KeyError:
        pass
    return RedirectResponse("/ui/customers", status_code=303)


# ── 子网扫描发现(P1 第一批 ①) ──────────────────────────────


@router.post("/devices/scan")
def device_scan(cidr: str = Form(...), community: str = Form("public")):
    """子网扫描:ICMP+SNMP 并发发现存活设备并识别厂商。"""
    from patrol.netscan import scan_subnet

    try:
        results = scan_subnet(cidr.strip(), community.strip())
        return {"ok": True, "total": len(results), "devices": results,
                "error": ""}
    except ValueError as e:
        return {"ok": False, "total": 0, "devices": [], "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "total": 0, "devices": [],
                "error": f"扫描失败: {e}"}


@router.post("/devices/scan-import")
async def device_scan_import(request: Request,
                             devices_json: str = Form(...),
                             customer: str = Form(""),
                             username: str = Form(""),
                             password: str = Form("")):
    """扫描结果一键建档(勾选设备+填统一账号密码)。"""
    import json as json_mod

    try:
        devices = json_mod.loads(devices_json)
    except json_mod.JSONDecodeError:
        return {"ok": False, "imported": 0, "error": "数据无效"}

    imported = 0
    errors: list[str] = []
    for d in devices:
        name = d.get("sysname") or d.get("host", "").replace(".", "-")
        try:
            _device_store.create({
                "name": name, "customer": customer,
                "host": d["host"],
                "vendor": d.get("vendor") or "h3c",
                "device_type": d.get("device_type") or "comware_switch",
                "login_method": "snmp" if not username else "ssh",
                "port": 161 if not username else 22,
                "username": username or "snmp",
                "password": password or community_fallback(),
                "enabled": True,
            })
            imported += 1
        except ValueError as e:
            errors.append(f"{name}: {e}")

    return {"ok": True, "imported": imported,
            "errors": errors[:5], "error": ""}


def community_fallback() -> str:
    return "public"


# ── 巡检前连通性预检(P1 第一批 ②) ──────────────────────────────


@router.post("/tasks/precheck")
def task_precheck(device_names: str = Form(...)):
    """巡检前连通性预检:逐台 TCP 探测,报告可达/不可达。"""
    import socket as socket_mod

    names = [n.strip() for n in device_names.split(",") if n.strip()]
    results: list[dict] = []
    for name in names:
        dev = _device_store.get(name)
        if not dev:
            results.append({"name": name, "host": "", "port": 0,
                            "reachable": False, "reason": "设备不存在"})
            continue
        host = dev.get("host", "")
        method = dev.get("login_method", "ssh")
        port = dev.get("port", 22 if method == "ssh" else
                       23 if method == "telnet" else
                       161 if method == "snmp" else 443)
        try:
            with socket_mod.create_connection((host, port), timeout=3):
                results.append({"name": name, "host": host, "port": port,
                                "reachable": True, "reason": ""})
        except (socket_mod.timeout, OSError) as e:
            reason = "超时" if "timed out" in str(e) else str(e)[:50]
            results.append({"name": name, "host": host, "port": port,
                            "reachable": False, "reason": reason})

    reachable = sum(1 for r in results if r["reachable"])
    return {"ok": True, "total": len(results), "reachable": reachable,
            "unreachable": len(results) - reachable, "results": results}


# ── 设备自动识别(U-2:只填 IP+账号密码) ──────────────────────


@router.post("/devices/detect")
def device_detect(
    host: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    login_method: str = Form("ssh"),
    port: int = Form(0),
):
    """登录设备执行 version 命令自动识别厂商/型号(SSH 失败降级 Telnet)。"""
    from patrol.autodetect import probe_device
    from patrol.models import validate_host

    try:
        validate_host(host)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        return probe_device(host, username, password,
                            login_method=login_method,
                            port=port or None, timeout=15)
    except Exception as e:  # noqa: BLE001 - 前端友好提示
        return {"ok": False, "error": str(e)}


# ── 设备台账批量导入(智能识别) ─────────────────────────────────

# 导入支持的目标字段(表单字段名 map_{field})
_IMPORT_FIELDS = [
    "host", "username", "password", "super_password", "name",
    "login_method", "vendor", "device_type", "port", "customer", "remark",
]
_IMPORT_REQUIRED = ["host", "username", "password"]
_IMPORT_LABELS = {
    "host": "登录地址 *", "username": "用户名 *", "password": "一级密码 *",
    "super_password": "Super 密码", "name": "设备名称", "login_method": "登录方式",
    "vendor": "厂商", "device_type": "设备类型", "port": "端口",
    "customer": "归属单位", "remark": "备注",
}


def _import_tmp_dir() -> Path:
    d = Path("output") / ".import_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/devices/import", response_class=HTMLResponse)
def device_import_page(request: Request, error: str = ""):
    """批量导入:上传台账文件(支持 xlsx/csv/docx,自动识别字段)。"""
    return templates.TemplateResponse("ui/import.html", _ctx(
        request, active="devices", stage="upload", error=error,
        customers=_customer_store.list(),
    ))


@router.post("/devices/import")
async def device_import_upload(request: Request, file: UploadFile = File(...)):
    """上传 → 智能识别 → 预览确认。"""
    import uuid as uuid_mod

    from patrol.importer import preview_file

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".csv", ".docx"):
        return templates.TemplateResponse("ui/import.html", _ctx(
            request, active="devices", stage="upload",
            error=f"不支持的文件类型: {suffix or '(未知)'},支持 xlsx / csv / docx",
            customers=_customer_store.list(),
        ))

    # 单机工具:清掉上一次的临时文件再落盘
    tmp_dir = _import_tmp_dir()
    for old in tmp_dir.iterdir():
        try:
            old.unlink()
        except OSError:
            pass
    token = uuid_mod.uuid4().hex
    tmp_path = tmp_dir / f"{token}{suffix}"
    tmp_path.write_bytes(await file.read())

    try:
        pv = preview_file(tmp_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        return templates.TemplateResponse("ui/import.html", _ctx(
            request, active="devices", stage="upload", error=str(e),
            customers=_customer_store.list(),
        ))

    return templates.TemplateResponse("ui/import.html", _ctx(
        request, active="devices", stage="preview",
        pv=pv, token=token,
        fields=_IMPORT_FIELDS, labels=_IMPORT_LABELS,
        required=_IMPORT_REQUIRED,
        customers=_customer_store.list(),
    ))


@router.post("/devices/import/commit", response_class=HTMLResponse)
def device_import_commit(
    request: Request,
    token: str = Form(...),
    default_customer: str = Form(""),
    map_host: str = Form(""),
    map_username: str = Form(""),
    map_password: str = Form(""),
    map_super_password: str = Form(""),
    map_name: str = Form(""),
    map_login_method: str = Form(""),
    map_vendor: str = Form(""),
    map_device_type: str = Form(""),
    map_port: str = Form(""),
    map_customer: str = Form(""),
    map_remark: str = Form(""),
):
    """按确认后的映射批量建档,展示结果。"""
    from patrol.importer import import_rows, read_table

    # token 校验:仅允许本目录下的十六进制令牌(防路径拼接)
    if not token.isalnum() or len(token) != 32:
        return RedirectResponse("/ui/devices/import", status_code=303)
    tmp_files = list(_import_tmp_dir().glob(f"{token}.*"))
    if not tmp_files:
        return templates.TemplateResponse("ui/import.html", _ctx(
            request, active="devices", stage="upload",
            error="导入会话已过期,请重新上传文件",
            customers=_customer_store.list(),
        ))

    table = read_table(tmp_files[0])
    form_maps = {f"map_{f}": locals()[f"map_{f}"] for f in _IMPORT_FIELDS}
    mapping = {}
    for field in _IMPORT_FIELDS:
        col = form_maps.get(f"map_{field}", "")
        if col.isdigit() and int(col) < len(table.headers):
            mapping[field] = int(col)

    result = import_rows(
        _device_store, _customer_store, table, mapping,
        default_customer=default_customer,
    )
    tmp_files[0].unlink(missing_ok=True)

    return templates.TemplateResponse("ui/import.html", _ctx(
        request, active="devices", stage="done", result=result,
        customers=_customer_store.list(),
    ))


# ── 巡检任务 ────────────────────────────────────────────────────


@router.get("/tasks", response_class=HTMLResponse)
def task_list(request: Request):
    """任务列表。"""
    tasks = sorted(_task_store.list_all(),
                   key=lambda t: t.get("created_at", ""), reverse=True)
    enabled_devices = [d for d in _device_store.list() if d.get("enabled")]
    return templates.TemplateResponse("ui/tasks.html", _ctx(
        request, active="tasks", tasks=tasks, enabled_devices=enabled_devices,
    ))


@router.post("/tasks")
def task_create(device_names: list[str] = Form(None)):
    """创建巡检任务:勾选的多台设备合并为一份整体报告。"""
    from patrol.api.app import _task_manager
    if device_names:
        try:
            _task_manager.create_batch_task(device_names)
        except KeyError as e:
            logger.warning("创建巡检任务失败: %s", e)
    return RedirectResponse("/ui/tasks", status_code=303)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: str):
    """任务详情（用于刷新）。"""
    task = _task_store.get(task_id)
    if not task:
        return RedirectResponse("/ui/tasks", status_code=303)
    tasks = [task]
    enabled_devices = [d for d in _device_store.list() if d.get("enabled")]
    return templates.TemplateResponse("ui/tasks.html", _ctx(
        request, active="tasks", tasks=tasks, enabled_devices=enabled_devices,
    ))


# ── 设备知识库(经验沉淀) ──────────────────────────────────────


@router.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request, customer: str = "", device: str = "",
                   snapshot: str = "", error: str = "", q: str = ""):
    """知识库浏览(支持全文搜索 q 参数)。"""
    from patrol import knowledge as kb

    # 全文搜索模式
    if q.strip():
        search_results = kb.search(q.strip())
        return templates.TemplateResponse("ui/knowledge.html", _ctx(
            request, active="knowledge", customer="", device="",
            snapshot=None, rows=[], error=error, q=q,
            search_results=search_results,
        ))

    rows: list = []
    snap = None
    if customer and device and snapshot:
        snap = kb.load_snapshot(customer, device, snapshot)
    elif customer and device:
        rows = kb.list_snapshots(customer, device)
    elif customer:
        rows = [{"name": n} for n in kb.list_devices(customer)]
    else:
        rows = [{"name": n} for n in kb.list_customers()]

    return templates.TemplateResponse("ui/knowledge.html", _ctx(
        request, active="knowledge", customer=customer, device=device,
        snapshot=snap, rows=rows, error=error, q=q,
        search_results=[],
    ))


@router.post("/knowledge/import")
async def knowledge_import(request: Request, customer: str = Form(...),
                           device: str = Form(""), text: str = Form(""),
                           file: UploadFile = File(None),
                           replace: str = Form("")):
    """导入历史资料(replace=on 时先删该设备旧快照再导入)。"""
    from urllib.parse import quote

    from patrol import knowledge as kb

    # 替换模式:先确定设备名,删除旧快照
    if replace:
        if file and file.filename:
            device = device or Path(file.filename).stem
        elif text.strip():
            device = device or "导入资料"
        if device:
            kb.delete_device(customer, device)

    try:
        if file and file.filename:
            suffix = Path(file.filename).suffix.lower()
            data = await file.read()
            if suffix == ".docx":
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".docx",
                                                 delete=False) as f:
                    f.write(data)
                kb.import_docx(Path(f.name), customer,
                               device=device or Path(file.filename).stem)
            else:
                kb.import_text(data.decode("utf-8", errors="replace"),
                               customer, device or Path(file.filename).stem)
        elif text.strip():
            kb.import_text(text, customer, device or "导入资料")
        else:
            raise ValueError("请粘贴文本或选择文件")
        return RedirectResponse(
            f"/ui/knowledge?customer={quote(customer)}", status_code=303)
    except Exception as e:  # noqa: BLE001 - 用户可见
        from urllib.parse import quote as q
        return RedirectResponse(
            f"/ui/knowledge?error={q(str(e))}", status_code=303)


@router.post("/knowledge/seed")
def knowledge_seed_route():
    from patrol import knowledge as kb
    n = kb.seed_builtin()
    return {"ok": True,
            "message": f"已载入/确认 {n} 台内置样例(重复执行不重复导入)"}


@router.post("/knowledge/import-reports")
def knowledge_import_reports():
    from patrol import knowledge as kb
    r = kb.import_all_reports()
    msg = f"导入 {r['imported']} 份报告" +         (f",跳过 {r['skipped']} 个非报告 JSON" if r["skipped"] else "")
    if r["errors"]:
        msg += f";失败 {len(r['errors'])} 项"
    return {"ok": True, "message": msg}


@router.post("/knowledge/copilot")
def knowledge_copilot(check_name: str = Form(...),
                      raw_output: str = Form(...),
                      vendor: str = Form(""), device_type: str = Form("")):
    """知识库回显 → AI 生成解析规则并试跑(确认走 /ui/copilot/confirm)。"""
    from patrol.parser_copilot import generate_with_ai

    result = generate_with_ai(check_name, raw_output)
    result["vendor"] = vendor
    result["device_type"] = device_type
    result["check_name"] = check_name
    return result


# 模拟设备实例表(进程内;端口 → server)
_SIMULATORS: dict[int, "object"] = {}


@router.post("/knowledge/simulate")
def knowledge_simulate(customer: str = Form(...), device: str = Form(...)):
    """用知识库设备快照起本地 Telnet 模拟设备(演示/培训/自测)。"""
    from patrol.simulator_core import (
        SimDeviceServer, responses_from_knowledge,
    )

    responses = responses_from_knowledge(customer, device)
    if not responses:
        return {"ok": False, "error": f"「{customer}/{device}」无知识库快照或无回显"}
    # 复用已运行的同类模拟器(同客户设备重复点击)
    for port, srv in _SIMULATORS.items():
        if srv.get("key") == f"{customer}/{device}":
            return {"ok": True, "port": port, "reused": True}
    server = SimDeviceServer(port=0, responses=responses)
    port = server.start()
    _SIMULATORS[port] = {"server": server, "key": f"{customer}/{device}"}
    _audit_log_sim(customer, device, port)
    return {"ok": True, "port": port, "reused": False}


def _audit_log_sim(customer, device, port):
    try:
        from patrol.api.app import _audit
        _audit.log("simulator.start", target=f"{customer}/{device}",
                   detail=f"127.0.0.1:{port}")
    except Exception:  # noqa: BLE001 - 审计失败不影响
        pass


@router.post("/knowledge/export")
def knowledge_export():
    """一键交接:导出知识库+规则+样式为 zip。"""
    from pathlib import Path as P
    from patrol import knowledge as kb
    from fastapi.responses import FileResponse

    path = kb.export_all()
    return FileResponse(
        str(path), filename=path.name,
        media_type="application/zip")


@router.post("/knowledge/import-zip")
async def knowledge_import_zip(file: UploadFile = File(...)):
    """导入交接包(zip)。"""
    from pathlib import Path as P
    from tempfile import NamedTemporaryFile
    from urllib.parse import quote

    from patrol import knowledge as kb

    suffix = P(file.filename).suffix.lower()
    if suffix != ".zip":
        return {"ok": False, "error": "仅支持 .zip 文件"}
    with NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(await file.read())
    try:
        counts = kb.import_all(P(f.name))
        msg = (f"导入完成:知识库 {counts['knowledge']} 条,"
               f"规则 {counts['rules']} 个,"
               f"解析器 {counts['copilot']} 个")
        return {"ok": True, "message": msg}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@router.post("/knowledge/delete-device")
def knowledge_delete_device(customer: str = Form(...),
                            device: str = Form(...)):
    """删除某设备的全部知识库快照。"""
    from urllib.parse import quote

    from patrol import knowledge as kb
    n = kb.delete_device(customer, device)
    return {"ok": True, "deleted": n,
            "message": f"已删除「{device}」全部 {n} 条快照"}


@router.post("/knowledge/delete-customer")
def knowledge_delete_customer(customer: str = Form(...)):
    """删除某客户的全部知识库数据(设备+快照)。"""
    from patrol import knowledge as kb
    n = kb.delete_customer(customer)
    return {"ok": True, "deleted": n,
            "message": f"已删除「{customer}」全部 {n} 条快照"}


@router.post("/knowledge/delete")
def knowledge_delete(customer: str, device: str, snapshot: str):
    from urllib.parse import quote

    from patrol import knowledge as kb
    kb.delete_snapshot(customer, device, snapshot)
    return RedirectResponse(
        f"/ui/knowledge?customer={quote(customer)}&device={quote(device)}",
        status_code=303)


# ── 多期对比报告(P1 第二批 ②) ────────────────────────────────


@router.get("/reports/compare", response_class=HTMLResponse)
def report_compare(request: Request, a: str = "", b: str = ""):
    """选两期报告 JSON,生成对比视图(健康分变化/新增与解决异常/配置变更)。"""
    import json as json_mod
    from patrol import knowledge as _kb  # noqa: F401

    # 报告列表(供下拉选择)
    all_reports = []
    out = Path("output")
    if out.exists():
        for f in sorted(out.glob("*.json"), reverse=True):
            if f.stem.startswith("patrol_") or f.stem.startswith("zz_"):
                continue  # 跳过非报告 JSON
            json_check = out / f.name
            try:
                d = json_mod.loads(json_check.read_text(encoding="utf-8"))
                if "devices" not in d:
                    continue
            except Exception:  # noqa: BLE001
                continue
            from datetime import datetime as _dt
            all_reports.append({
                "name": f.name,
                "modified": _dt.fromtimestamp(f.stat().st_mtime
                                              ).strftime("%Y-%m-%d %H:%M"),
            })

    comparison = None
    if a and b and a != b:
        try:
            data_a = json_mod.loads(
                (out / a).read_text(encoding="utf-8"))
            data_b = json_mod.loads(
                (out / b).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data_a = data_b = None

        if data_a and data_b:
            comparison = _build_comparison(data_a, data_b)

    return templates.TemplateResponse("ui/compare.html", _ctx(
        request, active="reports",
        all_reports=all_reports, a=a, b=b, comparison=comparison,
    ))


def _build_comparison(data_a: dict, data_b: dict) -> dict:
    """构建两期报告的对比数据。"""
    from patrol.models import CheckStatus  # noqa: F401

    def _fail_set(data):
        result = set()
        for d in data.get("devices", []):
            for it in d.get("check_items", []):
                if it.get("status") == "FAIL":
                    result.add((d.get("name", ""), it.get("name", "")))
        return result

    def _msg_map(data):
        result = {}
        for d in data.get("devices", []):
            for it in d.get("check_items", []):
                if it.get("status") == "FAIL":
                    result[(d.get("name", ""), it.get("name", ""))] =                         it.get("message", "")
        return result

    fails_a = _fail_set(data_a)
    fails_b = _fail_set(data_b)
    msgs_b = _msg_map(data_b)

    resolved = sorted(fails_a - fails_b)
    new_items = sorted(fails_b - fails_a)

    def _health(data):
        from patrol.scoring import score_report
        from patrol.models import DeviceAsset, DeviceReport, CheckItem, CheckStatus
        devices = []
        for d in data.get("devices", []):
            asset = DeviceAsset(name=d.get("name", ""), host=d.get("host", ""))
            dev = DeviceReport(asset=asset)
            for it in d.get("check_items", []):
                dev.check_items.append(CheckItem(
                    name=it.get("name", ""), category=it.get("category", ""),
                    command=it.get("command", ""), raw_output="",
                    status=CheckStatus(it.get("status", "UNKNOWN")),
                    message=it.get("message", "")))
            devices.append(dev)
        if not devices:
            return 0
        return score_report(__import__("patrol.models", fromlist=[
            "PatrolReport"]).PatrolReport(devices=devices)).get("overall") or 0

    pass_a = sum(d.get("pass_count", 0) for d in data_a.get("devices", []))
    fail_a = sum(d.get("fail_count", 0) for d in data_a.get("devices", []))
    unknown_a = sum(d.get("unknown_count", 0) for d in data_a.get("devices", []))
    pass_b = sum(d.get("pass_count", 0) for d in data_b.get("devices", []))
    fail_b = sum(d.get("fail_count", 0) for d in data_b.get("devices", []))
    unknown_b = sum(d.get("unknown_count", 0) for d in data_b.get("devices", []))

    return {
        "health_a": _health(data_a),
        "health_b": _health(data_b),
        "pass_a": pass_a, "fail_a": fail_a, "unknown_a": unknown_a,
        "pass_b": pass_b, "fail_b": fail_b, "unknown_b": unknown_b,
        "resolved_count": len(resolved),
        "new_count": len(new_items),
        "resolved": [{"device": d, "check": c} for d, c in resolved],
        "new_items": [{"device": d, "check": c,
                       "message": msgs_b.get((d, c), "")} for d, c in new_items],
        "config_changes": sum(
            1 for d in data_b.get("devices", [])
            for it in d.get("check_items", [])
            if it.get("name") == "config_diff" and
            it.get("details", {}).get("has_diff")),
    }


# ── 巡检确认单(P1 第二批 ③:A4 打印签字版) ────────────────────


@router.get("/reports/{filename}/confirmation", response_class=HTMLResponse)
def report_confirmation(request: Request, filename: str):
    """从报告 JSON 生成 A4 打印版巡检确认单。"""
    import json as json_mod

    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)
    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)

    data = json_mod.loads(json_path.read_text(encoding="utf-8"))
    devices = []
    pass_n = fail_n = unknown_n = 0
    for d in data.get("devices", []):
        # 汇总该设备状态
        p = d.get("pass_count", 0)
        f = d.get("fail_count", 0)
        u = d.get("unknown_count", 0)
        if f > 0:
            status = "FAIL"
            fail_n += 1
        elif u > 0 and p == 0:
            status = "UNKNOWN"
            unknown_n += 1
        else:
            status = "PASS"
            pass_n += 1

        # 异常摘要(取前 2 条 FAIL)
        fails = [it.get("message", "")[:40]
                 for it in d.get("check_items", [])
                 if it.get("status") == "FAIL"][:2]
        devices.append({
            "name": d.get("name", ""),
            "host": d.get("host", ""),
            "model": d.get("model", ""),
            "status": status,
            "fail_summary": "; ".join(fails) if fails else "",
        })

    customer = ""
    if devices and data.get("devices"):
        customer = data["devices"][0].get("customer", "")

    return templates.TemplateResponse("ui/confirmation.html", _ctx(
        request, active="reports",
        customer=customer,
        date=data.get("generated_at", "")[:10],
        report_no=data.get("generated_at", "").replace("-", "").replace(":",
                                                                        "").replace("T", "-")[:15],
        total=len(devices),
        pass_count=pass_n, fail_count=fail_n, unknown_count=unknown_n,
        devices=devices,
        exec_summary=data.get("exec_summary", ""),
    ))


# ── 解析器 Copilot(P2:UNKNOWN 项 AI 生成解析规则) ─────────────


@router.post("/reports/{filename}/copilot")
def copilot_generate(filename: str, device: str = Form(...),
                     check_name: str = Form(...)):
    """对报告中的 UNKNOWN 项:AI 生成声明式解析规则并当场试跑(不入库)。"""
    import json as json_mod

    from patrol.parser_copilot import generate_with_ai

    if ".." in filename or "/" in filename or "\\" in filename:
        return {"ok": False, "error": "非法文件名"}
    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return {"ok": False, "error": "报告数据文件不存在"}

    data = json_mod.loads(json_path.read_text(encoding="utf-8"))
    dev = next((d for d in data.get("devices", [])
                if d.get("name") == device), None)
    if not dev:
        return {"ok": False, "error": f"设备不存在: {device}"}
    item = next((i for i in dev.get("check_items", [])
                 if i.get("name") == check_name), None)
    if not item:
        return {"ok": False, "error": f"检查项不存在: {check_name}"}
    raw = item.get("raw_output") or ""
    if not raw.strip():
        return {"ok": False, "error": "该检查项无原始回显(可能是采集失败)"}

    result = generate_with_ai(check_name, raw)
    # 附带回显供确认页预览
    result["vendor"] = dev.get("vendor", "")
    result["device_type"] = dev.get("device_type", "")
    result["device"] = device
    result["check_name"] = check_name
    return result


@router.post("/copilot/confirm")
def copilot_confirm(vendor: str = Form(...), device_type: str = Form(...),
                    check_name: str = Form(...), fields_json: str = Form(...)):
    """人工确认后入库;下次巡检自动生效。"""
    import json as json_mod

    from patrol.parser_copilot import save_rule

    try:
        fields = json_mod.loads(fields_json)
        assert isinstance(fields, dict) and fields
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "规则 JSON 无效"}
    path = save_rule(vendor, device_type, check_name, fields)
    return {"ok": True, "error": "", "saved_to": str(path)}


# ── 报告管理 ────────────────────────────────────────────────────


@router.get("/reports", response_class=HTMLResponse)
def report_list(request: Request):
    """报告列表。"""
    import json as json_mod

    from patrol.ai import load_ai_config

    output_dir = Path("output")
    reports = []
    if output_dir.exists():
        for f in sorted(output_dir.glob("*.html"), reverse=True):
            size = f.stat().st_size
            modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            json_path = f.with_suffix(".json")
            has_ai = False
            if json_path.exists():
                try:
                    data = json_mod.loads(json_path.read_text(encoding="utf-8"))
                    has_ai = bool(data.get("ai_analysis"))
                except (ValueError, OSError):
                    pass
            reports.append({
                "name": f.name,
                "size": f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB",
                "modified": modified,
                "has_preview": json_path.exists(),
                "has_ai": has_ai,
            })
    return templates.TemplateResponse("ui/reports.html", _ctx(
        request, active="reports", reports=reports,
        ai_enabled=load_ai_config().ready,
    ))


def _delete_report_files(filename: str) -> None:
    """删除报告 HTML 及伴生 JSON(文件名不合法时静默跳过)。"""
    if ".." in filename or "/" in filename or "\\" in filename:
        return
    if not filename.endswith(".html"):
        return
    html_path = Path("output") / filename
    json_path = html_path.with_suffix(".json")
    for p in (html_path, json_path):
        if p.exists():
            p.unlink()


@router.post("/reports/batch-delete")
def report_batch_delete(filenames: list[str] = Form(default=[])):
    """批量删除报告。"""
    for filename in filenames:
        _delete_report_files(filename)
    return RedirectResponse("/ui/reports", status_code=303)


@router.post("/reports/{filename}/delete")
def report_delete(filename: str):
    """删除单个报告(连同伴生 JSON)。"""
    _delete_report_files(filename)
    return RedirectResponse("/ui/reports", status_code=303)


@router.post("/reports/{filename}/ai-analysis")
def report_ai_analysis(filename: str):
    """对已有报告执行/重新执行 AI 分析,并同步更新 HTML 与 JSON。"""
    import json as json_mod
    from urllib.parse import quote

    from patrol.ai import AINotConfigured, analyze_report, load_ai_config
    from patrol.reporter.html import HTMLReporter
    from patrol.reporter.rebuild import rebuild_report

    def _back(msg: str):
        return RedirectResponse(
            f"/ui/reports/{quote(filename)}/preview?ai_error={quote(msg)}",
            status_code=303,
        )

    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)

    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return _back("缺少报告数据文件,无法分析")

    try:
        data = json_mod.loads(json_path.read_text(encoding="utf-8"))
        report = rebuild_report(data)
        result = analyze_report(report, load_ai_config())
    except AINotConfigured:
        return _back("AI 分析未启用,请先在 config/ai.yaml 中配置")
    except Exception as e:  # noqa: BLE001 - 用户可见的失败提示
        logger.warning("AI 分析失败 %s: %s", filename, e)
        return _back(f"AI 分析失败: {e}")

    data["ai_analysis"] = result
    report.ai_analysis = result
    json_path.write_text(
        json_mod.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 用带 AI 结论的数据重新渲染 HTML 报告(同路径覆盖)
    html_path = Path("output") / filename
    if html_path.exists():
        HTMLReporter().generate(report, html_path)

    return RedirectResponse(
        f"/ui/reports/{quote(filename)}/preview", status_code=303
    )


@router.get("/reports/{filename}/preview", response_class=HTMLResponse)
def report_preview(request: Request, filename: str, ai_error: str = ""):
    """在线预览报告（读取 JSON 结构化数据）。"""
    import json as json_mod

    from patrol.ai import load_ai_config

    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)

    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)

    data = json_mod.loads(json_path.read_text(encoding="utf-8"))

    # 计算汇总
    total_pass = sum(d.get("pass_count", 0) for d in data.get("devices", []))
    total_fail = sum(d.get("fail_count", 0) for d in data.get("devices", []))
    total_unknown = sum(d.get("unknown_count", 0) for d in data.get("devices", []))

    # 收集风险项
    fail_items = []
    for dev in data.get("devices", []):
        for item in dev.get("check_items", []):
            if item.get("status") == "FAIL":
                fail_items.append({
                    "device_name": dev.get("name", ""),
                    "category": item.get("category", ""),
                    "message": item.get("message", ""),
                    "severity": item.get("details", {}).get("severity", "warning"),
                    "suggestion": item.get("details", {}).get("suggestion", ""),
                })

    return templates.TemplateResponse("ui/preview.html", _ctx(
        request, active="reports",
        filename=filename, data=data,
        total_pass=total_pass, total_fail=total_fail, total_unknown=total_unknown,
        fail_items=fail_items,
        ai_enabled=load_ai_config().ready, ai_error=ai_error,
    ))


@router.get("/reports/{filename}", response_class=HTMLResponse)
def report_view(request: Request, filename: str):
    """在线查看报告（iframe 嵌入）。"""
    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)
    report_path = Path("output") / filename
    if not report_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)
    return templates.TemplateResponse("ui/report_view.html", _ctx(
        request, active="reports", filename=filename,
    ))


@router.get("/reports/{filename}/download")
def report_download(filename: str):
    """下载报告。"""
    from fastapi.responses import FileResponse
    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)
    report_path = Path("output") / filename
    if not report_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)
    return FileResponse(
        str(report_path),
        filename=filename,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{filename}/download-word")
def report_download_word(filename: str, formal: int = 0):
    """从 JSON 数据生成 Word 报告并下载(formal=1 为正式汇报版,无原始回显)。"""
    import json as json_mod
    from fastapi.responses import FileResponse
    from patrol.reporter.rebuild import rebuild_report
    from patrol.reporter.word import (
        WordReporter, build_report_meta, generate_word_filename,
    )

    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)

    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)

    data = json_mod.loads(json_path.read_text(encoding="utf-8"))
    report = rebuild_report(data)

    # 生成 Word(默认工程明细版;formal=1 为正式汇报版)
    word_filename = generate_word_filename(report)
    if formal:
        word_filename = word_filename.replace("巡检报告_", "巡检报告(正式版)_", 1)
    word_path = Path("output") / word_filename
    WordReporter().generate(report, word_path,
                            meta=build_report_meta(report, formal=bool(formal)))
    from patrol.utils.archive import archive_report
    archive_report(word_path,
                   report.devices[0].asset.customer if report.devices else "")

    return FileResponse(
        str(word_path),
        filename=word_filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/reports/{filename}/download-excel")
def report_download_excel(filename: str):
    """从 JSON 数据生成 Excel 台账报告(模板三)并下载。"""
    import json as json_mod
    from fastapi.responses import FileResponse
    from patrol.reporter.excel import ExcelReporter, generate_excel_filename
    from patrol.reporter.rebuild import rebuild_report

    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)

    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)

    data = json_mod.loads(json_path.read_text(encoding="utf-8"))
    report = rebuild_report(data)

    excel_filename = generate_excel_filename(report)
    excel_path = Path("output") / excel_filename
    ExcelReporter().generate(report, excel_path)
    from patrol.utils.archive import archive_report
    archive_report(excel_path,
                   report.devices[0].asset.customer if report.devices else "")

    return FileResponse(
        str(excel_path),
        filename=excel_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/reports/{filename}/download-pdf")
def report_download_pdf(filename: str):
    """从 JSON 数据生成 PDF 报告并下载。"""
    import json as json_mod
    from fastapi.responses import FileResponse, JSONResponse
    from patrol.reporter.rebuild import rebuild_report

    if ".." in filename or "/" in filename or "\\" in filename:
        return RedirectResponse("/ui/reports", status_code=303)

    json_path = Path("output") / filename.replace(".html", ".json")
    if not json_path.exists():
        return RedirectResponse("/ui/reports", status_code=303)

    # 检查 PDF 能力
    try:
        from patrol.reporter.pdf import PDFReporter, generate_pdf_filename, check_pdf_capability
        caps = check_pdf_capability()
        if not any(caps.values()):
            return JSONResponse(
                status_code=500,
                content={"error": "PDF 转换不可用，需要安装 Microsoft Word 或 LibreOffice"},
            )
    except ImportError:
        return JSONResponse(
            status_code=500,
            content={"error": "PDF 模块未安装"},
        )

    data = json_mod.loads(json_path.read_text(encoding="utf-8"))
    report = rebuild_report(data)

    # 生成 PDF
    pdf_filename = generate_pdf_filename(report)
    pdf_path = Path("output") / pdf_filename
    try:
        PDFReporter().generate(report, pdf_path)
    except RuntimeError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    return FileResponse(
        str(pdf_path),
        filename=pdf_filename,
        media_type="application/pdf",
    )
