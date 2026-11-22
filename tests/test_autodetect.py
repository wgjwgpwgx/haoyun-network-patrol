"""设备自动识别测试(销号清单 #6 / U-2)"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from patrol.autodetect import detect_from_version, probe_device

FIX = Path(__file__).parent / "fixtures"


def _fx(path: str) -> str:
    return (FIX / path).read_text(encoding="utf-8")


class TestDetectFromVersion:
    def test_huawei_fixture(self):
        r = detect_from_version(_fx("huawei/vrp_switch/display_version.txt"))
        assert r["vendor"] == "huawei" and r["device_type"] == "vrp_switch"
        assert "S5735" in r["model"]
        assert r["software_version"]

    def test_h3c_comware_fixture(self):
        r = detect_from_version(_fx("h3c/comware_switch/display_version.txt"))
        assert r["vendor"] == "h3c" and r["device_type"] == "comware_switch"

    def test_zte_fixture(self):
        r = detect_from_version(_fx("zte/zxr10_switch/show_version.txt"))
        assert r["vendor"] == "zte" and r["device_type"] == "zxr10_switch"
        assert r["model"] == "5250-28PS-E"

    def test_maipu_fixture(self):
        r = detect_from_version(_fx("maipu/mypower_switch/show_version.txt"))
        assert r["vendor"] == "maipu" and r["device_type"] == "mypower_switch"
        assert r["model"] == "S3100V2-24GT4XS"

    def test_ruijie_inline(self):
        r = detect_from_version(
            "Ruijie Full Services Software Platform Software\n"
            "RGOS 10.4(3b14) Release(191117)\nS5750C-24GT4S uptime")
        assert r["vendor"] == "ruijie" and r["device_type"] == "rgos_switch"

    def test_usg_priority_over_huawei(self):
        r = detect_from_version(
            "Huawei Versatile Routing Platform Software\n"
            "VRP (R) software, Version 5.160 (USG6000V V500R005)")
        assert r["device_type"] == "usg_firewall"

    def test_s7506(self):
        r = detect_from_version(
            "H3C Comware Platform Software\nS7506E uptime is 30 weeks")
        assert r["vendor"] == "h3c" and r["device_type"] == "s7506e"

    def test_unknown_and_empty(self):
        assert detect_from_version("") is None
        assert detect_from_version("Welcome to some unknown device") is None


class TestProbeDevice:
    HUAWEI_OUT = _fx("huawei/vrp_switch/display_version.txt")

    @patch("netmiko.ConnectHandler")
    def test_ssh_success(self, mock_ch):
        conn = MagicMock()
        conn.send_command.return_value = self.HUAWEI_OUT
        mock_ch.return_value = conn
        r = probe_device("192.0.2.1", "u", "p")
        assert r["ok"] and r["method"] == "ssh"
        assert r["result"]["vendor"] == "huawei"
        mock_ch.assert_called_once()  # 未降级

    @patch("netmiko.ConnectHandler")
    def test_fallback_to_telnet(self, mock_ch):
        conn = MagicMock()
        conn.send_command.return_value = self.HUAWEI_OUT
        # 第一次(SSH)连接抛错,第二次(Telnet)成功
        mock_ch.side_effect = [OSError("ssh refused"), conn]
        r = probe_device("192.0.2.1", "u", "p")
        assert r["ok"] and r["method"] == "telnet"

    @patch("netmiko.ConnectHandler")
    def test_both_fail(self, mock_ch):
        mock_ch.side_effect = OSError("no route")
        r = probe_device("192.0.2.1", "u", "p")
        assert not r["ok"] and "no route" in r["error"]

    @patch("netmiko.ConnectHandler")
    def test_show_version_fallback_command(self, mock_ch):
        conn = MagicMock()
        # display version 空 → 尝试 show version(用中兴回显驱动 fallback 分支)
        conn.send_command.side_effect = ["", _fx("zte/zxr10_switch/show_version.txt")]
        mock_ch.return_value = conn
        r = probe_device("192.0.2.1", "u", "p")
        assert r["ok"] and r["result"]["vendor"] == "zte"


class TestWebDetectRoute:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from patrol.api.app import app
        return TestClient(app)

    def test_route_with_mock_probe(self, client, monkeypatch):
        from patrol import autodetect as ad

        monkeypatch.setattr(
            ad, "probe_device",
            lambda *a, **k: {"ok": True, "method": "ssh",
                             "result": {"vendor": "huawei",
                                        "device_type": "vrp_switch",
                                        "model": "S5735", "software_version": "V500"},
                             "raw": "...", "error": ""})
        r = client.post("/ui/devices/detect", data={
            "host": "10.1.1.1", "username": "u", "password": "p",
            "login_method": "ssh", "port": 0})
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_route_rejects_bad_host(self, client):
        r = client.post("/ui/devices/detect", data={
            "host": "../evil", "username": "u", "password": "p"})
        assert r.status_code == 200 and r.json()["ok"] is False
