"""中兴 ZXR10 交换机回显解析器

依据 ZXR10 官方手册格式构造样本编写,解析采用多格式宽容匹配;
**尚未经真机回显验证**,现场遇格式不符按 UNKNOWN 流程保留原始回显反馈适配。
无法解析的字段返回 None / 0 / [] / False，不猜测。
"""
from __future__ import annotations

import re
from typing import Any


def parse_device_info(output: str) -> dict[str, Any]:
    """解析 show version

    样本格式：
      ZTE ZXR10 5250 Series Software, Version V3.1.0
      Copyright (c) 2001-2026 ZTE Corporation.
      ZXR10 5250-28PS-E uptime is 12 weeks, 3 days, 4 hours, 56 minutes
      Serial Number : ZTE05G10249
    """
    info: dict[str, Any] = {
        "model": "",
        "device_name": "",
        "software_version": "",
        "uptime": "",
        "serial_number": "",
    }

    for line in output.splitlines():
        # 软件版本：Version V3.1.0
        m = re.search(r"Version\s+(\S+)", line)
        if m and not info["software_version"]:
            info["software_version"] = m.group(1)

        # 型号：优先 uptime 行 "ZXR10 5250-28PS-E uptime"，其次 "ZXR10 5250 Series"
        m = re.search(r"ZXR10\s+(\S+)\s+uptime", line)
        if m:
            info["model"] = m.group(1)
        elif not info["model"]:
            m = re.search(r"ZXR10\s+(\S+)\s+Series", line)
            if m:
                info["model"] = m.group(1)

        # 运行时间
        m = re.search(r"uptime\s+is\s+(.+)", line)
        if m:
            info["uptime"] = m.group(1).strip().rstrip(",")

        # 序列号（部分型号在 show version 中输出）
        m = re.search(r"Serial\s*[Nn]umber\s*:?\s*(\S+)", line)
        if m:
            info["serial_number"] = m.group(1)

    return info


def parse_cpu_usage(output: str) -> dict[str, Any]:
    """解析 show cpu

    样本格式：
      CPU utilization in 5 seconds: 8.3%
      CPU utilization in 1 minute : 7.9%
      CPU utilization in 5 minutes: 7.5%
    """
    result: dict[str, Any] = {
        "usage_percent": None,
        "usage_5s": None,
        "usage_1m": None,
        "usage_5m": None,
    }

    for line in output.splitlines():
        m = re.search(r"(?:five|5)\s*seconds?\s*:?\s*([\d.]+)%", line)
        if m:
            result["usage_5s"] = float(m.group(1))

        m = re.search(r"(?:one|1)\s*minute\s*:?\s*([\d.]+)%", line)
        if m:
            result["usage_1m"] = float(m.group(1))

        m = re.search(r"(?:five|5)\s*minutes?\s*:?\s*([\d.]+)%", line)
        if m:
            result["usage_5m"] = float(m.group(1))

    if result["usage_5s"] is not None:
        result["usage_percent"] = round(result["usage_5s"])

    return result


def parse_memory_usage(output: str) -> dict[str, Any]:
    """解析 show memory

    样本格式：
      System Total Memory(bytes): 1073741824
      Total Used Memory(bytes): 279134208
      Memory Used Rate: 26%
    """
    result: dict[str, Any] = {"total_bytes": None, "used_bytes": None, "usage_percent": None}

    for line in output.splitlines():
        m = re.search(r"Total Memory\(bytes\)\s*:?\s*(\d+)", line)
        if m:
            result["total_bytes"] = int(m.group(1))

        m = re.search(r"Used Memory\(bytes\)\s*:?\s*(\d+)", line)
        if m:
            result["used_bytes"] = int(m.group(1))

        m = re.search(r"(?:Memory\s+)?Used\s+Rate\s*:?\s*(\d+)%", line)
        if m:
            result["usage_percent"] = int(m.group(1))

    # 无百分比但有总量/用量时兜底计算
    if result["usage_percent"] is None and result["total_bytes"] and result["used_bytes"]:
        result["usage_percent"] = round(result["used_bytes"] * 100 / result["total_bytes"])

    return result


def parse_interface_status(output: str) -> dict[str, Any]:
    """解析 show ip interface brief

    样本格式：
      Interface         IP-Address      Mask          Admin  Phy   Prot
      gei-1/1/1         10.1.1.1        255.255.255.0 up     up    up
      vlan10            192.168.10.1    255.255.255.0 up     up    up
      gei-1/1/24        unassigned      --            up     down  down

    状态列在行尾（Admin/Phy/Prot 二或三列），任一 down 记异常。
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
        if len(parts) < 3:
            continue

        # 接口名 = 行首第一个字段（gei-1/1/1 / vlan10 等无空格）
        iface = parts[0]
        if not iface:
            continue

        # 行尾的 up/down 状态列（1~3 列）
        states = [p.lower() for p in parts[1:] if p.lower() in ("up", "down")]
        if not states:
            continue

        status = states[0]
        entry = {"name": iface, "status": status, "protocol": states[-1]}
        result["interfaces"].append(entry)
        result["total"] += 1

        if "down" in states:
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
        # 路由行：协议字母前缀（C/S/O/R/B/*）+ 目的网络
        if re.match(r"^[A-Z*]+\s+\S+", line):
            route_count += 1
            if re.match(r"^S\*?\s+0\.0\.0\.0/0", line):
                result["has_default_route"] = True

    result["routes"] = route_count
    result["destinations"] = route_count
    return result


def parse_logbuffer(output: str) -> dict[str, Any]:
    """解析 show logging

    样本格式（ZXR10 syslog，华为系 %%模块/级别/助记）：
      Jul 12 2026 10:23:45 sw-acc %%01IFNET/4/LINK_STATE(l): ...
    严重级别为斜杠间的数字(0-7,0 最严重)：N <= 3 为告警。
    注意区别于锐捷 %%N-XXX(级别紧跟 %%)。
    """
    result: dict[str, Any] = {"total_lines": 0, "error_count": 0, "errors": []}
    severity_pattern = re.compile(r"%%\d+\w*/(\d+)/")

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

    ZXR10 配置风格（宽容匹配多种官方格式）：
      - hostname sw-access
      - snmp community / snmp-server community / set snmp community
      - line vty + login
      - spanning-tree enable / stp enable
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

        # Telnet:配置中出现启用语句才算启用(ZXR10 部分版本默认开启 Telnet,
        # 配置中不显示该行——此情形待真机确认)
        if "telnet-server enable" in stripped or "telnet server enable" in stripped:
            telnet_enabled = True
        if "user-interface vty" in stripped and "protocol" in stripped and "telnet" in stripped:
            telnet_enabled = True

        # SSH
        if "ssh-server enable" in stripped or "ssh server enable" in stripped:
            ssh_enabled = True

        # SNMP 团体字:兼容 "community <值> [ro|rw]" 与 "community [read|write] <值>" 两种语序。
        # 读写属性必须显式列举,不能用贪婪的 \w+ 去吞,否则会把属性词当成团体字
        m = re.search(r"(?:set\s+)?snmp(?:-server|-agent)?\s+community"
                      r"(?:\s+(?:read|write|ro|rw))?\s+(\S+)",
                      line, re.IGNORECASE)
        if m:
            communities.append({"level": "read", "community": m.group(1)})

        # VTY 认证
        if re.match(r"line\s+vty", stripped):
            in_vty = True
        elif in_vty:
            if stripped == "!" or stripped == "end" or re.match(r"(line|interface)\s+", stripped):
                in_vty = False
            else:
                if "login" in stripped:
                    has_auth = True
                if "protocol input ssh" in stripped or "transport input ssh" in stripped:
                    ssh_only = True
                if ("protocol input telnet" in stripped
                        or "transport input telnet" in stripped
                        or "protocol input all" in stripped):
                    telnet_enabled = True

        # STP(全局启用语句;"spanning-tree disable" 这类关闭语句不算)
        if re.match(r"(?:spanning-tree|stp)\b", stripped) and "disable" not in stripped:
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
