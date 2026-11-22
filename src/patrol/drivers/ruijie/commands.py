"""锐捷 RGOS 交换机命令定义

所有命令均为只读命令。
锐捷使用 show 而非 display。
"""
from patrol.drivers.base import CheckCommand


def get_rgos_switch_commands() -> list[CheckCommand]:
    return [
        CheckCommand("device_info", "基本信息", "show version", "设备型号、版本、序列号"),
        CheckCommand("cpu_usage", "CPU", "show cpu", "CPU 利用率"),
        CheckCommand("memory_usage", "内存", "show memory", "内存利用率"),
        CheckCommand("interface_status", "接口状态", "show ip interface brief", "三层接口状态"),
        CheckCommand("routing_table", "路由", "show ip route", "路由表条目数"),
        CheckCommand("logbuffer", "日志", "show logging reverse", "最近日志"),
        CheckCommand("config_cur", "运行配置", "show running-config", "配置分析"),
        CheckCommand("lldp_neighbor", "网络拓扑", "show lldp neighbors", "LLDP 邻居(拓扑绘制)"),
    ]
