"""集成测试 - 场景 1：单设备完整巡检流程

使用华为 VRP 交换机测试 fixture，不连真实 SSH。
验证：采集 → 解析 → 规则判定 → 报告生成 → 报告内容。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from patrol.analyzer.engine import RuleEngine
from patrol.cli import run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.models import CheckStatus, DeviceAsset, DeviceReport, PatrolReport
from patrol.reporter.html import HTMLReporter
from patrol.reporter.word import WordReporter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "huawei" / "vrp_switch"
RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "vrp_switch.yaml"

# 命令到 fixture 文件的映射
CMD_TO_FILE = {
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


@pytest.fixture
def huawei_asset() -> DeviceAsset:
    return DeviceAsset(
        name="华为交换机-测试",
        host="192.168.154.221",
        vendor="huawei",
        device_type="vrp_switch",
        login_method="ssh",
        port=22,
        username="huawei",
        password="test123",
        timeout=10,
        command_timeout=30,
    )


@pytest.fixture
def rule_engine() -> RuleEngine:
    rules = RuleEngine.load_file(str(RULES))
    return RuleEngine(rules)


@pytest.fixture
def driver() -> HuaweiVRPSwitchDriver:
    return HuaweiVRPSwitchDriver()


def _mock_execute(command: str, timeout: int = 60) -> str:
    """根据命令返回对应的 fixture 文件内容。"""
    filename = CMD_TO_FILE.get(command)
    if filename:
        fpath = FIXTURES / filename
        if fpath.exists():
            return fpath.read_text(encoding="utf-8")
    return ""


class TestSingleDeviceFullPatrol:
    """场景 1：单设备完整巡检流程"""

    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    @patch.object(SSHCollector, "execute", side_effect=_mock_execute)
    def test_full_patrol_flow(
        self, mock_exec, mock_disconnect, mock_connect,
        huawei_asset, driver, rule_engine, tmp_path
    ):
        """完整巡检流程：连接 → 采集 → 解析 → 规则 → 报告"""
        # 1. 执行巡检
        report = run_inspection(huawei_asset, driver, rule_engine)

        # 2. 验证连接
        mock_connect.assert_called_once_with(huawei_asset)
        mock_disconnect.assert_called_once()

        # 3. 验证无错误
        assert report.error is None, f"巡检出错: {report.error}"

        # 4. 验证设备信息
        assert report.model != "", "设备型号未解析"
        assert report.software_version != "", "软件版本未解析"
        assert report.uptime != "", "运行时间未解析"

        # 5. 验证检查项
        assert len(report.check_items) > 0, "无检查项"
        statuses = {item.status for item in report.check_items}
        assert CheckStatus.PASS in statuses, "无 PASS 项"
        assert CheckStatus.FAIL in statuses, "无 FAIL 项（测试 fixture 应触发 FAIL）"

        # 6. 验证每个检查项有完整字段
        for item in report.check_items:
            assert item.name, "检查项缺少 name"
            assert item.category, "检查项缺少 category"
            assert item.command, "检查项缺少 command"
            assert item.message, "检查项缺少 message"
            assert item.status in CheckStatus, f"无效状态: {item.status}"

        # 7. 验证汇总
        assert report.pass_count > 0
        assert report.fail_count > 0
        assert report.pass_count + report.fail_count + report.unknown_count == len(report.check_items)

        # 8. 生成 HTML 报告
        patrol_report = PatrolReport(title="集成测试报告", devices=[report])
        html_path = tmp_path / "test_report.html"
        HTMLReporter().generate(patrol_report, html_path)

        assert html_path.exists(), "HTML 报告未生成"
        assert html_path.stat().st_size > 1000, "HTML 报告内容过少"
        content = html_path.read_text(encoding="utf-8")
        assert "华为交换机-测试" in content
        assert "PASS" in content
        assert "FAIL" in content

        # 9. 验证 JSON 数据文件
        json_path = html_path.with_suffix(".json")
        assert json_path.exists(), "JSON 数据文件未生成"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["total_devices"] == 1
        assert len(data["devices"]) == 1
        assert data["devices"][0]["name"] == "华为交换机-测试"

        # 10. 生成 Word 报告
        word_path = tmp_path / "test_report.docx"
        WordReporter().generate(patrol_report, word_path)
        assert word_path.exists(), "Word 报告未生成"
        assert word_path.stat().st_size > 5000, "Word 报告内容过少"

    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    @patch.object(SSHCollector, "execute", side_effect=_mock_execute)
    def test_check_items_data_integrity(
        self, mock_exec, mock_disconnect, mock_connect,
        huawei_asset, driver, rule_engine
    ):
        """验证检查项数据完整性"""
        report = run_inspection(huawei_asset, driver, rule_engine)

        # 按名称索引检查项
        items_by_name = {item.name: item for item in report.check_items}

        # 验证 CPU 检查项
        if "cpu_usage" in items_by_name:
            cpu = items_by_name["cpu_usage"]
            assert cpu.details.get("usage_percent") is not None, "CPU 利用率未解析"
            assert isinstance(cpu.details["usage_percent"], (int, float))

        # 验证内存检查项
        if "memory_usage" in items_by_name:
            mem = items_by_name["memory_usage"]
            assert mem.details.get("usage_percent") is not None, "内存利用率未解析"

        # 验证接口检查项
        if "interface_status" in items_by_name:
            iface = items_by_name["interface_status"]
            assert "total" in iface.details, "接口总数未解析"
            assert "abnormal_count" in iface.details, "异常接口数未解析"

    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    @patch.object(SSHCollector, "execute", side_effect=_mock_execute)
    def test_report_redaction(
        self, mock_exec, mock_disconnect, mock_connect,
        huawei_asset, driver, rule_engine, tmp_path
    ):
        """验证报告中密码已脱敏"""
        report = run_inspection(huawei_asset, driver, rule_engine)
        patrol_report = PatrolReport(title="脱敏测试", devices=[report])

        html_path = tmp_path / "redacted.html"
        HTMLReporter().generate(patrol_report, html_path)

        content = html_path.read_text(encoding="utf-8")
        assert "test123" not in content, "密码未脱敏！"

        json_path = html_path.with_suffix(".json")
        json_content = json_path.read_text(encoding="utf-8")
        assert "test123" not in json_content, "JSON 中密码未脱敏！"
