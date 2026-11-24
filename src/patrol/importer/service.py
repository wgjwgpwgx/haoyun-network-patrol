"""导入服务:预览(识别结果)与按映射批量建档"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from patrol.importer.detect import (
    CONTENT_DETECTABLE,  # noqa: F401  (re-export 便于上层使用)
    REQUIRED_FIELDS,
    ColumnMatch,
    detect_columns,
)
from patrol.importer.readers import TableData, read_table

# 登录方式归一(中文/别名 → 内部值)
_LOGIN_METHODS = {
    "ssh": "ssh", "telnet": "telnet", "web": "web", "网页": "web",
    "网页采集": "web", "页面": "web", "api": "api", "接口": "api",
    "webapi": "api", "console": "console", "串口": "console",
}

# 厂商归一
_VENDORS = {
    "h3c": "h3c", "华三": "h3c", "新华三": "h3c", "h3c交换机": "h3c",
    "huawei": "huawei", "华为": "huawei",
    "ruijie": "ruijie", "锐捷": "ruijie",
    "sangfor": "sangfor", "深信服": "sangfor",
    "dptech": "dptech", "迪普": "dptech",
    "zte": "zte", "中兴": "zte",
    "maipu": "maipu", "迈普": "maipu",
}

# 各厂商默认设备类型:台账没填设备类型(或填的不是该厂商受支持的类型)时使用,
# 保证导入的设备一定能匹配到驱动——否则巡检时取不到驱动,整批任务失败
_DEFAULT_TYPES = {
    "h3c": "comware_switch", "huawei": "vrp_switch", "ruijie": "rgos_switch",
    "sangfor": "ngaf_firewall", "dptech": "fw_firewall",
    "zte": "zxr10_switch", "maipu": "mypower_switch",
}


def _normalize_type(vendor: str, device_type: str) -> tuple[str, str]:
    """厂商/设备类型归一到已注册的驱动;类型缺失或不属于该厂商时取厂商默认类型。"""
    import patrol.drivers  # noqa: F401 - 确保驱动已注册
    from patrol.drivers.registry import list_drivers

    registered = {tuple(key.split("/", 1)) for key in list_drivers()}
    if (vendor, device_type) in registered:
        return vendor, device_type
    if vendor in _DEFAULT_TYPES:
        return vendor, _DEFAULT_TYPES[vendor]
    return "h3c", _DEFAULT_TYPES["h3c"]


def preview_file(path: str | Path) -> dict[str, Any]:
    """读取+识别,返回预览所需全部信息(不写库)。

    返回:file/source/headers/row_count/rows(前 50 行)/
         mapping{字段: {column,header,confidence,reason}}/missing_required/low_confidence
    """
    table = read_table(path)
    matches = detect_columns(table.headers, table.rows)

    mapping: dict[str, dict[str, Any]] = {
        f"{m.field}": {
            "column": m.column, "header": m.header,
            "confidence": round(m.confidence, 2), "reason": m.reason,
        }
        for m in matches.values()
    }
    missing = [f for f in REQUIRED_FIELDS if f not in matches]
    low_conf = [f for f, m in mapping.items() if m["confidence"] < 0.8]

    return {
        "file": str(path),
        "source": table.source,
        "headers": table.headers,
        "row_count": len(table.rows),
        "rows": table.rows[:50],
        "mapping": mapping,
        "missing_required": missing,
        "low_confidence": low_conf,
    }


def import_rows(
    devices: Any,                # DeviceStore
    customers: Any,              # CustomerStore
    table: TableData,
    mapping: dict[str, int],
    default_customer: str = "",
    default_login_method: str = "ssh",
) -> dict[str, Any]:
    """按确认后的列映射批量建档。

    mapping: {字段: 列下标}(来自预览确认界面,允许用户手工修正)。
    返回 {created, skipped, errors:[{row, name, reason}]}。
    """
    from patrol.models import validate_host

    created = skipped = 0
    errors: list[dict[str, str]] = []

    for idx, row in enumerate(table.rows, start=1):
        def val(field: str) -> str:
            col = mapping.get(field)
            return (row[col].strip() if col is not None and col < len(row)
                    else "").strip()

        host = val("host")
        username = val("username")
        password = val("password")
        name = val("name") or host
        customer = val("customer") or default_customer

        # 行级校验:必填三要素
        if not (host and username and password):
            skipped += 1
            errors.append({"row": idx, "name": name,
                           "reason": "缺少必填项(地址/用户名/密码)"})
            continue
        try:
            validate_host(host)
        except ValueError as e:
            skipped += 1
            errors.append({"row": idx, "name": name, "reason": str(e)})
            continue
        # 单位存在性(填了才校验)
        if customer and customers.get(customer) is None:
            skipped += 1
            errors.append({"row": idx, "name": name,
                           "reason": f"归属客户不存在: {customer}"})
            continue

        login_raw = (val("login_method") or default_login_method).lower()
        login_method = _LOGIN_METHODS.get(login_raw, default_login_method)
        vendor_raw = val("vendor").lower()
        vendor = _VENDORS.get(vendor_raw, vendor_raw)
        vendor, device_type = _normalize_type(vendor, val("device_type"))
        port_val = val("port")
        port = int(port_val) if port_val.isdigit() and 1 <= int(port_val) <= 65535 \
            else (23 if login_method == "telnet" else 22 if login_method == "ssh" else 443)

        try:
            devices.create({
                "name": name, "customer": customer, "host": host,
                "vendor": vendor,
                "device_type": device_type,
                "login_method": login_method, "port": port,
                "username": username, "password": password,
                "super_password": val("super_password"),
                "remark": val("remark"), "enabled": True,
            })
            created += 1
        except ValueError as e:  # 重复设备名等
            skipped += 1
            errors.append({"row": idx, "name": name, "reason": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}
