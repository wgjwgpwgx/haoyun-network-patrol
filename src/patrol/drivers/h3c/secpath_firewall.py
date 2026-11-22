"""H3C SecPath 防火墙 Driver(复用 Comware 交换机解析器)

设备信息:
  - 厂商:H3C
  - 操作系统:Comware(F100/F1000 系列防火墙)
  - Netmiko device_type: hp_comware

命令与 Comware 交换机基本一致,额外增加防火墙会话表检查。
解析器复用 H3CComwareSwitchDriver,会话表解析为本文件新增,均待真机验证。
"""
from __future__ import annotations

import re
from typing import Any

from patrol.drivers.base import CheckCommand, ParsedResult
from patrol.drivers.h3c.comware_switch import H3CComwareSwitchDriver
from patrol.drivers.registry import register


def _parse_session_table(output: str) -> dict[str, Any]:
    """解析 display session table summary

    标准格式(Comware 防火墙):
      Slot 1:
        Current sessions: 12345
      或
      Current sessions:1234
    """
    result: dict[str, Any] = {"session_count": None}
    counts = []
    for line in output.splitlines():
        m = re.search(r"Current sessions?\s*[:：]?\s*(\d+)", line, re.IGNORECASE)
        if m:
            counts.append(int(m.group(1)))
    if counts:
        # 多 Slot 取最大值(反映设备当前承载规模)
        result["session_count"] = max(counts)
    return result


def _parse_simple_status(output: str) -> dict[str, Any]:
    """解析 display fan / display power 的状态词统计(Comware 防火墙)。

    标准格式:
      Fan 1 State: Normal
      Power 1 State: Normal
    """
    normal = len(re.findall(r"\b(Normal|OK|Good)\b", output, re.IGNORECASE))
    fault_matches = re.findall(
        r"\b(Fault|Failed|Error|Absent|Warning|Abnormal)\b", output, re.IGNORECASE)
    total = normal + len(fault_matches)
    return {
        "total": total,
        # 一个状态词都识别不到(待真机验证驱动):置 None → 引擎判 UNKNOWN
        "abnormal_count": len(fault_matches) if total else None,
        "abnormal": fault_matches,
    }


@register
class H3CSecPathFirewallDriver(H3CComwareSwitchDriver):
    """H3C SecPath 防火墙巡检 Driver"""

    @property
    def device_type(self) -> str:
        return "secpath_firewall"

    def get_check_commands(self) -> list[CheckCommand]:
        return [
            CheckCommand(name="device_info", category="基本信息",
                         command="display version",
                         description="设备型号、版本、运行时间、序列号"),
            CheckCommand(name="cpu_usage", category="CPU",
                         command="display cpu-usage", description="CPU 利用率"),
            CheckCommand(name="memory_usage", category="内存",
                         command="display memory", description="内存利用率"),
            CheckCommand(name="interface_status", category="接口状态",
                         command="display interface brief",
                         description="接口 Up/Down 状态"),
            CheckCommand(name="interface_errors", category="接口状态",
                         command="display interface",
                         description="接口错误包统计"),
            CheckCommand(name="fan_status", category="风扇",
                         command="display device", description="风扇/单板状态"),
            CheckCommand(name="power_status", category="电源",
                         command="display power", description="电源状态"),
            CheckCommand(name="session_table", category="会话",
                         command="display session table summary",
                         description="防火墙会话表规模"),
            CheckCommand(name="temperature", category="硬件环境",
                         command="display environment", description="设备温度(待真机验证)"),
            CheckCommand(name="transceiver", category="硬件环境",
                         command="display transceiver diagnosis", description="光模块 DDM"),
            CheckCommand(name="ospf_neighbor", category="路由协议",
                         command="display ospf peer", description="OSPF 邻居状态"),
            CheckCommand(name="arp_count", category="表项规模",
                         command="display arp all", description="ARP 表项总数"),
            CheckCommand(name="storage", category="资源",
                         command="dir", description="Flash 使用率"),
            CheckCommand(name="config_diff", category="运行配置",
                         command="compare configuration", description="配置一致性(未保存=高危)"),
            CheckCommand(name="reboot_reason", category="日志告警",
                         command="display reboot-info", description="上次重启原因(待真机验证)"),
            CheckCommand(name="lldp_neighbor", category="网络拓扑",
                         command="display lldp neighbor-information list",
                         description="LLDP 邻居(拓扑绘制)"),
        ]

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        cmd_obj = next(
            (c for c in self.get_check_commands() if c.name == name), None)
        command = cmd_obj.command if cmd_obj else ""
        category = cmd_obj.category if cmd_obj else ""

        local: dict[str, Any] = {
            "session_table": _parse_session_table,
            "fan_status": _parse_simple_status,
            "power_status": _parse_simple_status,
        }
        if name in local:
            try:
                return ParsedResult(
                    name=name, category=category, command=command,
                    raw_output=raw_output, parsed=local[name](raw_output),
                    success=True,
                )
            except Exception as e:
                return ParsedResult(
                    name=name, category=category, command=command,
                    raw_output=raw_output, success=False,
                    error=f"解析失败: {e}",
                )
        # 其余检查项复用 Comware 解析器
        return super().parse_output(name, raw_output)
