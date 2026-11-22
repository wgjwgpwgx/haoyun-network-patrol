"""Cisco IOS 回显解析器

基于 IOS 15.x 标准输出格式编写,尚未在真机上验证(标记:待真机验证)。
无法解析的字段返回 None / 0 / [],不猜测。
"""
from __future__ import annotations

import re
from typing import Any


def parse_device_info(output: str) -> dict[str, Any]:
    """解析 show version

    标准格式:
      Cisco IOS Software, C2960S Software (C2960S-UNIVERSALK9-M), Version 15.2(2)E9, ...
      cisco WS-C2960S-48TS-L (PowerPC405) processor (revision R0) ...
      WS-C2960S-48TS-L uptime is 30 weeks, 2 days, 3 hours, 55 minutes
      System serial number            : FDO1234ABCD
    """
    info: dict[str, Any] = {
        "model": "", "device_name": "", "software_version": "",
        "uptime": "", "serial_number": "",
    }
    for line in output.splitlines():
        m = re.search(r"Version\s+([\d()A-Za-z.]+)", line)
        if m and "Cisco IOS Software" in line and not info["software_version"]:
            info["software_version"] = m.group(1)
        # cisco WS-C2960S-48TS-L (PowerPC405) processor
        m = re.search(r"cisco\s+(\S+)\s+.*processor", line, re.IGNORECASE)
        if m and not info["model"]:
            info["model"] = m.group(1)
        m = re.search(r"uptime is\s+(.+?)\s*$", line, re.IGNORECASE)
        if m and not info["uptime"]:
            info["uptime"] = m.group(1).strip()
        m = re.search(r"System serial number\s*:\s*(\S+)", line, re.IGNORECASE)
        if m:
            info["serial_number"] = m.group(1)
    return info


def parse_cpu_usage(output: str) -> dict[str, Any]:
    """解析 show processes cpu 首行

    标准格式:
      CPU utilization for five seconds: 8%/0%; one minute: 5%; five minutes: 4%
    """
    result: dict[str, Any] = {
        "usage_percent": None, "usage_5s": None,
        "usage_1m": None, "usage_5m": None,
    }
    m = re.search(
        r"five seconds:\s*(?P<s5>[\d.]+)%(/\d+%)?;\s*"
        r"one minute:\s*(?P<m1>[\d.]+)%;\s*five minutes:\s*(?P<m5>[\d.]+)%",
        output,
    )
    if m:
        result["usage_5s"] = float(m.group("s5"))
        result["usage_1m"] = float(m.group("m1"))
        result["usage_5m"] = float(m.group("m5"))
        result["usage_percent"] = int(float(m.group("s5")))
    return result


def parse_memory_usage(output: str) -> dict[str, Any]:
    """解析 show memory statistics

    标准格式:
                  Head    Total(b)     Used(b)     Free(b)
      Processor  0x...    62197760     25127720    37070040
      I/O        0x...    12582912     1887656     10695256
    """
    result: dict[str, Any] = {
        "total_bytes": None, "used_bytes": None, "usage_percent": None,
    }
    for line in output.splitlines():
        m = re.match(r"^Processor\s+\S+\s+(\d+)\s+(\d+)\s+(\d+)", line)
        if m:
            total, used = int(m.group(1)), int(m.group(2))
            result["total_bytes"] = total
            result["used_bytes"] = used
            if total:
                result["usage_percent"] = round(used * 100 / total)
            break
    return result


def parse_interface_status(output: str) -> dict[str, Any]:
    """解析 show ip interface brief

    标准格式:
      Interface              IP-Address      OK? Method Status                Protocol
      GigabitEthernet0/1     unassigned      YES NVRAM  up                    up
      GigabitEthernet0/2     unassigned      YES unset   administratively down down
      Vlan10                 10.1.1.1        YES NVRAM  up                    down
    """
    result: dict[str, Any] = {
        "total": 0, "up_count": 0, "down_count": 0,
        "admin_down_count": 0, "abnormal_count": 0, "abnormal": [],
    }
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Interface"):
            continue
        # 行尾两列为 Status 与 Protocol;Status 可能是 "administratively down"
        m = re.match(
            r"^(\S+).*?\s+(administratively down|up|down)\s+(up|down)\s*$", stripped)
        if not m:
            continue
        name, status, proto = m.group(1), m.group(2), m.group(3)
        result["total"] += 1
        if status.startswith("administratively"):
            result["admin_down_count"] += 1
            continue
        if status == "up" and proto == "up":
            result["up_count"] += 1
        else:
            result["down_count"] += 1
            # 管理已启用但协议未通的接口视为异常
            if status == "up":
                result["abnormal_count"] += 1
                result["abnormal"].append(
                    {"name": name, "status": status, "protocol": proto})
    if result["total"] == 0:
        # 一行接口都没识别到(待真机验证驱动):置 None → 引擎判 UNKNOWN
        result["abnormal_count"] = None
    return result


def _parse_env_status(output: str, section_keywords: tuple[str, ...]) -> dict[str, Any]:
    """解析 show env all 中指定段落(风扇/电源)的 Status 值。

    标准格式(不同平台略有差异):
      Fan Status:
        Fan 1
          Fan Type: Fan-1
          Status:  OK
      POWER SUPPLIES:
        Power Supply 1
          Status:  OK
    """
    result: dict[str, Any] = {"total": 0, "abnormal_count": 0, "abnormal": []}
    in_section = False
    current_item = ""
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 段落标题:以冒号结尾且不含状态赋值(如 "Fan Status:" / "POWER SUPPLIES:")
        if stripped.endswith(":"):
            in_section = any(kw in stripped for kw in section_keywords)
            current_item = ""
            continue
        m = re.match(r"^(Fan|Power Supply|PS)\s*(\d+)$", stripped, re.IGNORECASE)
        if m:
            current_item = stripped
            continue
        m = re.match(r"^Status\s*:\s*(\S+)", stripped, re.IGNORECASE)
        if m and in_section and current_item:
            result["total"] += 1
            status = m.group(1)
            if status.upper() not in ("OK", "NORMAL", "GOOD", "ON"):
                result["abnormal_count"] += 1
                result["abnormal"].append({"item": current_item, "status": status})
            current_item = ""
    if result["total"] == 0:
        # show env all 各平台格式差异大,未识别到状态项时不猜测为零异常
        result["abnormal_count"] = None
    return result


def parse_fan_status(output: str) -> dict[str, Any]:
    return _parse_env_status(output, ("FAN", "Fan"))


def parse_power_status(output: str) -> dict[str, Any]:
    return _parse_env_status(output, ("POWER", "Power"))


def parse_logbuffer(output: str) -> dict[str, Any]:
    """解析 show logging,统计 severity<=3 的日志条数。

    标准格式:
      *Sep 20 10:00:00.123: %LINK-3-UPDOWN: Interface GigabitEthernet0/2, ...
    """
    result: dict[str, Any] = {"error_count": 0, "entries": []}
    total_syslog = 0
    for m in re.finditer(r"%\w+-(\d)-\w+", output):
        total_syslog += 1
        severity = int(m.group(1))
        if severity <= 3:
            result["error_count"] += 1
            result["entries"].append(m.group(0))
    if total_syslog == 0 and not re.search(
            r"Syslog logging|Log Buffer|Console logging|logging host",
            output, re.IGNORECASE):
        # 既无 syslog 条目也无 show logging 特征行:格式未识别,不猜测为零告警
        result["error_count"] = None
    return result


def parse_config_cur(output: str) -> dict[str, Any]:
    """解析 show running-config 的安全相关配置(嵌套检查结构)。"""
    # transport input telnet / all 表示允许 Telnet
    telnet_enabled = bool(re.search(
        r"transport input (telnet|all)", output, re.IGNORECASE))
    ssh_enabled = bool(re.search(
        r"transport input (ssh|all)", output, re.IGNORECASE))
    # SNMP 默认团体字
    dangerous = re.findall(
        r"snmp-server community (public|private)", output, re.IGNORECASE)
    # AAA 认证
    has_aaa = bool(re.search(r"^aaa new-model", output, re.MULTILINE))
    # 生成树
    stp_enabled = bool(re.search(r"^spanning-tree mode ", output, re.MULTILINE))

    return {
        "checks": [
            {
                "name": "telnet_service",
                "category": "安全配置",
                "parsed": {"telnet_enabled": telnet_enabled, "ssh_enabled": ssh_enabled},
            },
            {
                "name": "snmp_community",
                "category": "安全配置",
                "parsed": {
                    "communities": dangerous,
                    "community_count": len(dangerous),
                    "has_dangerous": bool(dangerous),
                },
            },
            {
                "name": "vty_auth",
                "category": "安全配置",
                "parsed": {"has_authentication": has_aaa},
            },
            {
                "name": "stp_status",
                "category": "安全配置",
                "parsed": {"stp_enabled": stp_enabled},
            },
        ],
    }
