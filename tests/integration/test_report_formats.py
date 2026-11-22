"""集成测试 - 场景 4：报告格式验证

验证 HTML、Word、PDF 报告都能生成且内容合理。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from patrol.analyzer.engine import RuleEngine
from patrol.cli import run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.models import DeviceAsset, PatrolReport
from patrol.reporter.html import HTMLReporter
from patrol.reporter.word import WordReporter, generate_word_filename
from patrol.reporter.pdf import PDFReporter, generate_pdf_filename

FIXTURES = Path(__file__).parent.parent / "fixtures" / "huawei" / "vrp_switch"
RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "vrp_switch.yaml"

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


def _mock_execute(command: str, timeout: int = 60) -> str:
    filename = CMD_TO_FILE.get(command)
    if filename:
        fpath = FIXTURES / filename
        if fpath.exists():
            return fpath.read_text(encoding="utf-8")
    return ""


@pytest.fixture
def asset():
    return DeviceAsset(
        name="报告测试设备", host="10.0.0.1", vendor="huawei",
        device_type="vrp_switch", login_method="ssh",
        username="admin", password="secret123",
    )


@pytest.fixture
def engine():
    return RuleEngine(RuleEngine.load_file(str(RULES)))


@pytest.fixture
def driver():
    return HuaweiVRPSwitchDriver()


@pytest.fixture
def patrol_report(asset, driver, engine) -> PatrolReport:
    """生成一份巡检报告用于格式测试。"""
    with patch.object(SSHCollector, "connect", return_value=None), \
         patch.object(SSHCollector, "disconnect", return_value=None), \
         patch.object(SSHCollector, "execute", side_effect=_mock_execute):
        report = run_inspection(asset, driver, engine)
    return PatrolReport(title="格式测试报告", devices=[report])


class TestReportFormats:
    """场景 4：报告格式验证"""

    def test_html_report(self, patrol_report, tmp_path):
        """HTML 报告：存在、大小合理、内容正确"""
        path = tmp_path / "report.html"
        HTMLReporter().generate(patrol_report, path)

        assert path.exists()
        assert path.stat().st_size > 1000

        content = path.read_text(encoding="utf-8")
        assert "报告测试设备" in content
        assert "PASS" in content
        assert "<html" in content.lower()

    def test_json_data_file(self, patrol_report, tmp_path):
        """JSON 数据文件：存在、结构正确"""
        html_path = tmp_path / "report.html"
        HTMLReporter().generate(patrol_report, html_path)

        json_path = html_path.with_suffix(".json")
        assert json_path.exists()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["title"] == "格式测试报告"
        assert data["total_devices"] == 1
        assert len(data["devices"]) == 1

        dev = data["devices"][0]
        assert dev["name"] == "报告测试设备"
        assert len(dev["check_items"]) > 0
        assert "pass_count" in dev
        assert "fail_count" in dev

    def test_word_report(self, patrol_report, tmp_path):
        """Word 报告：存在、大小合理"""
        path = tmp_path / "report.docx"
        WordReporter().generate(patrol_report, path)

        assert path.exists()
        assert path.stat().st_size > 5000  # Word 文件至少 5KB

    def test_word_filename_format(self, patrol_report):
        """Word 文件名格式正确"""
        filename = generate_word_filename(patrol_report)
        assert filename.startswith("巡检报告_报告测试设备_")
        assert filename.endswith(".docx")

    def test_pdf_filename_format(self, patrol_report):
        """PDF 文件名格式正确"""
        filename = generate_pdf_filename(patrol_report)
        assert filename.startswith("巡检报告_报告测试设备_")
        assert filename.endswith(".pdf")

    def test_password_not_in_html(self, patrol_report, tmp_path):
        """HTML 报告中不含密码"""
        path = tmp_path / "report.html"
        HTMLReporter().generate(patrol_report, path)
        content = path.read_text(encoding="utf-8")
        assert "secret123" not in content

    def test_password_not_in_json(self, patrol_report, tmp_path):
        """JSON 数据中不含密码"""
        html_path = tmp_path / "report.html"
        HTMLReporter().generate(patrol_report, html_path)
        json_path = html_path.with_suffix(".json")
        content = json_path.read_text(encoding="utf-8")
        assert "secret123" not in content

    def test_password_not_in_word(self, patrol_report, tmp_path):
        """Word 报告中不含密码（通过检查生成过程）"""
        # Word 报告使用 redact() 脱敏，密码不会出现在 message 中
        # 但 raw_output 也需要脱敏
        path = tmp_path / "report.docx"
        WordReporter().generate(patrol_report, path)
        # docx 是二进制格式，用 python-docx 读取验证
        from docx import Document
        doc = Document(str(path))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    full_text += cell.text
        assert "secret123" not in full_text
