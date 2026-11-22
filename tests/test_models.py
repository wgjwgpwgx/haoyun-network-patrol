"""统一数据模型测试"""
from __future__ import annotations

from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceAsset,
    DeviceReport,
    PatrolReport,
)


class TestDeviceAsset:
    def test_default_values(self):
        asset = DeviceAsset(name="sw1", host="10.0.0.1")
        assert asset.vendor == "h3c"
        assert asset.device_type == "comware_switch"
        assert asset.port == 22
        assert asset.enabled is True
        assert asset.timeout == 30
        assert asset.command_timeout == 60

    def test_custom_values(self):
        asset = DeviceAsset(
            name="核心交换机",
            host="192.168.1.1",
            vendor="h3c",
            device_type="comware_switch",
            port=2222,
            username="admin",
            password="secret",
            enabled=False,
        )
        assert asset.name == "核心交换机"
        assert asset.port == 2222
        assert asset.enabled is False


class TestCheckItem:
    def test_create_check_item(self):
        item = CheckItem(
            name="cpu_usage",
            category="CPU",
            command="display cpu-usage",
            raw_output="12%",
            status=CheckStatus.PASS,
            message="CPU 利用率 12%",
        )
        assert item.status == CheckStatus.PASS
        assert item.details == {}


class TestDeviceReport:
    def test_summary_counts(self, sample_asset):
        report = DeviceReport(asset=sample_asset)
        report.check_items = [
            CheckItem(
                name="a", category="A", command="c1", raw_output="o1",
                status=CheckStatus.PASS, message="ok",
            ),
            CheckItem(
                name="b", category="B", command="c2", raw_output="o2",
                status=CheckStatus.FAIL, message="bad",
            ),
            CheckItem(
                name="c", category="C", command="c3", raw_output="o3",
                status=CheckStatus.UNKNOWN, message="?",
            ),
        ]
        assert report.pass_count == 1
        assert report.fail_count == 1
        assert report.unknown_count == 1
        assert "PASS: 1, FAIL: 1, UNKNOWN: 1" in report.summary

    def test_empty_report(self, sample_asset):
        report = DeviceReport(asset=sample_asset)
        assert report.pass_count == 0
        assert report.fail_count == 0


class TestPatrolReport:
    def test_has_failures(self, sample_asset):
        report = PatrolReport()
        device = DeviceReport(asset=sample_asset)
        device.check_items = [
            CheckItem(
                name="a", category="A", command="c", raw_output="o",
                status=CheckStatus.FAIL, message="fail",
            ),
        ]
        report.devices.append(device)
        assert report.has_failures is True

    def test_no_failures(self, sample_asset):
        report = PatrolReport()
        device = DeviceReport(asset=sample_asset)
        device.check_items = [
            CheckItem(
                name="a", category="A", command="c", raw_output="o",
                status=CheckStatus.PASS, message="ok",
            ),
        ]
        report.devices.append(device)
        assert report.has_failures is False
