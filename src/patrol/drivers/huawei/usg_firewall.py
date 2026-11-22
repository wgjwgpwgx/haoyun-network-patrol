"""华为 USG 防火墙 Driver(复用 VRP 交换机解析器)

设备信息:
  - 厂商:Huawei
  - 操作系统:VRP(USG2000/5000/6000 系列防火墙)
  - Netmiko device_type: huawei

命令与交换机基本一致,额外增加防火墙会话表检查。
解析器复用 patrol.drivers.huawei.parsers,会话表解析为本文件新增,
均待真机验证。
"""
from __future__ import annotations

from typing import Any

from patrol.drivers.base import CheckCommand, ParsedResult
from patrol.drivers.huawei import parsers as vrp_parsers
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.drivers.registry import register
from patrol.drivers.topology import parse_lldp as _lldp


def _parse_session_table(output: str) -> dict[str, Any]:
    """解析 display firewall session table summary

    标准格式(VRP 防火墙):
      Current sessions: 
        ...
      Slot 1 cpu 0:  12345 sessions
      or
      Total 12345 sessions
    """
    import re

    result: dict[str, Any] = {"session_count": None, "tcp": None, "udp": None}
    m = re.search(r"(?:Total|total)\s+(\d+)\s+sessions?", output)
    if m:
        result["session_count"] = int(m.group(1))
    for line in output.splitlines():
        m = re.search(r"(\d+)\s+sessions", line)
        if m and result["session_count"] is None:
            result["session_count"] = int(m.group(1))
    return result


@register
class HuaweiUSGFirewallDriver(HuaweiVRPSwitchDriver):
    """华为 USG 防火墙巡检 Driver"""

    @property
    def device_type(self) -> str:
        return "usg_firewall"

    def get_check_commands(self) -> list[CheckCommand]:
        return [
            CheckCommand(name="device_info", category="基本信息",
                         command="display version",
                         description="设备型号、版本、运行时间、序列号"),
            CheckCommand(name="cpu_usage", category="CPU",
                         command="display cpu-usage", description="CPU 利用率"),
            CheckCommand(name="memory_usage", category="内存",
                         command="display memory-usage", description="内存利用率"),
            CheckCommand(name="interface_status", category="接口状态",
                         command="display interface brief",
                         description="接口 Up/Down 状态"),
            CheckCommand(name="fan_status", category="风扇",
                         command="display fan", description="风扇状态"),
            CheckCommand(name="power_status", category="电源",
                         command="display power", description="电源状态"),
            CheckCommand(name="session_table", category="会话",
                         command="display firewall session table summary",
                         description="防火墙会话表规模"),
            CheckCommand(name="config_cur", category="运行配置",
                         command="display current-configuration",
                         description="Telnet/SNMP/VTY/STP 配置检查"),
            CheckCommand(name="temperature", category="硬件环境",
                         command="display temperature",
                         description="设备温度(待真机验证)"),
            CheckCommand(name="transceiver", category="硬件环境",
                         command="display transceiver diagnosis",
                         description="光模块 DDM 收发光功率"),
            CheckCommand(name="ospf_neighbor", category="路由协议",
                         command="display ospf peer", description="OSPF 邻居状态"),
            CheckCommand(name="arp_count", category="表项规模",
                         command="display arp all", description="ARP 表项总数"),
            CheckCommand(name="storage", category="资源",
                         command="dir", description="Flash 使用率"),
            CheckCommand(name="config_diff", category="运行配置",
                         command="compare configuration",
                         description="配置一致性(未保存=高危)"),
            CheckCommand(name="reboot_reason", category="日志告警",
                         command="display reboot-info",
                         description="上次重启原因(待真机验证)"),
            CheckCommand(name="ntp_status", category="安全基线",
                         command="display ntp-service status",
                         description="NTP 时钟同步状态"),
            CheckCommand(name="lldp_neighbor", category="网络拓扑",
                         command="display lldp neighbor brief",
                         description="LLDP 邻居(拓扑绘制)"),
        ]

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        dispatch: dict[str, Any] = {
            "device_info": vrp_parsers.parse_device_info,
            "cpu_usage": vrp_parsers.parse_cpu_usage,
            "memory_usage": vrp_parsers.parse_memory_usage,
            "interface_status": vrp_parsers.parse_interface_status,
            "fan_status": vrp_parsers.parse_fan_status,
            "power_status": vrp_parsers.parse_power_status,
            "session_table": _parse_session_table,
            "config_cur": vrp_parsers.parse_config_cur,
            "temperature": vrp_parsers.parse_temperature,
            "transceiver": vrp_parsers.parse_transceiver,
            "ospf_neighbor": vrp_parsers.parse_ospf_neighbor,
            "arp_count": vrp_parsers.parse_arp_count,
            "storage": vrp_parsers.parse_storage,
            "config_diff": vrp_parsers.parse_config_diff,
            "reboot_reason": vrp_parsers.parse_reboot_reason,
            "ntp_status": vrp_parsers.parse_ntp_status,
            "lldp_neighbor": lambda out: _lldp(out, "huawei"),
        }

        cmd_obj = next((c for c in self.get_check_commands() if c.name == name), None)
        command = cmd_obj.command if cmd_obj else ""
        category = cmd_obj.category if cmd_obj else ""

        parser = dispatch.get(name)
        if parser is None:
            return ParsedResult(
                name=name, category=category, command=command,
                raw_output=raw_output, success=False,
                error=f"未实现的解析器: {name}",
            )
        try:
            parsed = parser(raw_output)
            return ParsedResult(
                name=name, category=category, command=command,
                raw_output=raw_output, parsed=parsed, success=True,
            )
        except Exception as e:
            return ParsedResult(
                name=name, category=category, command=command,
                raw_output=raw_output, success=False,
                error=f"解析失败: {e}",
            )
