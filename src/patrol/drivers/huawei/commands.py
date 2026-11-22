"""华为 VRP 交换机命令定义

所有命令均为只读命令。
命令格式基于华为 VRP 公开文档，实际回显需设备验证。
"""
from patrol.drivers.base import CheckCommand


def get_vrp_switch_commands() -> list[CheckCommand]:
    """返回华为 VRP 交换机的检查命令列表。"""
    return [
        CheckCommand(
            name="device_info",
            category="基本信息",
            command="display version",
            description="设备型号、版本、运行时间、序列号",
        ),
        CheckCommand(
            name="cpu_usage",
            category="CPU",
            command="display cpu-usage",
            description="CPU 利用率",
        ),
        CheckCommand(
            name="memory_usage",
            category="内存",
            command="display memory-usage",
            description="内存利用率",
        ),
        CheckCommand(
            name="interface_status",
            category="接口状态",
            command="display interface brief",
            description="接口 Up/Down 状态、错误包、丢包",
        ),
        CheckCommand(
            name="fan_status",
            category="风扇",
            command="display fan",
            description="风扇状态",
        ),
        CheckCommand(
            name="power_status",
            category="电源",
            command="display power",
            description="电源状态",
        ),
        CheckCommand(
            name="logbuffer",
            category="日志",
            command="display logbuffer",
            description="最近严重日志",
        ),
        CheckCommand(
            name="routing_table",
            category="路由",
            command="display ip routing-table",
            description="路由表条目数",
        ),
        CheckCommand(
            name="config_cur",
            category="运行配置",
            command="display current-configuration",
            description="Telnet/SNMP/VTY/STP 配置检查",
        ),
        CheckCommand(
            name="temperature",
            category="硬件环境",
            command="display temperature",
            description="设备温度传感器(标准格式,待真机验证)",
        ),
        CheckCommand(
            name="transceiver",
            category="硬件环境",
            command="display transceiver diagnosis",
            description="光模块 DDM 收发光功率对照门限",
        ),
        CheckCommand(
            name="ospf_neighbor",
            category="路由协议",
            command="display ospf peer",
            description="OSPF 邻居状态(应全 Full)",
        ),
        CheckCommand(
            name="arp_count",
            category="表项规模",
            command="display arp all",
            description="ARP 表项总数",
        ),
        CheckCommand(
            name="storage",
            category="资源",
            command="dir",
            description="Flash 存储使用率",
        ),
        CheckCommand(
            name="config_diff",
            category="运行配置",
            command="compare configuration",
            description="running 与 startup 配置一致性(未保存=高危)",
        ),
        CheckCommand(
            name="reboot_reason",
            category="日志告警",
            command="display reboot-info",
            description="上次重启原因(部分机型不支持,待真机验证)",
        ),
        CheckCommand(
            name="ntp_status",
            category="安全基线",
            command="display ntp-service status",
            description="NTP 时钟同步状态(等保:时间同步)",
        ),
        CheckCommand(
            name="lldp_neighbor", category="网络拓扑",
            command="display lldp neighbor brief",
            description="LLDP 邻居(拓扑绘制,待真机验证)",
        ),
    ]
