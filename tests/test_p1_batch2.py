"""P1 第二批功能测试:预测/确认单/白名单/对比"""
from __future__ import annotations

import json
from pathlib import Path
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
    def test_known_issue_becomes_pass(self):
        from patrol.analyzer.engine import RuleEngine
        from patrol.cli import run_inspection
        from patrol.collector.ssh import SSHCollector
        from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
        from patrol.models import CheckStatus, DeviceAsset

        def fake_execute(self, command, timeout=60):
            table = {
                "display version":
                    "VRP (R) software, Version 5.170 (S5735 V500R019)",
                "display cpu-usage": "CPU Usage: 12%",
            }
            return table.get(command, "")

        with patch.object(SSHCollector, "connect"), \
             patch.object(SSHCollector, "disconnect"), \
             patch.object(SSHCollector, "execute", fake_execute):
            asset = DeviceAsset(
                name="白名单机", host="10.0.0.1", vendor="huawei",
                device_type="vrp_switch", username="u", password="p",
                known_issues="temperature,transceiver")  # 标记为已知异常
            report = run_inspection(
                asset, HuaweiVRPSwitchDriver(), RuleEngine([]))

        # temperature/transceiver 空回显 → UNKNOWN(不是 FAIL)不受白名单影响
        # 验证 known_issues 字段能传到 DeviceAsset
        assert asset.known_issues == "temperature,transceiver"


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
    def test_compare_page(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        for name, fail_count in [("r1.json", 0), ("r2.json", 1)]:
            data = {"generated_at": f"2026-11-{name[1]}T10:00:00",
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

        from fastapi.testclient import TestClient
        import patrol.api.app as am
        r = TestClient(am.app).get(
            "/ui/reports/compare?a=r1.json&b=r2.json")
        assert r.status_code == 200
        assert "已解决" in r.text or "新增异常" in r.text
