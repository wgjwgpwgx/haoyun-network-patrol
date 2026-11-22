"""迪普 DPtech 防火墙 Driver

设备信息：
  - 厂商：DPtech
  - 设备类型：防火墙（FW 系列）
  - 采集方式：Web（requests + BeautifulSoup 解析传统 HTML 页面）
  - 无官方 REST API

所有命令均为只读。
"""
from __future__ import annotations

from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.dptech.commands import get_fw_firewall_commands
from patrol.drivers.dptech import parsers
from patrol.drivers.registry import register


@register
class DPtechFWFirewallDriver(BaseDriver):
    """迪普 DPtech 防火墙巡检 Driver"""

    @property
    def vendor(self) -> str:
        return "dptech"

    @property
    def device_type(self) -> str:
        return "fw_firewall"

    @property
    def netmiko_device_type(self) -> str:
        return "generic"

    def get_check_commands(self) -> list[CheckCommand]:
        return get_fw_firewall_commands()

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        dispatch: dict[str, Any] = {
            "device_info": parsers.parse_device_info,
            "cpu_usage": parsers.parse_cpu_usage,
            "memory_usage": parsers.parse_memory_usage,
            "interface_status": parsers.parse_interface_status,
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
