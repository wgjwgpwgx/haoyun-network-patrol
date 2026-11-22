"""迈普 MyPower 交换机 Driver

设备信息：
  - 厂商：Maipu(迈普)
  - 操作系统：MyPower
  - 设备类型：交换机（S3100/S4320/NS 系列等，信创名录常见）
  - Netmiko device_type: cisco_ios（MyPower CLI 高度兼容 IOS 风格，提示符 `hostname#`；
    官方未提供专用 netmiko 类型，借道 IOS 通道，交互差异待真机验证）

所有命令均为只读命令。
"""
from __future__ import annotations

from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.maipu.commands import get_mypower_switch_commands
from patrol.drivers.maipu import parsers
from patrol.drivers.registry import register
from patrol.drivers.topology import parse_lldp as _lldp


@register
class MaipuMyPowerSwitchDriver(BaseDriver):
    """迈普 MyPower 交换机巡检 Driver"""

    @property
    def vendor(self) -> str:
        return "maipu"

    @property
    def device_type(self) -> str:
        return "mypower_switch"

    @property
    def netmiko_device_type(self) -> str:
        return "cisco_ios"

    @property
    def netmiko_telnet_device_type(self) -> str:
        return "cisco_ios_telnet"

    def get_check_commands(self) -> list[CheckCommand]:
        return get_mypower_switch_commands()

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        dispatch: dict[str, Any] = {
            "device_info": parsers.parse_device_info,
            "cpu_usage": parsers.parse_cpu_usage,
            "memory_usage": parsers.parse_memory_usage,
            "interface_status": parsers.parse_interface_status,
            "routing_table": parsers.parse_routing_table,
            "logbuffer": parsers.parse_logbuffer,
            "config_cur": parsers.parse_config_cur,
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
