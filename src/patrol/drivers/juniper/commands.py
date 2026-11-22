"""Juniper Junos 检查命令定义

所有命令均为只读(show 类)。命令格式基于 Junos 公开文档与常见版本
(17/20/21.x)输出编写,实际回显格式待真机验证(见 docs/acceptance/)。
"""
from patrol.drivers.base import CheckCommand


def get_junos_commands() -> list[CheckCommand]:
    """返回 Juniper Junos 设备的检查命令列表。"""
    return [
        CheckCommand(
            name="device_info",
            category="基本信息",
            command="show version",
            description="设备型号、Junos 版本、主机名",
        ),
        CheckCommand(
            name="cpu_usage",
            category="CPU",
            command="show chassis routing-engine",
            description="主控板 CPU 利用率(100-Idle)",
        ),
        CheckCommand(
            name="memory_usage",
            category="内存",
            command="show chassis routing-engine",
            description="主控板内存利用率",
        ),
        CheckCommand(
            name="interface_status",
            category="接口状态",
            command="show interfaces terse",
            description="接口 Admin/Link 状态",
        ),
        CheckCommand(
            name="fan_status",
            category="风扇",
            command="show chassis environment",
            description="风扇框状态",
        ),
        CheckCommand(
            name="power_status",
            category="电源",
            command="show chassis environment",
            description="电源模块状态",
        ),
        CheckCommand(
            name="system_alarms",
            category="告警",
            command="show system alarms",
            description="系统当前活动告警",
        ),
        CheckCommand(
            name="config_cur",
            category="运行配置",
            command="show configuration system services",
            description="管理服务配置(Telnet/SSH)",
        ),
        CheckCommand(
            name="lldp_neighbor", category="网络拓扑",
            command="show lldp neighbors",
            description="LLDP 邻居(拓扑绘制,待真机验证)",
        ),
    ]
