"""深信服 NGAF 防火墙 Driver

双驱动策略：
  1. 优先使用 WebAPI（login_method=api，需 NGAF v8.0.35+ 且开启 WebAPI 权限）
  2. 降级使用 Web 页面采集（login_method=web，Playwright）

所有命令均为只读命令。
"""
from __future__ import annotations

from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.sangfor.commands import get_ngaf_api_commands, get_ngaf_web_commands
from patrol.drivers.sangfor import parsers_api, parsers_web
from patrol.drivers.registry import register


@register
class SangforNGAFDriver(BaseDriver):
    """深信服 NGAF 防火墙巡检 Driver"""

    @property
    def vendor(self) -> str:
        return "sangfor"

    @property
    def device_type(self) -> str:
        return "ngaf_firewall"

    @property
    def netmiko_device_type(self) -> str:
        return "generic"  # NGAF 不使用 SSH

    def get_check_commands(self) -> list[CheckCommand]:
        """返回命令列表。

        默认返回 API 命令。Web 模式由 CLI 根据 login_method 切换。
        """
        return get_ngaf_api_commands()

    def get_web_commands(self) -> list[CheckCommand]:
        """返回 Web 页面命令列表（login_method=web 时使用）。"""
        return get_ngaf_web_commands()

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        """解析输出。自动判断是 API JSON 还是 Web 页面文本。"""
        cmd_obj = next((c for c in self.get_check_commands() if c.name == name), None)
        if not cmd_obj:
            cmd_obj = next((c for c in self.get_web_commands() if c.name == name), None)
        command = cmd_obj.command if cmd_obj else ""
        category = cmd_obj.category if cmd_obj else ""

        # 判断输入格式
        is_json = raw_output.strip().startswith("{") or raw_output.strip().startswith("[")

        if is_json:
            dispatch: dict[str, Any] = {
                "device_info": parsers_api.parse_device_info_api,
                "cpu_usage": parsers_api.parse_cpu_usage_api,
                "memory_usage": parsers_api.parse_memory_usage_api,
                "interface_status": parsers_api.parse_interface_status_api,
                "routing_table": parsers_api.parse_routing_table_api,
                "logbuffer": parsers_api.parse_logbuffer_api,
            }
        else:
            dispatch = {
                "device_info": parsers_web.parse_device_info_web,
                "cpu_usage": parsers_web.parse_cpu_usage_web,
                "memory_usage": parsers_web.parse_memory_usage_web,
                "interface_status": parsers_web.parse_interface_status_web,
            }

        parser = dispatch.get(name)
        if parser is None:
            return ParsedResult(
                name=name, category=category, command=command,
                raw_output=raw_output, success=False,
                error=f"未实现的解析器: {name} (format={'json' if is_json else 'text'})",
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
