"""深信服 NGAF API 响应解析器

基于 NGAF v8.0.35+ WebAPI 真实响应格式。
统一外层结构：{"code": int, "msg": "string", "data": ...}
"""
from __future__ import annotations

import json
from typing import Any


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_data(raw: str) -> dict[str, Any]:
    """提取 data 字段。"""
    resp = _safe_json(raw)
    return resp.get("data", resp)


def parse_device_info_api(raw: str) -> dict[str, Any]:
    """解析 /system/device-info

    响应字段：device_model, firmware_version, sn, uptime, cpu_model, total_memory, ha_status
    """
    d = _get_data(raw)
    return {
        "model": d.get("device_model", ""),
        "software_version": d.get("firmware_version", ""),
        "serial_number": d.get("sn", ""),
        "uptime": d.get("uptime", ""),
        "cpu_model": d.get("cpu_model", ""),
        "total_memory": d.get("total_memory", None),
        "ha_status": d.get("ha_status", ""),
    }


def parse_cpu_usage_api(raw: str) -> dict[str, Any]:
    """解析 /monitor/cpu

    响应字段：cpu_10s, cpu_1min, cpu_5min, cpu_max
    """
    d = _get_data(raw)
    usage_10s = d.get("cpu_10s")
    return {
        "usage_percent": round(float(usage_10s)) if usage_10s is not None else None,
        "usage_10s": float(usage_10s) if usage_10s is not None else None,
        "usage_1m": float(d.get("cpu_1min", 0)) if d.get("cpu_1min") is not None else None,
        "usage_5m": float(d.get("cpu_5min", 0)) if d.get("cpu_5min") is not None else None,
        "max_usage": float(d.get("cpu_max", 0)) if d.get("cpu_max") is not None else None,
    }


def parse_memory_usage_api(raw: str) -> dict[str, Any]:
    """解析 /monitor/memory

    响应字段：total, used, free, usage_rate
    """
    d = _get_data(raw)
    usage_rate = d.get("usage_rate")
    return {
        "usage_percent": round(float(usage_rate)) if usage_rate is not None else None,
        "total_bytes": d.get("total"),
        "used_bytes": d.get("used"),
        "free_bytes": d.get("free"),
    }


def parse_interface_status_api(raw: str) -> dict[str, Any]:
    """解析 /monitor/interface

    响应字段：接口数组，每项含 if_name, ip_addr, phy_status, proto_status, in_bps, out_bps, in_error, out_error
    """
    d = _get_data(raw)
    ifaces = d if isinstance(d, list) else d.get("interfaces", d.get("list", []))
    if not isinstance(ifaces, list):
        ifaces = []

    result: dict[str, Any] = {
        "interfaces": [],
        "abnormal_interfaces": [],
        "abnormal_count": 0,
        "total": len(ifaces),
    }

    for iface in ifaces:
        name = iface.get("if_name", "")
        phy = iface.get("phy_status", "").lower()
        proto = iface.get("proto_status", "").lower()
        in_err = iface.get("in_error", 0)
        out_err = iface.get("out_error", 0)

        entry = {
            "name": name,
            "phy_status": phy,
            "proto_status": proto,
            "ip_address": iface.get("ip_addr", ""),
            "in_bps": iface.get("in_bps", 0),
            "out_bps": iface.get("out_bps", 0),
            "in_errors": int(in_err) if in_err else 0,
            "out_errors": int(out_err) if out_err else 0,
        }
        result["interfaces"].append(entry)

        if phy in ("down", "offline", "disabled") or proto in ("down", "offline"):
            result["abnormal_interfaces"].append(name)
            result["abnormal_count"] += 1

    return result


def parse_routing_table_api(raw: str) -> dict[str, Any]:
    """解析 /system/routes"""
    d = _get_data(raw)
    routes = d if isinstance(d, list) else d.get("routes", d.get("list", []))
    if not isinstance(routes, list):
        routes = []
    return {"destinations": len(routes), "routes": len(routes)}


def parse_logbuffer_api(raw: str) -> dict[str, Any]:
    """解析 /log/system?reverse=true"""
    d = _get_data(raw)
    logs = d if isinstance(d, list) else d.get("logs", d.get("list", []))
    if not isinstance(logs, list):
        logs = []

    errors = []
    for log in logs:
        level = str(log.get("level", "")).lower()
        if level in ("critical", "error", "emergency", "alert"):
            errors.append(str(log.get("message", log.get("msg", ""))))

    return {"total_lines": len(logs), "error_count": len(errors), "errors": errors[:20]}
