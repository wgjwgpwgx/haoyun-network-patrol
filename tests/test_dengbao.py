"""等保 2.0 安全基线包测试(销号清单 #4)"""
from __future__ import annotations

from pathlib import Path

import patrol.drivers  # noqa: F401
from patrol.analyzer.engine import RuleEngine, expand_parsed
from patrol.drivers.h3c.s7506e import H3CS7506EDriver
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.drivers.security_baseline import extract_dengbao_checks, parse_ntp_status

RULES = Path(__file__).parent.parent / "config" / "rules" / "baseline_dengbao.yaml"

# 含等保要素的配置片段
GOOD_CFG = """
password-control enable
 password-control length 8
user-interface vty 0 4
 acl 2001 inbound
 idle-timeout 5
info-center loghost 10.1.1.100
ntp-service unicast-server 10.1.1.200
"""
# 不达标的空配置
BAD_CFG = """
hostname sw
user-interface vty 0 4
 idle-timeout 30
"""


class TestExtract:
    def test_good_config_all_pass(self):
        checks = {c["name"]: c["parsed"] for c in extract_dengbao_checks(GOOD_CFG)}
        assert checks["login_lock"]["login_locked"] is True
        assert checks["password_policy"]["policy_ok"] is True
        assert checks["mgmt_acl"]["acl_enabled"] is True
        assert checks["syslog_external"]["enabled"] is True
        assert checks["vty_idle_timeout"]["timeout_ok"] is True
        assert checks["vty_idle_timeout"]["idle_minutes"] == 5

    def test_bad_config_all_fail(self):
        checks = {c["name"]: c["parsed"] for c in extract_dengbao_checks(BAD_CFG)}
        assert checks["login_lock"]["login_locked"] is False
        assert checks["mgmt_acl"]["acl_enabled"] is False
        assert checks["syslog_external"]["enabled"] is False
        assert checks["vty_idle_timeout"]["timeout_ok"] is False  # 30 分钟过长

    def test_ntp(self):
        assert parse_ntp_status("clock status: synchronized\nstratum: 2")["synced"] is True
        assert parse_ntp_status("clock status: unsynchronized")["synced"] is False


class TestNestedIntoDrivers:
    def test_huawei_config_cur_contains_baseline(self):
        pr = HuaweiVRPSwitchDriver().parse_output("config_cur", GOOD_CFG)
        names = [x.name for x in expand_parsed(pr)]
        for n in ("login_lock", "password_policy", "mgmt_acl",
                  "syslog_external", "vty_idle_timeout"):
            assert n in names

    def test_s7506e_config_cur_contains_baseline(self):
        pr = H3CS7506EDriver().parse_output("config_cur", GOOD_CFG)
        names = [x.name for x in expand_parsed(pr)]
        assert "vty_idle_timeout" in names

    def test_ntp_command_registered(self):
        from patrol.drivers.registry import get_driver
        for key in ("huawei/vrp_switch", "huawei/usg_firewall", "h3c/s7506e"):
            names = {c.name for c in get_driver(*key.split("/")).get_check_commands()}
            assert "ntp_status" in names, key


class TestDengbaoRules:
    def test_load_and_judge(self):
        engine = RuleEngine(RuleEngine.load_file(str(RULES)))
        assert len(engine.rules) == 8

        # BAD 配置 → 基线项 FAIL
        pr = HuaweiVRPSwitchDriver().parse_output("config_cur", BAD_CFG)
        nested = {x.name: x for x in expand_parsed(pr)}
        item = engine.evaluate(nested["login_lock"], vendor="huawei",
                               device_type="vrp_switch")
        assert item.status.value == "FAIL" and "D001" in item.message

        # GOOD 配置 → PASS
        pr = HuaweiVRPSwitchDriver().parse_output("config_cur", GOOD_CFG)
        nested = {x.name: x for x in expand_parsed(pr)}
        item = engine.evaluate(nested["login_lock"], vendor="huawei",
                               device_type="vrp_switch")
        assert item.status.value == "PASS"

        # NTP:未同步 FAIL
        ntp = HuaweiVRPSwitchDriver().parse_output(
            "ntp_status", "clock status: unsynchronized")
        item = engine.evaluate(ntp, vendor="huawei", device_type="vrp_switch")
        assert item.status.value == "FAIL" and "D006" in item.message


class TestScoringIntegration:
    def test_baseline_items_in_security_group(self):
        from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport
        from patrol.scoring import score_device

        dev = DeviceReport(asset=DeviceAsset(name="d", host="10.0.0.1"))
        dev.check_items = [
            CheckItem(name="fan_status", category="x", command="c",
                      raw_output="", status=CheckStatus.PASS, message=""),
            CheckItem(name="login_lock", category="安全基线", command="c",
                      raw_output="", status=CheckStatus.FAIL, message="",
                      details={"severity": "critical"}),
        ]
        r = score_device(dev)
        assert r["groups"]["security"]["fail"] == 1
        assert r["veto"] is True  # 等保 critical 未达标同样一票否决


class TestReportCompliance:
    def test_word_and_json_baseline_rate(self, tmp_path):
        import json

        from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport
        from patrol.reporter.html import HTMLReporter
        from patrol.reporter.word import WordReporter

        dev = DeviceReport(asset=DeviceAsset(name="d", host="10.0.0.1"))
        dev.check_items = [
            CheckItem(name="telnet_service", category="安全", command="c",
                      raw_output="", status=CheckStatus.FAIL, message="",
                      details={"severity": "warning"}),
            CheckItem(name="login_lock", category="安全基线", command="c",
                      raw_output="", status=CheckStatus.PASS, message=""),
        ]
        report = PatrolReport(devices=[dev])

        out = tmp_path / "b.docx"
        WordReporter().generate(report, out)
        from docx import Document
        doc = Document(str(out))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "安全基线达标率:50%(1/2 项达标)" in text

        out2 = tmp_path / "b.html"
        HTMLReporter().generate(report, out2)
        data = json.loads(out2.with_suffix(".json").read_text(encoding="utf-8"))
        assert data["baseline"] == {"pass": 1, "fail": 1, "rate": 50}
        assert data["health"]["overall"] is not None
