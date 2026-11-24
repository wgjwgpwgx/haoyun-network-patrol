"""从报告 JSON 重建报告对象:巡检时刻、采集异常、序列号必须原样还原"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport
from patrol.reporter.html import HTMLReporter
from patrol.reporter.rebuild import rebuild_report


def _roundtrip(tmp_path: Path, report: PatrolReport) -> PatrolReport:
    """生成报告 → 读伴生 JSON → 重建(即界面导出 Word/Excel 的实际路径)。"""
    html_path = tmp_path / "r.html"
    HTMLReporter().generate(report, html_path)
    data = json.loads(html_path.with_suffix(".json").read_text(encoding="utf-8"))
    return rebuild_report(data)


def test_times_error_and_serial_survive_roundtrip(tmp_path):
    asset = DeviceAsset(name="核心交换", host="192.0.2.1", vendor="h3c",
                        device_type="comware_switch")
    device = DeviceReport(
        asset=asset, serial_number="210235A1B2C3",
        collected_at=datetime(2026, 11, 1, 9, 59, 0), error="连接超时")
    report = PatrolReport(title="巡检报告", devices=[device],
                          generated_at=datetime(2026, 11, 1, 10, 0, 0))

    rebuilt = _roundtrip(tmp_path, report)

    assert rebuilt.generated_at == datetime(2026, 11, 1, 10, 0, 0)
    got = rebuilt.devices[0]
    assert got.collected_at == datetime(2026, 11, 1, 9, 59, 0)
    assert got.error == "连接超时", "采集异常丢失后,没连上的设备会被当成正常设备"
    assert got.serial_number == "210235A1B2C3"


def test_check_items_survive_roundtrip(tmp_path):
    device = DeviceReport(
        asset=DeviceAsset(name="sw", host="192.0.2.2", vendor="h3c",
                          device_type="comware_switch"))
    device.check_items.append(CheckItem(
        name="cpu_usage", category="CPU", command="display cpu-usage",
        raw_output="12%", status=CheckStatus.FAIL, message="high",
        details={"usage_percent": 95, "severity": "critical"}))
    rebuilt = _roundtrip(tmp_path, PatrolReport(devices=[device]))

    item = rebuilt.devices[0].check_items[0]
    assert item.status == CheckStatus.FAIL and item.details["usage_percent"] == 95


def test_missing_or_broken_times_do_not_crash():
    rebuilt = rebuild_report({"generated_at": "not-a-time", "devices": [
        {"name": "x", "host": "h", "vendor": "h3c", "device_type": "comware_switch",
         "collected_at": "garbage", "error": "", "check_items": []}]})
    assert rebuilt.devices[0].error is None
    assert isinstance(rebuilt.generated_at, datetime)
    assert isinstance(rebuilt.devices[0].collected_at, datetime)
