"""从报告 JSON 重建 PatrolReport 对象

用于 Web 界面按需生成 Word/PDF、重新生成 HTML、触发 AI 分析等场景。
"""
from __future__ import annotations

from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceAsset,
    DeviceReport,
    PatrolReport,
)


def rebuild_report(data: dict) -> PatrolReport:
    """把报告 JSON(dict)还原为 PatrolReport 模型。"""
    report = PatrolReport(
        title=data.get("title", "巡检报告"),
        ai_analysis=data.get("ai_analysis"),
    )
    for dev_data in data.get("devices", []):
        asset = DeviceAsset(
            name=dev_data.get("name", ""),
            customer=dev_data.get("customer", ""),
            host=dev_data.get("host", ""),
            vendor=dev_data.get("vendor", ""),
            device_type=dev_data.get("device_type", ""),
        )
        device = DeviceReport(asset=asset)
        device.model = dev_data.get("model", "")
        device.software_version = dev_data.get("software_version", "")
        device.uptime = dev_data.get("uptime", "")
        for item_data in dev_data.get("check_items", []):
            device.check_items.append(CheckItem(
                name=item_data.get("name", ""),
                category=item_data.get("category", ""),
                command=item_data.get("command", ""),
                raw_output=item_data.get("raw_output", ""),
                status=CheckStatus(item_data.get("status", "UNKNOWN")),
                message=item_data.get("message", ""),
                details=item_data.get("details", {}),
            ))
        report.devices.append(device)
    return report
