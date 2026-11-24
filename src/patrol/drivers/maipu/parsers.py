"""迈普 MyPower 交换机回显解析器

依据 MyPower 官方手册格式构造样本编写（CLI 类 IOS 风格）;
**尚未经真机回显验证**,现场遇格式不符按 UNKNOWN 流程保留原始回显反馈适配。
无法解析的字段返回 None / 0 / [] / False，不猜测。
"""
from __future__ import annotations

import re
from typing import Any


def parse_device_info(output: str) -> dict[str, Any]:
    """解析 show version

    样本格式：
      MyPower Operating System Software
      MyPower S3100V2 Software Version 2.10.13
      Compiled on Jul 08 2024, 15:32:10
      MyPower S3100V2-24GT4XS uptime is 15 weeks, 1 day, 2 hours
      Serial Number : MP1102260B7
    """
    info: dict[str, Any] = {
        "model": "",
        "device_name": "",
        "software_version": "",
        "uptime": "",
        "serial_number": "",
    }

    for line in output.splitlines():
        # 软件版本：Version 2.10.13
        m = re.search(r"Version\s+(\S+)", line)
        if m and not info["software_version"]:
            info["software_version"] = m.group(1)

        # 型号：MyPower S3100V2-24GT4XS uptime / MyPower S3100V2 Software
        m = re.search(r"MyPower\s+(\S+)\s+uptime", line)
        if m:
            info["model"] = m.group(1)
        elif not info["model"]:
            m = re.search(r"MyPower\s+(\S+)\s+Software", line)
            if m:
                info["model"] = m.group(1)

        # 运行时间
        m = re.search(r"uptime\s+is\s+(.+)", line)
        if m:
            info["uptime"] = m.group(1).strip().rstrip(",")

        # 序列号
        m = re.search(r"Serial\s*[Nn]umber\s*:?\s*(\S+)", line)
        if m:
            info["serial_number"] = m.group(1)

    return info


def parse_cpu_usage(output: str) -> dict[str, Any]:
    """解析 show processes cpu

    样本格式（类 IOS）：
      CPU utilization in five seconds: 12%/2%; one minute: 9%; five minutes: 7%
    """
    result: dict[str, Any] = {
        "usage_percent": None,
        "usage_5s": None,
        "usage_1m": None,
        "usage_5m": None,
    }

    m = re.search(r"(?:five|5)\s*seconds?\s*:?\s*([\d.]+)%", output)
    if m:
        result["usage_5s"] = float(m.group(1))

    m = re.search(r"(?:one|1)\s*minute\s*:?\s*([\d.]+)%", output)
    if m:
        result["usage_1m"] = float(m.group(1))

    m = re.search(r"(?:five|5)\s*minutes?\s*:?\s*([\d.]+)%", output)
    if m:
        result["usage_5m"] = float(m.group(1))

    if result["usage_5s"] is not None:
        result["usage_percent"] = round(result["usage_5s"])

    return result


def parse_memory_usage(output: str) -> dict[str, Any]:
    """解析 show memory statistics

    样本格式（类 IOS 表格）：
                Head      Total(b)     Used(b)     Free(b)
      Processor 0x1A2B3C  262144000    89128960    173015040
    """
    result: dict[str, Any] = {"total_bytes": None, "used_bytes": None, "usage_percent": None}

    for line in output.splitlines():
        m = re.search(r"(\d+)\s+(\d+)\s+(\d+)\s*$", line.rstrip())
        if m and "Head" not in line:
            result["total_bytes"] = int(m.group(1))
            result["used_bytes"] = int(m.group(2))
            break

    if result["total_bytes"] and result["used_bytes"]:
        result["usage_percent"] = round(result["used_bytes"] * 100 / result["total_bytes"])

    return result


def parse_interface_status(output: str) -> dict[str, Any]:
    """解析 show ip interface brief

    样本格式（类 IOS）：
      Interface              IP-Address      OK? Method Status                Protocol
      Vlan1                  192.168.10.1    YES NVRAM  up                    up
      GigabitEthernet0/1     unassigned      YES unset   up                    up
      GigabitEthernet0/2     unassigned      YES unset   down                 down
    """
    result: dict[str, Any] = {
        "interfaces": [],
        "abnormal_interfaces": [],
        "abnormal_count": 0,
        "total": 0,
    }

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Interface") or line.startswith("---"):
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        # 状态/协议为行尾两个字段
        proto = parts[-1].lower()
        status = parts[-2].lower()
        if status not in ("up", "down") or proto not in ("up", "down"):
            continue

        iface = parts[0]
        entry = {"name": iface, "status": status, "protocol": proto}
        result["interfaces"].append(entry)
        result["total"] += 1

        if status == "down" or proto == "down":
            result["abnormal_interfaces"].append(iface)
            result["abnormal_count"] += 1

    return result


def parse_routing_table(output: str) -> dict[str, Any]:
    """解析 show ip route：统计路由条目数（排除 Codes/Gateway 说明行）"""
    result: dict[str, Any] = {"destinations": 0, "routes": 0, "has_default_route": False}

    route_count = 0
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("Codes", "Gateway", "N1", "E1", "i ")):
            continue
        if re.match(r"^[A-Z*]+\s+\S+", line):
            route_count += 1
            if re.match(r"^S\*?\s+0\.0\.0\.0/0", line):
                result["has_default_route"] = True

    result["routes"] = route_count
    result["destinations"] = route_count
    return result


def parse_logbuffer(output: str) -> dict[str, Any]:
    """解析 show logging

    样本格式（类 IOS syslog）：
      Jul 08 10:23:45.123: %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up
    严重级别在 %FACILITY-N-MNEMONIC 中：N <= 3 为告警。
    """
    result: dict[str, Any] = {"total_lines": 0, "error_count": 0, "errors": []}
    severity_pattern = re.compile(r"%\w+-(\d)-\w+")

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
    """解析 show running-config（类 IOS 配置风格）

      - hostname / line vty + login / transport input
      - snmp-server community / spanning-tree
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
        if stripped.startswith("no "):
            continue  # 显式关闭某功能:不能因为行里带功能名就算"已启用"

        if "telnet-server enable" in stripped or "telnet server enable" in stripped:
            telnet_enabled = True

        if "ssh-server enable" in stripped or "ssh server enable" in stripped:
            ssh_enabled = True

        m = re.search(r"snmp-server\s+community\s+(\S+)", line, re.IGNORECASE)
        if m:
            communities.append({"level": "read", "community": m.group(1)})

        if re.match(r"line\s+vty", stripped):
            in_vty = True
        elif in_vty:
            if stripped == "!" or stripped == "end" or re.match(r"(line|interface)\s+", stripped):
                in_vty = False
            else:
                if "login" in stripped:
                    has_auth = True
                if "transport input ssh" in stripped:
                    ssh_only = True
                if "transport input telnet" in stripped or "transport input all" in stripped:
                    telnet_enabled = True

        # STP(全局启用语句;"spanning-tree disable" 这类关闭语句不算)
        if re.match(r"spanning-tree\b", stripped) and "disable" not in stripped:
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
                "parsed": {"stp_enabled": stp_enabled},
            },
        ],
    }
