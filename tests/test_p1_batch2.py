"""P1 第二批功能测试:预测/确认单/白名单/对比"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestPrediction:
    def test_rising_trend_predicts(self):
        from patrol.prediction import predict_threshold
        series = [
            ("2026-11-01T10:00:00", 40),
            ("2026-11-08T10:00:00", 55),
            ("2026-11-15T10:00:00", 70),
        ]
        r = predict_threshold(series, threshold=80)
        assert r is not None
        assert r["will_exceed"] is True
        assert r["days_to_exceed"] > 0

    def test_stable_no_prediction(self):
        from patrol.prediction import predict_threshold
        series = [
            ("2026-11-01T10:00:00", 50),
            ("2026-11-08T10:00:00", 51),
            ("2026-11-15T10:00:00", 50),
        ]
        assert predict_threshold(series, threshold=80) is None

    def test_insufficient_data(self):
        from patrol.prediction import predict_threshold
        assert predict_threshold([("t1", 50)], 80) is None
        assert predict_threshold([], 80) is None

    def test_already_over(self):
        from patrol.prediction import predict_threshold
        series = [
            ("2026-11-01T10:00:00", 75),
            ("2026-11-08T10:00:00", 82),
            ("2026-11-15T10:00:00", 85),
        ]
        r = predict_threshold(series, threshold=80)
        assert r is not None and r["days_to_exceed"] == 0


class TestKnownIssues:
    @staticmethod
    def _run(known_issues: str):
        """锐捷设备 CPU 91%(规则阈值 80%):验证白名单对 FAIL 项的实际作用。"""
        from patrol.analyzer.engine import RuleEngine
        from patrol.cli import run_inspection
        from patrol.collector.ssh import SSHCollector
        from patrol.drivers.ruijie.driver import RuijieRGOSSwitchDriver
        from patrol.models import DeviceAsset

        def fake_execute(self, command, timeout=60):
            return {"show cpu": "CPU utilization in five seconds: 91%"}.get(command, "")

        engine = RuleEngine(RuleEngine.parse_rules({"rules": [{
            "id": "T1", "check_name": "cpu_usage", "name": "CPU 利用率过高",
            "severity": "critical", "vendors": ["*"], "device_types": ["*"],
            "metric": "usage_percent", "operator": "gt", "value": 80,
            "suggestion": "排查"}]}))
        asset = DeviceAsset(
            name="白名单机", host="10.0.0.1", vendor="ruijie",
            device_type="rgos_switch", username="u", password="p",
            known_issues=known_issues)
        with patch.object(SSHCollector, "connect"), \
             patch.object(SSHCollector, "disconnect"), \
             patch.object(SSHCollector, "execute", fake_execute):
            return run_inspection(asset, RuijieRGOSSwitchDriver(), engine)

    @staticmethod
    def _cpu(report):
        return next(it for it in report.check_items if it.name == "cpu_usage")

    def test_known_issue_is_marked_and_not_counted_as_failure(self):
        report = self._run("cpu_usage")
        cpu = self._cpu(report)
        assert cpu.status.value == "PASS" and "已知异常" in cpu.message
        assert report.fail_count == 0

    def test_same_issue_without_whitelist_fails(self):
        report = self._run("")
        cpu = self._cpu(report)
        assert cpu.status.value == "FAIL" and "已知异常" not in cpu.message
        assert report.fail_count == 1


class TestConfirmationRoute:
    def test_confirmation_page(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        data = {"generated_at": "2026-11-15T10:00:00",
                "exec_summary": "网络平稳",
                "devices": [{
                    "name": "sw-01", "customer": "客户A", "host": "10.0.0.1",
                    "model": "S5735", "pass_count": 5, "fail_count": 1,
                    "unknown_count": 0,
                    "check_items": [
                        {"name": "cpu", "status": "PASS", "message": "OK"},
                        {"name": "fan", "status": "FAIL",
                         "message": "风扇故障"}]}]}
        (out / "test.json").write_text(json.dumps(data), encoding="utf-8")
        (out / "test.html").write_text("<html></html>", encoding="utf-8")

        from fastapi.testclient import TestClient
        import patrol.api.app as am
        r = TestClient(am.app).get("/ui/reports/test.html/confirmation")
        assert r.status_code == 200
        assert "巡检结果确认单" in r.text
        assert "客户A" in r.text
        assert "sw-01" in r.text


class TestCompareRoute:
    # 系统实际产出的报告 JSON 命名(界面任务:patrol_{主机}_{时间戳}.json)
    NAMES = ("patrol_sw-01_20261101_100000.json", "patrol_sw-01_20261108_100000.json")

    def _write_reports(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        for name, fail_count in zip(self.NAMES, (0, 1)):
            data = {"generated_at": f"2026-11-0{self.NAMES.index(name) + 1}T10:00:00",
                    "devices": [{
                        "name": "sw-01", "customer": "C", "host": "10.0.0.1",
                        "model": "S5735",
                        "pass_count": 5, "fail_count": fail_count,
                        "unknown_count": 0,
                        "check_items": [
                            {"name": "cpu", "status": "PASS", "message": "OK"},
                            {"name": "fan", "status":
                             "FAIL" if fail_count else "PASS",
                             "message": "风扇故障" if fail_count else "OK",
                             "details": {}}]}]}
            (out / name).write_text(json.dumps(data), encoding="utf-8")
        (out / "zz_notes.json").write_text('{"devices": []}', encoding="utf-8")

    def test_compare_page_lists_real_report_files(self, tmp_path):
        """下拉框必须能列出系统自己产出的 patrol_*.json(曾被当成非报告 JSON 跳过)。"""
        from fastapi.testclient import TestClient
        import patrol.api.app as am

        self._write_reports(tmp_path)
        r = TestClient(am.app).get("/ui/reports/compare")
        assert r.status_code == 200
        for name in self.NAMES:
            assert name in r.text, f"多期对比下拉缺少系统产出的报告: {name}"
        assert "zz_notes.json" not in r.text

    def test_compare_page(self, tmp_path):
        from fastapi.testclient import TestClient
        import patrol.api.app as am

        self._write_reports(tmp_path)
        a, b = self.NAMES
        r = TestClient(am.app).get(f"/ui/reports/compare?a={a}&b={b}")
        assert r.status_code == 200
        assert "已解决" in r.text or "新增异常" in r.text
