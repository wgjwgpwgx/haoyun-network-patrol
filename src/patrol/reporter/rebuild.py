"""从报告 JSON 重建 PatrolReport 对象

用于 Web 界面按需生成 Word/PDF、重新生成 HTML、触发 AI 分析等场景。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceAsset,
    DeviceReport,
    PatrolReport,
)


def _time(value: Any) -> datetime | None:
    """ISO 时间字符串转 datetime;缺失或格式不对返回 None。"""
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def rebuild_report(data: dict) -> PatrolReport:
    """把报告 JSON(dict)还原为 PatrolReport 模型。

    巡检时刻与采集异常必须原样还原:导出的 Word/Excel 里"巡检时间""上期问题
    复查""配置变更对比"都以报告生成时间为基准,丢失后会把导出时刻当成巡检
    时刻、把本期失败项当成上期问题;采集异常丢失后,没连上的设备会显示成
    "没有任何检查项的正常设备"。
    """
    report = PatrolReport(
        title=data.get("title", "巡检报告"),
        ai_analysis=data.get("ai_analysis"),
        generated_at=_time(data.get("generated_at")) or datetime.now(),
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
        device.serial_number = dev_data.get("serial_number", "")
        device.collected_at = (_time(dev_data.get("collected_at"))
                               or device.collected_at)
        device.error = dev_data.get("error") or None
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
