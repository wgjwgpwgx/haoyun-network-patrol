"""深信服 NGAF Web 页面解析器

基于 NGAF Vue SPA 真实 DOM 选择器。
页面为 SPA 应用，数据通过 JavaScript 渲染。

DOM 选择器（基于用户确认的真实结构）：
  CPU：  .cpu-10s-rate .value / .cpu-1min-rate .value / .cpu-5min-rate .value
  内存： .memory-used-rate .value / .memory-total .value / .memory-used .value
  系统： .device-model .value / .firmware-version .value / .sn-code .value / .uptime .value
"""
from __future__ import annotations

import re
from typing import Any


# ── CSS 选择器定义 ──────────────────────────────────────────────

SELECTORS = {
    "device_info": {
        "model": ".device-model .value",
        "software_version": ".firmware-version .value",
        "serial_number": ".sn-code .value",
        "uptime": ".uptime .value",
    },
    "cpu_usage": {
        "usage_10s": ".cpu-10s-rate .value",
        "usage_1m": ".cpu-1min-rate .value",
        "usage_5m": ".cpu-5min-rate .value",
    },
    "memory_usage": {
        "usage_percent": ".memory-used-rate .value",
        "total_bytes": ".memory-total .value",
        "used_bytes": ".memory-used .value",
    },
}


def _extract_value_by_selector(html: str, selector: str) -> str | None:
    """从 HTML 中按 CSS 选择器提取值。

    简化实现：匹配 class 名对应的元素内容。
    真实场景应由 Selenium 的 find_element 处理，这里做文本回退。
    """
    # 将 CSS 选择器转为 class 匹配：.cpu-10s-rate .value → 在 class="cpu-10s-rate" 的元素内找 class="value"
    parts = selector.strip().split()
    if len(parts) == 2:
        parent_class = parts[0].lstrip(".")
        child_class = parts[1].lstrip(".")
        pattern = rf'class="[^"]*{re.escape(parent_class)}[^"]*"[^>]*>.*?class="[^"]*{re.escape(child_class)}[^"]*"[^>]*>([^<]+)<'
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # 单级选择器
    cls = selector.lstrip(".")
    pattern = rf'class="[^"]*{re.escape(cls)}[^"]*"[^>]*>([^<]+)<'
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None


def _parse_number(text: str | None) -> int | float | None:
    if text is None:
        return None
    m = re.search(r"([\d.]+)", text)
    if m:
        val = float(m.group(1))
        return int(val) if val == int(val) else val
    return None


def parse_device_info_web(html: str) -> dict[str, Any]:
    """解析系统概览页面。

    选择器：.device-model .value / .firmware-version .value / .sn-code .value / .uptime .value
    """
    sels = SELECTORS["device_info"]
    return {
        "model": _extract_value_by_selector(html, sels["model"]) or "",
        "software_version": _extract_value_by_selector(html, sels["software_version"]) or "",
        "serial_number": _extract_value_by_selector(html, sels["serial_number"]) or "",
        "uptime": _extract_value_by_selector(html, sels["uptime"]) or "",
    }


def parse_cpu_usage_web(html: str) -> dict[str, Any]:
    """解析 CPU 监控页面。

    选择器：.cpu-10s-rate .value / .cpu-1min-rate .value / .cpu-5min-rate .value
    """
    sels = SELECTORS["cpu_usage"]
    usage_10s = _parse_number(_extract_value_by_selector(html, sels["usage_10s"]))
    return {
        "usage_percent": round(float(usage_10s)) if usage_10s is not None else None,
        "usage_10s": float(usage_10s) if usage_10s is not None else None,
        "usage_1m": _parse_number(_extract_value_by_selector(html, sels["usage_1m"])),
        "usage_5m": _parse_number(_extract_value_by_selector(html, sels["usage_5m"])),
    }


def parse_memory_usage_web(html: str) -> dict[str, Any]:
    """解析内存监控页面。

    选择器：.memory-used-rate .value / .memory-total .value / .memory-used .value
    """
    sels = SELECTORS["memory_usage"]
    usage = _parse_number(_extract_value_by_selector(html, sels["usage_percent"]))
    return {
        "usage_percent": round(float(usage)) if usage is not None else None,
        "total_bytes": _parse_number(_extract_value_by_selector(html, sels["total_bytes"])),
        "used_bytes": _parse_number(_extract_value_by_selector(html, sels["used_bytes"])),
    }


def parse_interface_status_web(html: str) -> dict[str, Any]:
    """解析接口监控页面。

    TODO: 需要确认接口列表的 DOM 结构。
    """
    result: dict[str, Any] = {
        "interfaces": [],
        "abnormal_interfaces": [],
        "abnormal_count": 0,
        "total": 0,
    }

    # 通用匹配：接口名 + 状态
    for line in html.splitlines():
        line = line.strip()
        m = re.match(r"(\S+)\s+(up|down|online|offline)", line, re.IGNORECASE)
        if m:
            name = m.group(1)
            status = m.group(2).lower()
            result["interfaces"].append({"name": name, "status": status})
            result["total"] += 1
            if status in ("down", "offline"):
                result["abnormal_interfaces"].append(name)
                result["abnormal_count"] += 1

    return result
