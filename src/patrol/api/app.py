"""FastAPI 应用 - 网络设备巡检助手 Web API

接口概览：
  设备管理：GET/POST /devices, PUT/DELETE /devices/{name}
  巡检任务：POST /tasks, GET /tasks/{id}
  报告：GET /tasks/{id}/report, GET /reports/{filename}
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from patrol.api.schemas import (
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    TaskCreate,
    TaskOut,
)
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from patrol.api.ui import router as ui_router, init_ui

app = FastAPI(title="昊云网络巡检助手 API", version="0.1.0")

# 静态资源(logo 等)
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Web 登录认证(问题 001:默认开启,凭据在 config/auth.yaml,默认 admin/admin123;
# PATROL_WEB_PASSWORD 环境变量可覆盖;改密/改用户名在「系统设置 → 账号安全」)
from patrol.api.auth import setup_auth
setup_auth(app)

# 全局存储实例(P0-2:SQLite 仓库;首次启动自动从旧 YAML 迁移)
from patrol.storage.sqlstore import SqlAudit, bootstrap

_device_store, _customer_store, _task_store, _audit = bootstrap()
_task_manager = TaskManager(_device_store, _task_store)


def _who(request) -> str:
    """审计操作者:认证用户名或 local。"""
    try:
        from patrol.api.auth import auth_username
        return auth_username() or "local"
    except Exception:  # noqa: BLE001
        return "local"


# 注册 Web 管理界面路由
init_ui(_device_store, _task_store, _customer_store)
app.include_router(ui_router)

# 系统设置(产品信息/协议/API Key/软件更新),独立模块不影响既有路由
from patrol.api.settings_ui import router as settings_router
app.include_router(settings_router)


@app.get("/", include_in_schema=False)
def root():
    """根路径重定向到管理界面。"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui")


def _mask_password(raw: dict) -> DeviceOut:
    """将设备配置转为响应模型（隐藏密码、Super 密码和 token）。"""
    return DeviceOut(
        name=raw.get("name", ""),
        customer=raw.get("customer", ""),
        host=raw.get("host", ""),
        vendor=raw.get("vendor", "h3c"),
        device_type=raw.get("device_type", "comware_switch"),
        login_method=raw.get("login_method", "ssh"),
        port=raw.get("port", 22),
        web_port=raw.get("web_port", 443),
        web_protocol=raw.get("web_protocol", "https"),
        username=raw.get("username", ""),
        enabled=raw.get("enabled", True),
        timeout=raw.get("timeout", 30),
        command_timeout=raw.get("command_timeout", 60),
    )


# ── 设备管理 ────────────────────────────────────────────────────


@app.get("/devices", response_model=list[DeviceOut], tags=["设备管理"])
def list_devices():
    """查询所有设备列表（不返回密码）。"""
    return [_mask_password(d) for d in _device_store.list()]


@app.post("/devices", response_model=DeviceOut, status_code=201, tags=["设备管理"])
def create_device(body: DeviceCreate, request=None):
    """新增设备。"""
    try:
        created = _device_store.create(body.model_dump())
        _audit.log("device.create", target=body.name,
                   operator=_who(request))
        return _mask_password(created)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.put("/devices/{name}", response_model=DeviceOut, tags=["设备管理"])
def update_device(name: str, body: DeviceUpdate, request=None):
    """修改设备。"""
    try:
        updated = _device_store.update(name, body.model_dump(exclude_unset=True))
        _audit.log("device.update", target=name, operator=_who(request))
        return _mask_password(updated)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.delete("/devices/{name}", status_code=204, tags=["设备管理"])
def delete_device(name: str, request=None):
    """删除设备。"""
    try:
        _device_store.delete(name)
        _audit.log("device.delete", target=name, operator=_who(request))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 客户管理 ────────────────────────────────────────────────────


@app.get("/customers", response_model=list[CustomerOut], tags=["客户管理"])
def list_customers():
    """查询所有客户(甲方公司)。"""
    return [CustomerOut(**c) for c in _customer_store.list()]


@app.post("/customers", response_model=CustomerOut, status_code=201, tags=["客户管理"])
def create_customer(body: CustomerCreate):
    """新增客户。"""
    try:
        created = _customer_store.create(body.model_dump())
        _audit.log("customer.create", target=body.name)
        return CustomerOut(**created)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.put("/customers/{name}", response_model=CustomerOut, tags=["客户管理"])
def update_customer(name: str, body: CustomerUpdate):
    """修改客户（name 可用于重命名；引用该客户的设备不会自动跟随）。"""
    try:
        updated = _customer_store.update(name, body.model_dump(exclude_unset=True))
        _audit.log("customer.update", target=name)
        return CustomerOut(**updated)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.delete("/customers/{name}", status_code=204, tags=["客户管理"])
def delete_customer(name: str):
    """删除客户（设备上的归属引用不会被清除，显示为"未指定"）。"""
    try:
        _customer_store.delete(name)
        _audit.log("customer.delete", target=name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 巡检任务 ────────────────────────────────────────────────────


@app.post("/tasks", response_model=TaskOut, status_code=201, tags=["巡检任务"])
def create_task(body: TaskCreate):
    """手工创建巡检任务（异步执行，不阻塞请求）。"""
    try:
        task = _task_manager.create_task(body.device_name)
        _audit.log("task.create", target=body.device_name,
                   detail=f"task_id={task.task_id}")
        return task
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/audit", tags=["系统"])
def list_audit(limit: int = 100):
    """操作审计(最近 N 条:设备/客户/任务/迁移操作)。"""
    return _audit.recent(min(limit, 500))


@app.get("/tasks/{task_id}", response_model=TaskOut, tags=["巡检任务"])
def get_task(task_id: str):
    """查询巡检任务状态。"""
    task = _task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return TaskOut(**task)


# ── 报告 ────────────────────────────────────────────────────────


@app.get("/tasks/{task_id}/report", response_class=HTMLResponse, tags=["报告"])
def get_task_report(task_id: str):
    """查看巡检任务的 HTML 报告。"""
    task = _task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"任务未完成，当前状态: {task['status']}",
        )
    report_file = task.get("report_file")
    if not report_file:
        raise HTTPException(status_code=404, detail="报告文件不存在")
    report_path = Path("output") / report_file
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")
    content = report_path.read_text(encoding="utf-8")
    return HTMLResponse(content=content)


@app.get("/reports/{filename}", response_class=HTMLResponse, tags=["报告"])
def download_report(filename: str):
    """下载 HTML 报告文件。"""
    # 安全检查：防止路径遍历
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    report_path = Path("output") / filename
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")
    content = report_path.read_text(encoding="utf-8")
    return HTMLResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
