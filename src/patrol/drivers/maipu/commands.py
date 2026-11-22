"""迈普 MyPower 交换机命令定义

所有命令均为只读命令。MyPower 使用 show 风格 CLI（类 IOS）。
"""
from patrol.drivers.base import CheckCommand


def get_mypower_switch_commands() -> list[CheckCommand]:
    return [
        CheckCommand("device_info", "基本信息", "show version", "设备型号、版本、序列号"),
        CheckCommand("cpu_usage", "CPU", "show processes cpu", "CPU 利用率"),
        CheckCommand("memory_usage", "内存", "show memory statistics", "内存利用率"),
        CheckCommand("interface_status", "接口状态", "show ip interface brief", "三层接口状态"),
        CheckCommand("routing_table", "路由", "show ip route", "路由表条目数"),
        CheckCommand("logbuffer", "日志", "show logging", "最近日志"),
        CheckCommand("config_cur", "运行配置", "show running-config", "配置分析"),
        CheckCommand("lldp_neighbor", "网络拓扑", "show lldp neighbors", "LLDP 邻居(拓扑绘制)"),
    ]
