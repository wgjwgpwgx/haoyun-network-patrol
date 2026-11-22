"""迪普 DPtech 防火墙命令/页面定义

迪普防火墙使用传统多页面 HTML 管理界面。
采集方式：requests + BeautifulSoup 解析 HTML。
"""
from patrol.drivers.base import CheckCommand


def get_fw_firewall_commands() -> list[CheckCommand]:
    """迪普 DPtech 防火墙页面路径。"""
    return [
        CheckCommand("device_info", "基本信息", "/system/system_info.html", "系统信息"),
        CheckCommand("cpu_usage", "CPU", "/monitor/cpu_stat.html", "CPU 监控"),
        CheckCommand("memory_usage", "内存", "/monitor/mem_stat.html", "内存监控"),
        CheckCommand("interface_status", "接口状态", "/monitor/interface_stat.html", "接口状态"),
    ]
