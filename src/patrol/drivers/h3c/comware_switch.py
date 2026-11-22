"""H3C Comware 交换机 Driver - 采集 4 项检查

检查项：
  1. device_info    - 设备基本信息（display version）
  2. cpu_usage      - CPU 利用率（display cpu-usage）
  3. memory_usage   - 内存利用率（display memory）
  4. interface_status - 接口状态（display interface brief）

所有 H3C Comware 交换机的命令定义和回显解析逻辑都在此模块中。
业务层不得直接引用本模块中的命令字符串。

解析逻辑基于 Comware V5/V7 公开文档的典型输出格式。
实际设备回显可能因版本/型号不同而有差异。
如果解析失败，parse_output 返回 success=False，
分析层应将其标记为 UNKNOWN。
"""
from __future__ import annotations

import re
from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.registry import register


@register
class H3CComwareSwitchDriver(BaseDriver):
    """H3C Comware 交换机巡检 Driver"""

    @property
    def vendor(self) -> str:
        return "h3c"

    @property
    def device_type(self) -> str:
        return "comware_switch"

    @property
    def netmiko_device_type(self) -> str:
        # Netmiko 使用 'hp_comware' 标识 H3C Comware 设备
        return "hp_comware"

    @property
    def netmiko_telnet_device_type(self) -> str:
        return "hp_comware_telnet"

    def get_check_commands(self) -> list[CheckCommand]:
        return [
            CheckCommand(
                name="device_info",
                category="基本信息",
                command="display version",
                description="获取设备型号、版本、运行时间",
            ),
            CheckCommand(
                name="cpu_usage",
                category="CPU",
                command="display cpu-usage",
                description="检查 CPU 利用率",
            ),
            CheckCommand(
                name="memory_usage",
                category="内存",
                command="display memory",
                description="检查内存利用率",
            ),
            CheckCommand(
                name="interface_status",
                category="接口状态",
                command="display interface brief",
                description="检查接口状态",
            ),
            CheckCommand(
                name="interface_errors",
                category="接口错误",
                command="display interface",
                description="检查接口错误包计数",
            ),
            CheckCommand(
                name="telnet_service",
                category="管理服务",
                command="display tcp status",
                description="检查 Telnet 服务是否启用",
            ),
            CheckCommand(
                name="temperature", category="硬件环境",
                command="display environment",
                description="设备温度传感器(待真机验证)",
            ),
            CheckCommand(
                name="transceiver", category="硬件环境",
                command="display transceiver diagnosis",
                description="光模块 DDM 收发光功率对照门限",
            ),
            CheckCommand(
                name="ospf_neighbor", category="路由协议",
                command="display ospf peer",
                description="OSPF 邻居状态(应全 Full)",
            ),
            CheckCommand(
                name="arp_count", category="表项规模",
                command="display arp all",
                description="ARP 表项总数",
            ),
            CheckCommand(
                name="storage", category="资源",
                command="dir",
                description="Flash 存储使用率",
            ),
            CheckCommand(
                name="config_diff", category="运行配置",
                command="compare configuration",
                description="running 与 startup 一致性(未保存=高危)",
            ),
            CheckCommand(
                name="reboot_reason", category="日志告警",
                command="display reboot-info",
                description="上次重启原因(待真机验证)",
            ),
            CheckCommand(
                name="lldp_neighbor", category="网络拓扑",
                command="display lldp neighbor-information list",
                description="LLDP 邻居(拓扑绘制,待真机验证)",
            ),
        ]

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        """根据检查项名称分派到对应的解析方法。"""
        dispatch = {
            "device_info": self._parse_device_info,
            "cpu_usage": self._parse_cpu_usage,
            "memory_usage": self._parse_memory_usage,
            "interface_status": self._parse_interface_status,
            "interface_errors": self._parse_interface_errors,
            "telnet_service": self._parse_telnet_service,
            "temperature": self._parse_temperature,
            "transceiver": self._parse_transceiver,
            "ospf_neighbor": self._parse_ospf_neighbor,
            "arp_count": self._parse_arp_count,
            "storage": self._parse_storage,
            "config_diff": self._parse_config_diff,
            "reboot_reason": self._parse_reboot_reason,
            "lldp_neighbor": self._parse_lldp,
        }

        cmd_obj = next(
            (c for c in self.get_check_commands() if c.name == name), None
        )
        command = cmd_obj.command if cmd_obj else ""
        category = cmd_obj.category if cmd_obj else ""

        parser = dispatch.get(name)
        if parser is None:
            return ParsedResult(
                name=name,
                category=category,
                command=command,
                raw_output=raw_output,
                success=False,
                error=f"未实现的解析器: {name}",
            )

        try:
            parsed = parser(raw_output)
            return ParsedResult(
                name=name,
                category=category,
                command=command,
                raw_output=raw_output,
                parsed=parsed,
                success=True,
            )
        except Exception as e:
            return ParsedResult(
                name=name,
                category=category,
                command=command,
                raw_output=raw_output,
                success=False,
                error=f"解析失败: {e}",
            )

    # ── 解析器 ────────────────────────────────────────────────────

    def _parse_device_info(self, output: str) -> dict[str, Any]:
        """解析 display version

        提取：型号、软件版本、运行时间、序列号。
        """
        info: dict[str, Any] = {
            "model": "",
            "software_version": "",
            "uptime": "",
            "serial_number": "",
        }

        # 型号：匹配 H3C S5560X-54C-EI 等（字母+数字，跳过 Software 等纯字母词）
        model_match = re.search(
            r"((?:H3C\s+)?(?:S|MSR|SR|WX|SecPath|FC|ER)\d\S*)", output
        )
        if model_match:
            info["model"] = model_match.group(1).strip()

        # 软件版本
        ver_match = re.search(r"Version\s+(\d+\.\d+\.\d+)", output, re.IGNORECASE)
        if ver_match:
            info["software_version"] = ver_match.group(1).strip()

        # 运行时间
        uptime_match = re.search(r"uptime is\s+(.+?)(?:\n|$)", output, re.IGNORECASE)
        if uptime_match:
            info["uptime"] = uptime_match.group(1).strip()

        # 序列号
        serial_match = re.search(
            r"(?:Serial Number|DEVICE_SERIAL_NUMBER)\s*[:\s]+(\S+)",
            output,
            re.IGNORECASE,
        )
        if serial_match:
            info["serial_number"] = serial_match.group(1).strip()

        return info

    def _parse_cpu_usage(self, output: str) -> dict[str, Any]:
        """解析 display cpu-usage

        提取 CPU 利用率百分比。
        典型格式：
          Slot 0 CPU 0 usage:
                 12% in last 5 seconds
        """
        result: dict[str, Any] = {"usage_percent": None}

        percentages = re.findall(r"(\d+)%", output)
        if percentages:
            # 取第一个百分比值（通常是最近 5 秒）
            result["usage_percent"] = int(percentages[0])

        return result

    def _parse_memory_usage(self, output: str) -> dict[str, Any]:
        """解析 display memory

        提取内存利用率。
        典型格式：
          Used Rate: 35%
        """
        result: dict[str, Any] = {"usage_percent": None}

        usage_match = re.search(
            r"(?:Used\s+Rate|Usage)\s*[:\s]+(\d+)%", output, re.IGNORECASE
        )
        if usage_match:
            result["usage_percent"] = int(usage_match.group(1))
        else:
            # 从 total/used 数值计算
            total_match = re.search(r"Total\s*[:\s]+(\d+)", output, re.IGNORECASE)
            used_match = re.search(r"Used\s*[:\s]+(\d+)", output, re.IGNORECASE)
            if total_match and used_match:
                total = int(total_match.group(1))
                used = int(used_match.group(1))
                if total > 0:
                    result["usage_percent"] = round(used / total * 100)

        return result

    def _parse_interface_status(self, output: str) -> dict[str, Any]:
        """解析 display interface brief

        提取接口列表，标记异常接口（link-down 的接口）。
        典型格式：
          Interface            Link Speed   Duplex  Type PVID
          GE1/0/1              UP   1G      full    A    10
          GE1/0/2              DOWN auto    A       A    1
        """
        interfaces: list[dict[str, str]] = []
        abnormal: list[str] = []

        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Interface") or line.startswith("---"):
                continue
            match = re.match(
                r"^(\S+)\s+(UP|DOWN|\*DOWN)\s+(\S+)\s+(\S+)\s+(\S+)\s*(\S*)",
                line,
            )
            if match:
                iface = match.group(1)
                link = match.group(2)
                speed = match.group(3)
                interfaces.append({"name": iface, "link": link, "speed": speed})
                if link == "DOWN":
                    abnormal.append(iface)

        return {
            "total": len(interfaces),
            "interfaces": interfaces,
            "abnormal_interfaces": abnormal,
            "abnormal_count": len(abnormal),
        }

    def _parse_interface_errors(self, output: str) -> dict[str, Any]:
        """解析 display interface 输出中的错误包计数。

        提取每个接口的 input errors 和 output errors。
        典型格式：
          GigabitEthernet1/0/1
          ...
            Input: 1234 packets, 5678 bytes
                   0 errors, 0 CRC, ...
            Output: 2345 packets, 6789 bytes
                    3 errors, 0 aborted, ...
        """
        error_interfaces: list[dict[str, Any]] = []
        current_iface = ""
        input_errors = 0
        output_errors = 0

        for line in output.splitlines():
            # 接口名行：以 GigabitEthernet / Ten-GigabitEthernet 等开头
            iface_match = re.match(
                r"^((?:GigabitEthernet|Ten-GigabitEthernet|XGE|GE|"
                r"LoopBack|Vlan-interface|MGE)\S+)",
                line,
            )
            if iface_match:
                # 保存上一个接口的错误计数
                if current_iface and (input_errors > 0 or output_errors > 0):
                    error_interfaces.append({
                        "name": current_iface,
                        "input_errors": input_errors,
                        "output_errors": output_errors,
                    })
                current_iface = iface_match.group(1)
                input_errors = 0
                output_errors = 0
                continue

            # Input errors 行
            err_match = re.search(r"(\d+)\s+errors", line, re.IGNORECASE)
            if err_match and current_iface:
                # 区分 input 和 output：看前面是否有 "Input:" 或 "Output:"
                if re.search(r"\bInput\b", line, re.IGNORECASE):
                    input_errors = int(err_match.group(1))
                elif re.search(r"\bOutput\b", line, re.IGNORECASE):
                    output_errors = int(err_match.group(1))
                # 独立的 "N errors" 行（紧接在 Input/Output 行之后）
                elif "error" in line.lower() and "CRC" not in line:
                    # 这种行通常是 Input 或 Output 的详细行
                    # 通过上下文判断（简化处理：如果还没设 input，设 input；否则设 output）
                    if input_errors == 0:
                        input_errors = int(err_match.group(1))
                    else:
                        output_errors = int(err_match.group(1))

        # 保存最后一个接口
        if current_iface and (input_errors > 0 or output_errors > 0):
            error_interfaces.append({
                "name": current_iface,
                "input_errors": input_errors,
                "output_errors": output_errors,
            })

        total_errors = sum(
            e["input_errors"] + e["output_errors"] for e in error_interfaces
        )

        return {
            "error_interfaces": error_interfaces,
            "error_count": total_errors,
            "interface_with_errors": len(error_interfaces),
        }

    def _parse_telnet_service(self, output: str) -> dict[str, Any]:
        """解析 display tcp status 输出，检查 Telnet 服务是否启用。

        典型格式：
          Local Address        Foreign Address      State        Slot
          0.0.0.0:23           0.0.0.0:0            LISTEN       0
          192.168.1.1:22       192.168.1.100:12345  ESTABLISHED  0
        """
        telnet_enabled = False
        telnet_ports: list[dict[str, str]] = []

        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Local"):
                continue
            # 匹配包含 :23 的行（Telnet 端口）
            # 格式：0.0.0.0:23 或 192.168.1.1:23
            match = re.search(r"[\d.]+:(\d+)\s+", line)
            if match:
                port = int(match.group(1))
                if port == 23:
                    telnet_enabled = True
                    telnet_ports.append({"line": line})

        return {
            "telnet_enabled": telnet_enabled,
            "telnet_ports": telnet_ports,
        }

    # ── 九大类扩展检查(复用 h3c.shared_parsers,标准格式待真机验证) ──

    def _parse_temperature(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_temperature_h3c(output)

    def _parse_transceiver(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_transceiver(output)

    def _parse_ospf_neighbor(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_ospf_neighbor(output)

    def _parse_arp_count(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_arp_count(output)

    def _parse_storage(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_storage(output)

    def _parse_config_diff(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_config_diff(output)

    def _parse_reboot_reason(self, output: str) -> dict[str, Any]:
        from patrol.drivers.h3c import shared_parsers
        return shared_parsers.parse_reboot_reason(output)

    def _parse_lldp(self, output: str) -> dict:
        from patrol.drivers.topology import parse_lldp
        return parse_lldp(output, style="h3c")
