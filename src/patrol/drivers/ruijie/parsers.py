"""锐捷 RGOS 交换机回显解析器

基于 RG-S5750C-48GT4XS-H (RGOS 11.4(1)B70P1) 真实回显编写。
无法解析的字段返回 None / 0 / [] / False，不猜测。
"""
from __future__ import annotations

import re
from typing import Any


def parse_device_info(output: str) -> dict[str, Any]:
    """解析 show version

    真实格式：
      System description : Ruijie 10G Ethernet Switch(S5750C-48GT4XS-H) By Ruijie Networks
      System uptime      : 28 weeks, 2 days, 05 hours, 41 minutes
      System software version : S5700H_RGOS 11.4(1)B70P1
      System serial number : G1M109S003135
    """
    info: dict[str, Any] = {
        "model": "",
        "device_name": "",
        "software_version": "",
        "uptime": "",
        "serial_number": "",
    }

    for line in output.splitlines():
        # 型号：System description : Ruijie 10G Ethernet Switch(S5750C-48GT4XS-H) ...
        m = re.search(r"System description\s*:.*\((\S+)\)", line)
        if m:
            info["model"] = m.group(1)

        # 软件版本：System software version : S5700H_RGOS 11.4(1)B70P1
        m = re.search(r"System software version\s*:\s*(\S+)", line)
        if m:
            info["software_version"] = m.group(1)

        # 运行时间：System uptime      : 28 weeks, 2 days, 05 hours, 41 minutes
        m = re.search(r"System uptime\s*:\s*(.+)", line)
        if m:
            info["uptime"] = m.group(1).strip()

        # 序列号：System serial number : G1M109S003135
        m = re.search(r"System serial number\s*:\s*(\S+)", line)
        if m:
            info["serial_number"] = m.group(1)

    return info


def parse_cpu_usage(output: str) -> dict[str, Any]:
    """解析 show cpu

    真实格式：
      CPU utilization in five seconds: 11.2%
      CPU utilization in one minute : 10.7%
      CPU utilization in five minutes: 9.5%
    """
    result: dict[str, Any] = {
        "usage_percent": None,
        "usage_5s": None,
        "usage_1m": None,
        "usage_5m": None,
    }

    for line in output.splitlines():
        # CPU utilization in five seconds: 11.2%
        m = re.search(r"five seconds:\s*([\d.]+)%", line)
        if m:
            result["usage_5s"] = float(m.group(1))

        m = re.search(r"one minute\s*:\s*([\d.]+)%", line)
        if m:
            result["usage_1m"] = float(m.group(1))

        m = re.search(r"five minutes:\s*([\d.]+)%", line)
        if m:
            result["usage_5m"] = float(m.group(1))

    # 取 5 秒值作为主指标
    if result["usage_5s"] is not None:
        result["usage_percent"] = round(result["usage_5s"])

    return result


def parse_memory_usage(output: str) -> dict[str, Any]:
    """解析 show memory

    真实格式：
      System Total Memory(bytes): 1073741824
      Total Used Memory(bytes): 279134208
      Memory Used Rate: 26%
    """
    result: dict[str, Any] = {"total_bytes": None, "used_bytes": None, "usage_percent": None}

    for line in output.splitlines():
        m = re.search(r"System Total Memory\(bytes\):\s*(\d+)", line)
        if m:
            result["total_bytes"] = int(m.group(1))

        m = re.search(r"Total Used Memory\(bytes\):\s*(\d+)", line)
        if m:
            result["used_bytes"] = int(m.group(1))

        m = re.search(r"Memory Used Rate:\s*(\d+)%", line)
        if m:
            result["usage_percent"] = int(m.group(1))

    return result


def parse_interface_status(output: str) -> dict[str, Any]:
    """解析 show ip interface brief

    真实格式：
      Interface              IP-Address(Pri)      IP-Address(Sec)  Status       Protocol
      Vlan 10                192.168.162.34/24      no address       up           up
      Vlan 40                no address           no address       down         down
      MGMT 0                 192.168.1.10/24      no address       up           up

    注意：锐捷的 VLAN 接口名是 "Vlan 10"（有空格），不是 "Vlanif10"。
    """
    result: dict[str, Any] = {
        "interfaces": [],
        "abnormal_interfaces": [],
        "abnormal_count": 0,
        "total": 0,
    }

    # IP 地址模式：192.168.162.34/24 或 no address
    ip_pattern = re.compile(r"^(\d+\.\d+\.\d+\.\d+/\d+|no)$")

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Interface") or line.startswith("---"):
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        # Status 和 Protocol 是最后两个字段
        proto = parts[-1]
        status = parts[-2]

        # 接口名：从行首开始，直到遇到 IP 地址或 "no"
        # IP 地址格式：192.168.162.34/24 或 "no"（表示 no address）
        iface_parts = []
        for part in parts[:-2]:  # 排除最后两个字段（Status, Protocol）
            if ip_pattern.match(part):
                break
            iface_parts.append(part)

        iface = " ".join(iface_parts)
        if not iface:
            continue

        entry = {"name": iface, "status": status, "protocol": proto}
        result["interfaces"].append(entry)
        result["total"] += 1

        if status.lower() == "down" or proto.lower() == "down":
            result["abnormal_interfaces"].append(iface)
            result["abnormal_count"] += 1

    return result


def parse_routing_table(output: str) -> dict[str, Any]:
    """解析 show ip route

    真实格式：
      统计路由条目数（排除 Codes 行、空行、Gateway 行）
    """
    result: dict[str, Any] = {"destinations": 0, "routes": 0, "has_default_route": False}

    route_count = 0
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过 Codes 说明行和 Gateway 行
        if line.startswith("Codes") or line.startswith("Gateway") or line.startswith("N1") or line.startswith("E1") or line.startswith("i "):
            continue
        # 路由行格式：C / S / O / R / B + 空格 + 目的网络
        if re.match(r"^[A-Z*]+\s+", line):
            route_count += 1
            if line.startswith("S*") or line.startswith("S "):
                if "0.0.0.0/0" in line:
                    result["has_default_route"] = True

    result["routes"] = route_count
    result["destinations"] = route_count
    return result


def parse_logbuffer(output: str) -> dict[str, Any]:
    """解析 show logging reverse

    真实格式（锐捷日志）：
      2026‑09‑21 15:45:12 RJ‑SW‑AGG‑01 %%7‑SHELL: ...
      严重级别在 %%N 中：N <= 3 为告警
    """
    result: dict[str, Any] = {"total_lines": 0, "error_count": 0, "errors": []}
    severity_pattern = re.compile(r"%%(\d)")

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        result["total_lines"] += 1

        m = severity_pattern.search(line)
        if m:
            level = int(m.group(1))
            if level <= 3:
                result["error_count"] += 1
                result["errors"].append(line)

    return result


def parse_config_cur(output: str) -> dict[str, Any]:
    """解析 show running-config

    锐捷配置格式与华为/H3C 不同：
      - 使用 hostname 而非 sysname
      - 使用 line vty + login local + transport input ssh
      - 使用 spanning-tree 而非 stp
    """
    telnet_enabled = False
    ssh_enabled = False
    communities: list[dict[str, str]] = []
    has_auth = False
    ssh_only = False
    stp_enabled = False

    in_vty = False
    for line in output.splitlines():
        stripped = line.strip().lower()

        # Telnet（锐捷没有显式的 telnet server enable，看 transport input）
        if "telnet server enable" in stripped:
            telnet_enabled = True

        # SSH
        if "ssh server enable" in stripped:
            ssh_enabled = True

        # SNMP
        m = re.search(r"snmp-server\s+community\s+(\S+)", line, re.IGNORECASE)
        if m:
            communities.append({"level": "read", "community": m.group(1)})

        # VTY
        if re.match(r"line\s+vty", stripped):
            in_vty = True
        elif in_vty:
            if stripped == "!" or stripped == "end" or re.match(r"line\s+", stripped) or re.match(r"interface\s+", stripped):
                in_vty = False
            else:
                if "login" in stripped:
                    has_auth = True
                if "transport input ssh" in stripped:
                    ssh_only = True
                # transport input telnet 表示允许 telnet
                if "transport input telnet" in stripped or "transport input all" in stripped:
                    telnet_enabled = True

        # STP
        if re.match(r"spanning-tree\b", stripped) and "mode" not in stripped:
            stp_enabled = True

    dangerous = [c for c in communities if c["community"].lower() in ("public", "private")]

    return {
        "checks": [
            {
                "name": "telnet_service",
                "category": "管理服务",
                "parsed": {"telnet_enabled": telnet_enabled, "ssh_enabled": ssh_enabled},
            },
            {
                "name": "snmp_community",
                "category": "SNMP",
                "parsed": {
                    "communities": communities,
                    "community_count": len(communities),
                    "dangerous_count": len(dangerous),
                    "has_dangerous": len(dangerous) > 0,
                },
            },
            {
                "name": "vty_auth",
                "category": "VTY 安全",
                "parsed": {"has_authentication": has_auth, "has_acl": False, "ssh_only": ssh_only},
            },
            {
                "name": "stp_status",
                "category": "生成树",
                "parsed": {"stp_enabled": stp_enabled, "stp_root_primary": False},
            },
        ]
    }
