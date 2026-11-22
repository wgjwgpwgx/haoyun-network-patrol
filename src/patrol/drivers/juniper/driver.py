"""Juniper Junos 设备 Driver

设备信息:
  - 厂商:Juniper Networks(瞻博)
  - 操作系统:Junos(EX/QFX/MX/SRX/SRX-SE 系列)
  - 设备类型:交换机 / 路由器
  - Netmiko device_type: juniper_junos

所有命令均为只读。解析器基于 Junos 标准输出格式编写,待真机验证。
"""
from __future__ import annotations

from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.juniper.commands import get_junos_commands
from patrol.drivers.juniper import parsers
from patrol.drivers.registry import register
from patrol.drivers.topology import parse_lldp as _lldp


@register
class JunosDriver(BaseDriver):
    """Juniper Junos 巡检 Driver"""

    @property
    def vendor(self) -> str:
        return "juniper"

    @property
    def device_type(self) -> str:
        return "junos"

    @property
    def netmiko_device_type(self) -> str:
        return "juniper_junos"

    @property
    def netmiko_telnet_device_type(self) -> str:
        return "juniper_junos_telnet"

    def get_check_commands(self) -> list[CheckCommand]:
        return get_junos_commands()

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        dispatch: dict[str, Any] = {
            "device_info": parsers.parse_device_info,
            "cpu_usage": parsers.parse_cpu_usage,
            "memory_usage": parsers.parse_memory_usage,
            "interface_status": parsers.parse_interface_status,
            "fan_status": parsers.parse_fan_status,
            "power_status": parsers.parse_power_status,
            "system_alarms": parsers.parse_system_alarms,
            "config_cur": parsers.parse_config_services,
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
