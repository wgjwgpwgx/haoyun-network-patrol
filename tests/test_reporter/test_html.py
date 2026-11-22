"""HTML 报告生成器测试"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceAsset,
    DeviceReport,
    PatrolReport,
)
from patrol.reporter.html import HTMLReporter


@pytest.fixture
def sample_report(sample_asset) -> PatrolReport:
    """构造一份示例报告。"""
    device = DeviceReport(asset=sample_asset)
    device.check_items = [
        CheckItem(
            name="cpu_usage",
            category="CPU",
            command="display cpu-usage",
            raw_output="Slot 0 CPU 0 usage:\n       12% in last 5 seconds",
            status=CheckStatus.PASS,
            message="CPU 利用率 12%，正常",
        ),
        CheckItem(
            name="interface_status",
            category="接口状态",
            command="display interface brief",
            raw_output="GE1/0/1 UP\nGE1/0/2 DOWN",
            status=CheckStatus.FAIL,
            message="1 个异常接口",
        ),
    ]
    return PatrolReport(title="测试报告", devices=[device])


class TestHTMLReporter:
    def test_creates_file(self, sample_report, tmp_path):
        reporter = HTMLReporter()
        output = reporter.generate(sample_report, tmp_path / "test.html")
        assert output.exists()
        assert output.stat().st_size > 0

    def test_contains_title(self, sample_report, tmp_path):
        reporter = HTMLReporter()
        output = reporter.generate(sample_report, tmp_path / "test.html")
        content = output.read_text(encoding="utf-8")
        assert "测试报告" in content

    def test_contains_status(self, sample_report, tmp_path):
        reporter = HTMLReporter()
        output = reporter.generate(sample_report, tmp_path / "test.html")
        content = output.read_text(encoding="utf-8")
        assert "PASS" in content
        assert "FAIL" in content

    def test_contains_device_info(self, sample_report, tmp_path):
        reporter = HTMLReporter()
        output = reporter.generate(sample_report, tmp_path / "test.html")
        content = output.read_text(encoding="utf-8")
        assert "测试交换机" in content
        assert "192.168.1.1" in content

    def test_empty_report(self, tmp_path):
        report = PatrolReport(title="空报告", devices=[])
        reporter = HTMLReporter()
        output = reporter.generate(report, tmp_path / "empty.html")
        content = output.read_text(encoding="utf-8")
        assert "空报告" in content

    def test_raw_output_shown_smoothly(self, sample_report, tmp_path):
        """原始输出平滑对齐直出报告,不再折叠在"查看"开关后面。"""
        reporter = HTMLReporter()
        output = reporter.generate(sample_report, tmp_path / "raw.html")
        content = output.read_text(encoding="utf-8")
        assert "toggleRaw" not in content          # 旧折叠脚本已移除
        assert 'class="raw-output"' in content     # 原始输出块常显
        assert "GE1/0/1 UP" in content             # 设备回显直接可见
        assert "display interface brief" in content  # 执行命令随块展示
        assert "word-break: break-word" in content   # 平滑换行,不逐字截断

    def test_severity_shows_chinese(self, sample_report, tmp_path):
        sample_report.devices[0].check_items[1].details = {"severity": "critical"}
        reporter = HTMLReporter()
        output = reporter.generate(sample_report, tmp_path / "sev.html")
        content = output.read_text(encoding="utf-8")
        assert "严重" in content
        assert ">critical<" not in content


class TestTopologySvg:
    def _dev(self, name, neighbors, status="PASS"):
        from patrol.models import CheckStatus
        dev = DeviceReport(asset=DeviceAsset(name=name, host="10.0.0.1"))
        dev.check_items.append(CheckItem(
            name="lldp_neighbor", category="网络拓扑", command="lldp",
            raw_output="", status=CheckStatus(status), message="",
            details={"neighbors": neighbors, "neighbor_count": len(neighbors)}))
        return dev

    def test_topology_rendered(self, tmp_path):
        report = PatrolReport(devices=[
            self._dev("sw-a", [{"local_intf": "GE1/0/1",
                                "peer_device": "sw-b",
                                "peer_port": "GE1/0/24"}]),
            self._dev("sw-b", []),
        ])
        out = tmp_path / "t.html"
        HTMLReporter().generate(report, out)
        html = out.read_text(encoding="utf-8")
        assert "网络拓扑" in html and "<svg" in html
        assert "sw-a" in html and "sw-b" in html
        assert "GE1/0/1" in html  # 端口标注

    def test_no_lldp_no_topology(self, tmp_path):
        dev = DeviceReport(asset=DeviceAsset(name="x", host="10.0.0.9"))
        out = tmp_path / "n.html"
        HTMLReporter().generate(PatrolReport(devices=[dev]), out)
        assert "网络拓扑" not in out.read_text(encoding="utf-8")


class TestCharts:
    def test_pie_and_bars_rendered(self, tmp_path):
        from patrol.models import CheckStatus
        dev = DeviceReport(asset=DeviceAsset(name="c", host="10.0.0.3"))
        dev.check_items = [
            CheckItem(name="cpu_usage", category="CPU", command="c",
                      raw_output="", status=CheckStatus.PASS, message="",
                      details={"usage_percent": 42}),
            CheckItem(name="memory_usage", category="内存", command="c",
                      raw_output="", status=CheckStatus.PASS, message="",
                      details={"usage_percent": 71}),
        ]
        out = tmp_path / "c.html"
        HTMLReporter().generate(PatrolReport(devices=[dev]), out)
        html = out.read_text(encoding="utf-8")
        assert "巡检结果分布" in html and "<svg" in html
        assert "CPU" in html and "42%" in html  # 条形图

    def test_chart_functions(self):
        from patrol.reporter.charts import bars_svg, pie_svg, trend_svg
        assert "<svg" in pie_svg([("通过", 3, "#52c41a"), ("失败", 1, "#f00")])
        assert "<svg" in bars_svg([("CPU", 42), ("内存", 88)])
        assert "<svg" in trend_svg([("t1", 30), ("t2", 55), ("t3", 42)])
        assert pie_svg([]) == ""
        assert trend_svg([("t1", 30)]) == ""  # 单点不成线
