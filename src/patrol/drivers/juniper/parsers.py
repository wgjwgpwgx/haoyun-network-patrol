"""Juniper Junos 回显解析器

基于 Junos 17/20/21 系列标准输出格式编写,尚未在真机上验证
(标记:待真机验证)。无法解析的字段返回 None / 0 / [],不猜测。
"""
from __future__ import annotations

import re
from typing import Any


def parse_device_info(output: str) -> dict[str, Any]:
    """解析 show version

    标准格式:
      Hostname: sw1
      Model: ex4300-48t
      Junos: 21.4R3-S5.2
      JUNOS Base OS Software Suite [21.4R3-S5.2]
    """
    info: dict[str, Any] = {
        "model": "",
        "device_name": "",
        "software_version": "",
        "uptime": "",
        "serial_number": "",
    }
    for line in output.splitlines():
        m = re.search(r"^Hostname:\s*(\S+)", line)
        if m:
            info["device_name"] = m.group(1)
        m = re.search(r"^Model:\s*(\S+)", line)
        if m:
            info["model"] = m.group(1)
        m = re.search(r"^Junos:\s*(\S+)", line)
        if m:
            info["software_version"] = m.group(1)
    return info


def parse_cpu_usage(output: str) -> dict[str, Any]:
    """解析 show chassis routing-engine 的 CPU 部分

    标准格式:
      CPU utilization:
        User                        0 percent
        Background                  0 percent
        Kernel                      2 percent
        Interrupt                   0 percent
        Idle                       98 percent

    总利用率 = 100 - Idle。
    """
    result: dict[str, Any] = {
        "usage_percent": None,
        "user": None, "background": None,
        "kernel": None, "interrupt": None, "idle": None,
    }
    for line in output.splitlines():
        m = re.search(r"(User|Background|Kernel|Interrupt|Idle)\s+([\d.]+)\s+percent", line)
        if m:
            key = m.group(1).lower()
            result[key] = float(m.group(2))
    if result["idle"] is not None:
        result["usage_percent"] = int(round(100 - result["idle"]))
    return result


def parse_memory_usage(output: str) -> dict[str, Any]:
    """解析 show chassis routing-engine 的内存部分

    标准格式:
      Memory utilization           18 percent
    """
    result: dict[str, Any] = {"usage_percent": None}
    m = re.search(r"Memory utilization\s+(\d+)\s+percent", output)
    if m:
        result["usage_percent"] = int(m.group(1))
    return result


def parse_interface_status(output: str) -> dict[str, Any]:
    """解析 show interfaces terse

    标准格式:
      Interface               Admin Link Proto    Local                 Remote
      ge-0/0/0                up    up
      ge-0/0/1                up    down
      ge-0/0/2                down  down
      bme0                    up    up
    """
    result: dict[str, Any] = {
        "total": 0, "up_count": 0, "down_count": 0,
        "admin_down_count": 0, "abnormal_count": 0, "abnormal": [],
    }
    for line in output.splitlines():
        # 跳过表头与续行
        if not line.strip() or line.strip().startswith("Interface"):
            continue
        m = re.match(r"^(\S+)\s+(up|down)\s+(up|down)\b", line)
        if not m:
            continue
        name, admin, link = m.group(1), m.group(2), m.group(3)
        result["total"] += 1
        if admin == "down":
            result["admin_down_count"] += 1
        if link == "up":
            result["up_count"] += 1
        else:
            result["down_count"] += 1
        # 管理 Up 但链路 Down 视为异常
        if admin == "up" and link == "down":
            result["abnormal_count"] += 1
            result["abnormal"].append({"name": name, "admin": admin, "link": link})
    if result["total"] == 0:
        # 一行接口都没识别到(真机格式差异):不猜测为"无异常",
        # 置 None 让规则引擎判 UNKNOWN
        result["abnormal_count"] = None
    return result


def _parse_environment_class(output: str, klass: str) -> dict[str, Any]:
    """解析 show chassis environment 中指定类别(Fan/Power)的状态行。

    标准格式:
      Class Item                   Status     Measurement
      Power Power Supply 0         OK
      Fan  Fan Tray 0             OK         Spinning at 3920 RPM

    状态列后可能跟随测量值列,因此按状态关键字定位而非取行尾。
    """
    result: dict[str, Any] = {
        "total": 0, "abnormal_count": 0, "abnormal": [],
    }
    status_re = re.compile(r"\b(OK|Failed|Failure|Absent|Testing|Offline)\b")
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith(klass):
            continue
        m = status_re.search(stripped)
        if not m:
            continue
        result["total"] += 1
        if m.group(1) != "OK":
            result["abnormal_count"] += 1
            result["abnormal"].append(
                {"item": stripped[:m.start()].strip(), "status": m.group(1)})
    if result["total"] == 0:
        # 未识别到任何状态行(待真机验证驱动):置 None → 引擎判 UNKNOWN
        result["abnormal_count"] = None
    return result


def parse_fan_status(output: str) -> dict[str, Any]:
    return _parse_environment_class(output, "Fan")


def parse_power_status(output: str) -> dict[str, Any]:
    return _parse_environment_class(output, "Power")


def parse_system_alarms(output: str) -> dict[str, Any]:
    """解析 show system alarms

    标准格式:
      2 alarms currently active
      Alarm time               Class  Description
      2026-09-20 10:00:00 UTC  Minor  ...
      2026-09-21 09:00:00 UTC  Major  ...
    """
    result: dict[str, Any] = {
        "active_alarms": 0, "major_count": 0, "alarms": [],
    }
    count_m = re.search(r"(\d+)\s+alarms?\s+currently\s+active", output, re.IGNORECASE)
    if count_m:
        result["active_alarms"] = int(count_m.group(1))
    # "No alarms currently active" 同样是已识别的正常零告警
    no_alarm_m = re.search(r"no\s+alarms?\s+currently\s+active", output, re.IGNORECASE)
    for line in output.splitlines():
        m = re.search(r"\b(Critical|Major|Minor|Info)\b\s+(.+)$", line)
        if m:
            entry = {"class": m.group(1), "description": m.group(2).strip()}
            result["alarms"].append(entry)
            if m.group(1) in ("Critical", "Major"):
                result["major_count"] += 1
    recognized = bool(count_m or no_alarm_m or result["alarms"])
    if not recognized:
        # 概要行与明细行均未识别(真机格式差异):不猜测为零告警
        result["major_count"] = None
    elif result["active_alarms"] and not result["alarms"]:
        # 有告警总数但明细未解析出:级别分布无法确认
        result["major_count"] = None
    return result


def parse_config_services(output: str) -> dict[str, Any]:
    """解析 show configuration system services(嵌套检查结构)

    标准格式:
      ssh {
          protocol-version v2;
      }
      telnet;
      web-management {
          https {
              system-generated-certificate;
      }
    """
    telnet_enabled = bool(re.search(r"^telnet;", output, re.MULTILINE))
    ssh_enabled = bool(re.search(r"^ssh\s*\{", output, re.MULTILINE))
    web_mgmt = bool(re.search(r"^web-management\s*\{", output, re.MULTILINE))

    return {
        "checks": [
            {
                "name": "telnet_service",
                "category": "安全配置",
                "parsed": {
                    "telnet_enabled": telnet_enabled,
                    "ssh_enabled": ssh_enabled,
                    "web_management_enabled": web_mgmt,
                },
            },
        ],
    }
