"""华为 VRP 交换机 Driver

设备信息：
  - 厂商：Huawei
  - 操作系统：VRP (Versatile Routing Platform)
  - 设备类型：交换机（S5700/S6700/CE 系列等）
  - Netmiko device_type: huawei

所有命令均为只读命令。
解析器基于真实回显编写，标注 TODO 的解析器待补充。
"""
from __future__ import annotations

from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.huawei.commands import get_vrp_switch_commands
from patrol.drivers.huawei import parsers
from patrol.drivers.registry import register
from patrol.drivers.topology import parse_lldp as _lldp


@register
class HuaweiVRPSwitchDriver(BaseDriver):
    """华为 VRP 交换机巡检 Driver"""

    @property
    def vendor(self) -> str:
        return "huawei"

    @property
    def netmiko_telnet_device_type(self) -> str:
        return "huawei_telnet"

    @property
    def device_type(self) -> str:
        return "vrp_switch"

    @property
    def netmiko_device_type(self) -> str:
        return "huawei"

    def get_check_commands(self) -> list[CheckCommand]:
        return get_vrp_switch_commands()

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        dispatch: dict[str, Any] = {
            "device_info": parsers.parse_device_info,
            "cpu_usage": parsers.parse_cpu_usage,
            "memory_usage": parsers.parse_memory_usage,
            "interface_status": parsers.parse_interface_status,
            "fan_status": parsers.parse_fan_status,
            "power_status": parsers.parse_power_status,
            "logbuffer": parsers.parse_logbuffer,
            "routing_table": parsers.parse_routing_table,
            "config_cur": parsers.parse_config_cur,
            "temperature": parsers.parse_temperature,
            "transceiver": parsers.parse_transceiver,
            "ospf_neighbor": parsers.parse_ospf_neighbor,
            "arp_count": parsers.parse_arp_count,
            "storage": parsers.parse_storage,
            "config_diff": parsers.parse_config_diff,
            "reboot_reason": parsers.parse_reboot_reason,
            "ntp_status": parsers.parse_ntp_status,
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
