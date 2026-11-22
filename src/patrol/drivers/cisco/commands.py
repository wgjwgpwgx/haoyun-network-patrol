"""Cisco IOS 检查命令定义

所有命令均为只读(show 类)。命令格式基于 Cisco IOS 15.x 公开文档与
常见输出编写,实际回显格式待真机验证(见 docs/acceptance/)。
"""
from patrol.drivers.base import CheckCommand


def get_ios_commands() -> list[CheckCommand]:
    """返回 Cisco IOS 设备的检查命令列表。"""
    return [
        CheckCommand(
            name="device_info",
            category="基本信息",
            command="show version",
            description="设备型号、IOS 版本、运行时间、序列号",
        ),
        CheckCommand(
            name="cpu_usage",
            category="CPU",
            command="show processes cpu",
            description="CPU 利用率(5 秒/1 分钟/5 分钟)",
        ),
        CheckCommand(
            name="memory_usage",
            category="内存",
            command="show memory statistics",
            description="处理器内存利用率",
        ),
        CheckCommand(
            name="interface_status",
            category="接口状态",
            command="show ip interface brief",
            description="接口协议/线路状态",
        ),
        CheckCommand(
            name="fan_status",
            category="风扇",
            command="show env all",
            description="风扇状态",
        ),
        CheckCommand(
            name="power_status",
            category="电源",
            command="show env all",
            description="电源模块状态",
        ),
        CheckCommand(
            name="logbuffer",
            category="日志",
            command="show logging",
            description="日志中严重级别(severity<=3)条目",
        ),
        CheckCommand(
            name="config_cur",
            category="运行配置",
            command="show running-config",
            description="Telnet/SNMP/VTY/STP 配置检查",
        ),
        CheckCommand(
            name="lldp_neighbor", category="网络拓扑",
            command="show lldp neighbors",
            description="LLDP 邻居(拓扑绘制,待真机验证)",
        ),
    ]
