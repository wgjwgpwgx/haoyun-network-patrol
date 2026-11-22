"""迪普 DPtech 防火墙 HTML 页面解析器

基于真实页面结构：
  <table class="info-table">
    <tr><td>设备型号</td><td>FW2000-GA</td></tr>
    <tr><td>序列号</td><td>DP123456</td></tr>
  </table>

每行 <tr> 包含 2 个 <td>：
  td[0] = 字段名称
  td[1] = 字段值
"""
from __future__ import annotations

import re
from typing import Any

# 字段名到统一 key 的映射
_FIELD_MAP: dict[str, str] = {
    "设备型号": "model",
    "型号": "model",
    "设备名称": "device_name",
    "主机名": "device_name",
    "主机名称": "device_name",
    "软件版本": "software_version",
    "固件版本": "software_version",
    "版本": "software_version",
    "序列号": "serial_number",
    "SN": "serial_number",
    "运行时间": "uptime",
    "系统运行时间": "uptime",
}


def _extract_table_rows(html: str) -> list[tuple[str, str]]:
    """从 HTML 中提取 info-table 的所有行。

    匹配 <table class="info-table"> 内的 <tr><td>...</td><td>...</td></tr>
    """
    rows: list[tuple[str, str]] = []

    # 提取 info-table 内容
    table_match = re.search(
        r'<table[^>]*class="[^"]*info-table[^"]*"[^>]*>(.*?)</table>',
        html, re.DOTALL | re.IGNORECASE,
    )
    table_content = table_match.group(1) if table_match else html

    # 提取每行的两个 <td>
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_content, re.DOTALL | re.IGNORECASE):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr_match.group(1), re.DOTALL | re.IGNORECASE)
        if len(tds) >= 2:
            label = re.sub(r"<[^>]+>", "", tds[0]).strip()
            value = re.sub(r"<[^>]+>", "", tds[1]).strip()
            rows.append((label, value))

    return rows


def parse_device_info(text: str) -> dict[str, Any]:
    """解析系统信息页面。

    <table class="info-table"> 中的标签-值对。
    """
    info: dict[str, Any] = {
        "model": "",
        "device_name": "",
        "software_version": "",
        "serial_number": "",
        "uptime": "",
    }

    for label, value in _extract_table_rows(text):
        key = _FIELD_MAP.get(label)
        if key and value:
            info[key] = value

    return info


def parse_cpu_usage(text: str) -> dict[str, Any]:
    """解析 CPU 监控页面。

    TODO: 需要确认 CPU 页面的 HTML 结构。
    当前使用通用百分比匹配。
    """
    result: dict[str, Any] = {"usage_percent": None}

    # 匹配 info-table 中的百分比
    for label, value in _extract_table_rows(text):
        if re.search(r"(CPU|cpu|利用率|使用率)", label):
            m = re.search(r"(\d+(?:\.\d+)?)", value)
            if m:
                result["usage_percent"] = round(float(m.group(1)))
                break

    # 回退：通用百分比匹配
    if result["usage_percent"] is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if m:
            result["usage_percent"] = round(float(m.group(1)))

    return result


def parse_memory_usage(text: str) -> dict[str, Any]:
    """解析内存监控页面。

    TODO: 需要确认内存页面的 HTML 结构。
    """
    result: dict[str, Any] = {"usage_percent": None, "total_bytes": None, "used_bytes": None}

    for label, value in _extract_table_rows(text):
        if re.search(r"(内存使用率|内存利用率|内存|Memory).*(率|%)", label):
            m = re.search(r"(\d+(?:\.\d+)?)", value)
            if m:
                result["usage_percent"] = round(float(m.group(1)))
        elif re.search(r"(总内存|Total\s*Memory)", label, re.IGNORECASE):
            m = re.search(r"(\d+)", value)
            if m:
                result["total_bytes"] = int(m.group(1))
        elif re.search(r"(已用内存|已用|Used\s*Memory)", label, re.IGNORECASE):
            m = re.search(r"(\d+)", value)
            if m:
                result["used_bytes"] = int(m.group(1))

    if result["usage_percent"] is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if m:
            result["usage_percent"] = round(float(m.group(1)))

    return result


def parse_interface_status(text: str) -> dict[str, Any]:
    """解析接口状态页面。

    TODO: 需要确认接口页面的 HTML 表格结构。
    当前使用 info-table 行匹配。
    """
    result: dict[str, Any] = {
        "interfaces": [],
        "abnormal_interfaces": [],
        "abnormal_count": 0,
        "total": 0,
    }

    # 从 info-table 中提取接口信息
    for label, value in _extract_table_rows(text):
        if re.match(r"(eth|ge|fe|wan|lan|port|vlan|mgt|GigabitEthernet)", label, re.IGNORECASE):
            status = value.lower().strip()
            result["interfaces"].append({"name": label, "status": status})
            result["total"] += 1
            if status in ("down", "offline", "disabled"):
                result["abnormal_interfaces"].append(label)
                result["abnormal_count"] += 1

    return result
