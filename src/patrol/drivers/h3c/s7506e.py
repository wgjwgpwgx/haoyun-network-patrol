"""H3C S7506E-V 交换机 Driver - Comware 5.20

基于真实设备回显编写，不做格式假设。

设备信息：
  - 型号：H3C S7506E-V
  - 操作系统：Comware 5.20, Release 6708P09
  - 设备类型：核心交换机

检查项：
  - device_info       : 设备基本信息（display version）
  - cpu_usage         : CPU 利用率（display cpu）
  - memory_usage      : 内存利用率（display memory）
  - board_status      : 板卡硬件状态（display dev version）
  - fan_status        : 风扇状态（display fan）
  - power_status      : 电源状态（display power）
  - routing_table     : 路由表规模（display ip routing-table）
  - l3_interface      : 三层虚接口状态（dis ip int bri）
  - logbuffer         : 日志告警（display logbuffer）
  - telnet_service    : Telnet 服务状态（display current-configuration）
  - snmp_community    : SNMP Community 安全性（display current-configuration）
  - vty_auth          : VTY 认证配置（display current-configuration）
  - stp_status        : 生成树配置（display current-configuration）
"""
from __future__ import annotations

import re
from typing import Any

from patrol.drivers.base import BaseDriver, CheckCommand, ParsedResult
from patrol.drivers.registry import register


@register
class H3CS7506EDriver(BaseDriver):
    """H3C S7506E-V 巡检 Driver（Comware 5.20）"""

    @property
    def vendor(self) -> str:
        return "h3c"

    @property
    def device_type(self) -> str:
        return "s7506e"

    @property
    def netmiko_device_type(self) -> str:
        return "hp_comware"

    @property
    def netmiko_telnet_device_type(self) -> str:
        return "hp_comware_telnet"

    def get_check_commands(self) -> list[CheckCommand]:
        return [
            CheckCommand("device_info", "基本信息", "display version", "设备基本信息"),
            CheckCommand("cpu_usage", "CPU", "display cpu", "CPU 利用率"),
            CheckCommand("memory_usage", "内存", "display memory", "内存利用率"),
            CheckCommand("board_status", "板卡", "display dev version", "板卡硬件状态"),
            CheckCommand("fan_status", "风扇", "display fan", "风扇状态"),
            CheckCommand("power_status", "电源", "display power", "电源状态"),
            CheckCommand("routing_table", "路由", "display ip routing-table", "路由表规模"),
            CheckCommand("l3_interface", "三层接口", "dis ip int bri", "三层虚接口状态"),
            CheckCommand("logbuffer", "日志", "display logbuffer", "日志告警"),
            CheckCommand("config_cur", "运行配置", "display current-configuration", "运行配置分析"),
            CheckCommand("temperature", "硬件环境", "display environment", "设备温度传感器(待真机验证)"),
            CheckCommand("transceiver", "硬件环境", "display transceiver diagnosis", "光模块 DDM 收发光功率"),
            CheckCommand("ospf_neighbor", "路由协议", "display ospf peer", "OSPF 邻居状态(应全 Full)"),
            CheckCommand("arp_count", "表项规模", "display arp all", "ARP 表项总数"),
            CheckCommand("storage", "资源", "dir", "Flash 存储使用率"),
            CheckCommand("config_diff", "运行配置", "compare configuration", "配置一致性(未保存=高危)"),
            CheckCommand("reboot_reason", "日志告警", "display reboot-info", "上次重启原因(待真机验证)"),
            CheckCommand("ntp_status", "安全基线", "display ntp-service status", "NTP 时钟同步状态"),
            CheckCommand("lldp_neighbor", "网络拓扑",
                         "display lldp neighbor-information list",
                         "LLDP 邻居(拓扑绘制,待真机验证)"),
        ]

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        dispatch = {
            "device_info": self._parse_device_info,
            "cpu_usage": self._parse_cpu_usage,
            "memory_usage": self._parse_memory_usage,
            "board_status": self._parse_board_status,
            "fan_status": self._parse_fan_status,
            "power_status": self._parse_power_status,
            "routing_table": self._parse_routing_table,
            "l3_interface": self._parse_l3_interface,
            "logbuffer": self._parse_logbuffer,
            "config_cur": self._parse_config_cur,
            "temperature": self._parse_temperature,
            "transceiver": self._parse_transceiver,
            "ospf_neighbor": self._parse_ospf_neighbor,
            "arp_count": self._parse_arp_count,
            "storage": self._parse_storage,
            "config_diff": self._parse_config_diff,
            "reboot_reason": self._parse_reboot_reason,
            "ntp_status": self._parse_ntp_status,
            "lldp_neighbor": self._parse_lldp,
        }

        cmd_obj = next((c for c in self.get_check_commands() if c.name == name), None)
        command = cmd_obj.command if cmd_obj else ""
        category = cmd_obj.category if cmd_obj else ""

        parser = dispatch.get(name)
        if parser is None:
            return ParsedResult(name=name, category=category, command=command,
                                raw_output=raw_output, success=False,
                                error=f"未实现的解析器: {name}")
        try:
            parsed = parser(raw_output)
            return ParsedResult(name=name, category=category, command=command,
                                raw_output=raw_output, parsed=parsed, success=True)
        except Exception as e:
            return ParsedResult(name=name, category=category, command=command,
                                raw_output=raw_output, success=False,
                                error=f"解析失败: {e}")

    # ── display version ──────────────────────────────────────────

    def _parse_device_info(self, output: str) -> dict[str, Any]:
        info: dict[str, Any] = {"model": "", "device_name": "", "brand": "",
                                "serial_number": "", "mgmt_ip": "", "memory_size": "",
                                "uptime": "", "software_version": ""}

        for line in output.splitlines():
            line = line.strip()
            if "设备型号:" in line:
                info["model"] = line.split(":", 1)[1].strip()
            elif "设备名称:" in line:
                info["device_name"] = line.split(":", 1)[1].strip()
            elif "设备品牌:" in line:
                info["brand"] = line.split(":", 1)[1].strip()
            elif "设备序列号:" in line:
                info["serial_number"] = line.split(":", 1)[1].strip()
            elif "管理地址:" in line:
                info["mgmt_ip"] = line.split(":", 1)[1].strip()
            elif "内存大小:" in line:
                info["memory_size"] = line.split(":", 1)[1].strip()
            elif "Version" in line:
                m = re.search(r"Version\s+([\d.]+)", line)
                if m:
                    info["software_version"] = m.group(1)

        # uptime 在第一行
        first_line = output.splitlines()[0].strip() if output else ""
        if "weeks" in first_line or "days" in first_line or "hours" in first_line:
            info["uptime"] = first_line

        return info

    # ── display cpu ──────────────────────────────────────────────

    def _parse_cpu_usage(self, output: str) -> dict[str, Any]:
        result: dict[str, Any] = {"usage_5s": None, "usage_1m": None, "usage_5m": None}

        for line in output.splitlines():
            line = line.strip()
            m = re.match(r"(\d+)%\s+in\s+last\s+(\d+)\s+(seconds?|minutes?)", line)
            if m:
                pct = int(m.group(1))
                value = int(m.group(2))
                unit = m.group(3)
                if "second" in unit and value == 5:
                    result["usage_5s"] = pct
                elif "minute" in unit and value == 1:
                    result["usage_1m"] = pct
                elif "minute" in unit and value == 5:
                    result["usage_5m"] = pct

        # 取最近 5 秒的值作为主要指标
        result["usage_percent"] = result["usage_5s"]
        return result

    # ── display memory ───────────────────────────────────────────

    def _parse_memory_usage(self, output: str) -> dict[str, Any]:
        result: dict[str, Any] = {"total_bytes": None, "used_bytes": None, "usage_percent": None}

        for line in output.splitlines():
            line = line.strip()
            if "System Total Memory" in line:
                m = re.search(r":\s*(\d+)", line)
                if m:
                    result["total_bytes"] = int(m.group(1))
            elif "Total Used Memory" in line:
                m = re.search(r":\s*(\d+)", line)
                if m:
                    result["used_bytes"] = int(m.group(1))
            elif "Used Rate" in line:
                m = re.search(r"(\d+)%", line)
                if m:
                    result["usage_percent"] = int(m.group(1))

        return result

    # ── display dev version ──────────────────────────────────────

    def _parse_board_status(self, output: str) -> dict[str, Any]:
        boards: list[dict[str, str]] = []
        abnormal: list[str] = []

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # 格式: slot  model  role  firmware_version  description
            # 例如: 0   LSQ1SRPB   Master   0    S7500E-6605P03   None
            parts = line.split()
            if len(parts) >= 3:
                slot = parts[0]
                model = parts[1]
                role = parts[2]
                boards.append({"slot": slot, "model": model, "role": role})
                # Master/Slave/Normal 都是正常状态
                if role.lower() not in ("master", "slave", "normal"):
                    abnormal.append(f"Slot {slot}: {role}")

        return {
            "boards": boards,
            "board_count": len(boards),
            "abnormal_boards": abnormal,
            "abnormal_count": len(abnormal),
        }

    # ── display fan ──────────────────────────────────────────────

    def _parse_fan_status(self, output: str) -> dict[str, Any]:
        fans: list[dict[str, str]] = []
        abnormal_count = 0

        for line in output.splitlines():
            line = line.strip()
            # 格式: Fan    1 State: Normal
            m = re.match(r"Fan\s+(\d+)\s+State:\s*(\S+)", line, re.IGNORECASE)
            if m:
                name = f"Fan {m.group(1)}"
                state = m.group(2)
                fans.append({"name": name, "state": state})
                if state.lower() != "normal":
                    abnormal_count += 1

        return {"fans": fans, "fan_count": len(fans), "abnormal_count": abnormal_count}

    # ── display power ────────────────────────────────────────────

    def _parse_power_status(self, output: str) -> dict[str, Any]:
        powers: list[dict[str, str]] = []
        abnormal_count = 0

        for line in output.splitlines():
            line = line.strip()
            # 格式: Power        1 State: Normal
            m = re.match(r"Power\s+(\d+)\s+State:\s*(\S+)", line, re.IGNORECASE)
            if m:
                name = f"Power {m.group(1)}"
                state = m.group(2)
                powers.append({"name": name, "state": state})
                if state.lower() != "normal":
                    abnormal_count += 1

        return {"powers": powers, "power_count": len(powers), "abnormal_count": abnormal_count}

    # ── display ip routing-table ─────────────────────────────────

    def _parse_routing_table(self, output: str) -> dict[str, Any]:
        result: dict[str, Any] = {"destinations": 0, "routes": 0}

        for line in output.splitlines():
            # 格式: Destinations :785  Routes : 785
            m = re.search(r"Destinations\s*:\s*(\d+)", line)
            if m:
                result["destinations"] = int(m.group(1))
            m = re.search(r"Routes\s*:\s*(\d+)", line)
            if m:
                result["routes"] = int(m.group(1))

        return result

    # ── dis ip int bri ───────────────────────────────────────────

    def _parse_l3_interface(self, output: str) -> dict[str, Any]:
        interfaces: list[dict[str, str]] = []
        abnormal: list[str] = []

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # 格式: Vlan-interface10  up       up       192.168.155.221   Vlan-inte...
            # 也可能是: M-Ethernet0/0/0   down   down    unassigned      M-Etherne...
            parts = line.split()
            if len(parts) >= 4:
                iface = parts[0]
                phy_status = parts[1]  # up/down
                proto_status = parts[2]  # up/down
                ip_addr = parts[3]
                interfaces.append({
                    "name": iface,
                    "phy_status": phy_status,
                    "proto_status": proto_status,
                    "ip_address": ip_addr,
                })
                # 异常判断：物理或协议 down（排除 M-Ethernet 管理口和 unassigned）
                if iface.startswith("Vlan-interface"):
                    if phy_status.lower() == "down" or proto_status.lower() == "down":
                        abnormal.append(iface)

        return {
            "interfaces": interfaces,
            "interface_count": len(interfaces),
            "abnormal_interfaces": abnormal,
            "abnormal_count": len(abnormal),
        }

    # ── display logbuffer ────────────────────────────────────────

    def _parse_logbuffer(self, output: str) -> dict[str, Any]:
        total_lines = 0
        # H3C Comware 5.20 日志级别在 /N/ 格式中
        # 例如: MSTP/2/PFWD → 2 是 severity
        severity_pattern = re.compile(r"/(\d)/")
        errors: list[str] = []

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            m = severity_pattern.search(line)
            if m:
                level = int(m.group(1))
                if level <= 3:  # 0=EMERGENCY, 1=ALERT, 2=CRITICAL, 3=ERROR
                    errors.append(line)

        return {
            "total_lines": total_lines,
            "error_count": len(errors),
            "errors": errors[:20],
        }

    # ── display current-configuration ────────────────────────────

    def _parse_config_cur(self, config: str) -> dict[str, Any]:
        """从运行配置中提取多个子检查项。"""
        from patrol.drivers.security_baseline import extract_dengbao_checks

        return {
            "checks": [
                self._cur_telnet(config),
                self._cur_snmp(config),
                self._cur_vty(config),
                self._cur_stp(config),
            ] + extract_dengbao_checks(config),
        }

    def _cur_telnet(self, config: str) -> dict[str, Any]:
        telnet_enabled = bool(re.search(r"telnet\s+server\s+enable", config, re.IGNORECASE))
        ssh_enabled = bool(re.search(r"ssh\s+server\s+enable", config, re.IGNORECASE))
        return {
            "name": "telnet_service", "category": "管理服务",
            "parsed": {"telnet_enabled": telnet_enabled, "ssh_enabled": ssh_enabled},
        }

    def _cur_snmp(self, config: str) -> dict[str, Any]:
        communities: list[dict[str, str]] = []
        for m in re.finditer(r"snmp-agent\s+community\s+(read|write)\s+(\S+)", config, re.IGNORECASE):
            communities.append({"level": m.group(1), "community": m.group(2)})
        dangerous = [c for c in communities if c["community"].lower() in ("public", "private")]
        return {
            "name": "snmp_community", "category": "SNMP",
            "parsed": {"communities": communities, "community_count": len(communities),
                       "dangerous_count": len(dangerous), "has_dangerous": len(dangerous) > 0},
        }

    def _cur_vty(self, config: str) -> dict[str, Any]:
        vty_section = ""
        in_vty = False
        for line in config.splitlines():
            stripped = line.strip()
            if re.match(r"user-interface\s+vty\s+0", stripped, re.IGNORECASE):
                in_vty = True
                vty_section += line + "\n"
            elif in_vty:
                if stripped == "#":
                    break
                vty_section += line + "\n"

        has_auth = bool(re.search(r"authentication-mode\s+scheme", vty_section, re.IGNORECASE))
        has_acl = bool(re.search(r"acl\s+\d+\s+inbound", vty_section, re.IGNORECASE))
        ssh_only = bool(re.search(r"protocol\s+inbound\s+ssh", vty_section, re.IGNORECASE))

        return {
            "name": "vty_auth", "category": "VTY 安全",
            "parsed": {"has_authentication": has_auth, "has_acl": has_acl,
                       "ssh_only": ssh_only, "vty_section": vty_section.strip()},
        }

    def _cur_stp(self, config: str) -> dict[str, Any]:
        stp_enabled = bool(re.search(r"stp\s+enable", config, re.IGNORECASE))
        stp_root = bool(re.search(r"stp\s+instance\s+\d+\s+root\s+primary", config, re.IGNORECASE))
        return {
            "name": "stp_status", "category": "生成树",
            "parsed": {"stp_enabled": stp_enabled, "stp_root_primary": stp_root},
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

    def _parse_lldp(self, output: str) -> dict[str, Any]:
        from patrol.drivers.topology import parse_lldp
        return parse_lldp(output, style="h3c")

    def _parse_ntp_status(self, output: str) -> dict[str, Any]:
        from patrol.drivers.security_baseline import parse_ntp_status
        return parse_ntp_status(output)
