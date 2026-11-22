"""集成测试 - 场景 2：多厂商混合巡检

同时巡检华为、锐捷设备，验证数据格式统一。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from patrol.analyzer.engine import RuleEngine
from patrol.cli import run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.drivers.ruijie.driver import RuijieRGOSSwitchDriver
from patrol.models import CheckStatus, DeviceAsset, PatrolReport
from patrol.reporter.html import HTMLReporter

HUAWEI_FIXTURES = Path(__file__).parent.parent / "fixtures" / "huawei" / "vrp_switch"
RUIJIE_FIXTURES = Path(__file__).parent.parent / "fixtures" / "ruijie" / "rgos_switch"
RULES_DIR = Path(__file__).parent.parent.parent / "config" / "rules"

HUAWEI_CMD_MAP = {
    "display version": "display_version.txt",
    "display cpu-usage": "display_cpu_usage.txt",
    "display memory-usage": "display_memory_usage.txt",
    "display interface brief": "display_interface_brief.txt",
    "display fan": "display_fan.txt",
    "display power": "display_power.txt",
    "display logbuffer": "display_logbuffer.txt",
    "display ip routing-table": "display_ip_routing_table.txt",
    "display current-configuration": "display_current_configuration.txt",
}

RUIJIE_CMD_MAP = {
    "show version": "show_version.txt",
    "show cpu": "show_cpu.txt",
    "show memory": "show_memory.txt",
    "show ip interface brief": "show_ip_interface_brief.txt",
    "show ip route": "show_ip_route.txt",
    "show logging reverse": "show_logging.txt",
    "show running-config": "show_running_config.txt",
}


def _make_mock_execute(fixture_dir: Path, cmd_map: dict):
    """创建一个 mock execute 函数，根据命令返回 fixture 数据。"""
    def _execute(command: str, timeout: int = 60) -> str:
        filename = cmd_map.get(command)
        if filename:
            fpath = fixture_dir / filename
            if fpath.exists():
                return fpath.read_text(encoding="utf-8")
        return ""
    return _execute


@pytest.fixture
def huawei_asset():
    return DeviceAsset(
        name="华为交换机-1", host="10.0.0.1", vendor="huawei",
        device_type="vrp_switch", login_method="ssh",
        username="admin", password="pw1",
    )


@pytest.fixture
def ruijie_asset():
    return DeviceAsset(
        name="锐捷交换机-1", host="10.0.0.2", vendor="ruijie",
        device_type="rgos_switch", login_method="ssh",
        username="admin", password="pw2",
    )


@pytest.fixture
def huawei_engine():
    return RuleEngine(RuleEngine.load_file(str(RULES_DIR / "vrp_switch.yaml")))


@pytest.fixture
def ruijie_engine():
    return RuleEngine(RuleEngine.load_file(str(RULES_DIR / "rgos_switch.yaml")))


class TestMultiVendorPatrol:
    """场景 2：多厂商混合巡检"""

    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    def test_huawei_and_ruijie(
        self, mock_disconnect, mock_connect,
        huawei_asset, ruijie_asset,
        huawei_engine, ruijie_engine,
        tmp_path
    ):
        """华为 + 锐捷同时巡检，验证数据格式统一"""
        results = []

        # 巡检华为
        with patch.object(SSHCollector, "execute", side_effect=_make_mock_execute(HUAWEI_FIXTURES, HUAWEI_CMD_MAP)):
            huawei_report = run_inspection(huawei_asset, HuaweiVRPSwitchDriver(), huawei_engine)
            results.append(huawei_report)

        # 巡检锐捷
        with patch.object(SSHCollector, "execute", side_effect=_make_mock_execute(RUIJIE_FIXTURES, RUIJIE_CMD_MAP)):
            ruijie_report = run_inspection(ruijie_asset, RuijieRGOSSwitchDriver(), ruijie_engine)
            results.append(ruijie_report)

        # 验证两台设备都成功
        for report in results:
            assert report.error is None, f"{report.asset.name} 巡检失败: {report.error}"
            assert len(report.check_items) > 0, f"{report.asset.name} 无检查项"

        # 验证数据格式统一：所有检查项都有相同的字段结构
        for report in results:
            for item in report.check_items:
                assert hasattr(item, "name")
                assert hasattr(item, "category")
                assert hasattr(item, "status")
                assert hasattr(item, "message")
                assert hasattr(item, "details")
                assert item.status in CheckStatus

        # 验证汇总统计正确
        for report in results:
            total = report.pass_count + report.fail_count + report.unknown_count
            assert total == len(report.check_items), f"{report.asset.name} 汇总不一致"

        # 生成合并报告
        patrol_report = PatrolReport(title="多厂商巡检报告", devices=results)
        html_path = tmp_path / "multi_vendor.html"
        HTMLReporter().generate(patrol_report, html_path)

        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "华为交换机-1" in content
        assert "锐捷交换机-1" in content

        # 验证 JSON
        json_path = html_path.with_suffix(".json")
        import json
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["total_devices"] == 2
        assert len(data["devices"]) == 2
