"""深信服 NGAF 命令/API 端点定义

支持两种采集方式：
  - api: REST API（v8.0.35+，需管理员开启 WebAPI 权限）
  - web: Playwright 页面抓取（Vue SPA）
"""
from patrol.drivers.base import CheckCommand


# ── API 端点（login_method=api）──────────────────────────────────

def get_ngaf_api_commands() -> list[CheckCommand]:
    """深信服 NGAF WebAPI 端点。"""
    return [
        CheckCommand("device_info", "基本信息", "/system/device-info", "设备信息"),
        CheckCommand("cpu_usage", "CPU", "/monitor/cpu", "CPU 利用率"),
        CheckCommand("memory_usage", "内存", "/monitor/memory", "内存利用率"),
        CheckCommand("interface_status", "接口状态", "/monitor/interface", "接口状态"),
        CheckCommand("routing_table", "路由", "/system/routes", "路由表"),
        CheckCommand("logbuffer", "日志", "/log/system?reverse=true", "系统日志"),
    ]


# ── Web 页面路径（login_method=web）─────────────────────────────

def get_ngaf_web_commands() -> list[CheckCommand]:
    """深信服 NGAF Web 页面路径（Vue SPA hash 路由）。"""
    return [
        CheckCommand("device_info", "基本信息", "/#/system/info", "设备版本硬件信息"),
        CheckCommand("cpu_usage", "CPU", "/#/monitor/cpu", "CPU 监控"),
        CheckCommand("memory_usage", "内存", "/#/monitor/memory", "内存监控"),
        CheckCommand("interface_status", "接口状态", "/#/monitor/interface", "接口监控"),
    ]
