"""SMTP 邮件分发测试(销号清单 #13c)"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from patrol.desktop import service


@pytest.fixture(autouse=True)
def smtp_cfg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = Path("config"); cfg_dir.mkdir()
    (cfg_dir / "smtp.yaml").write_text(
        "enabled: true\nhost: smtp.example.com\nport: 465\n"
        "ssl: true\nusername: ops@ex.com\npassword: appkey\n"
        "from: 巡检助手 <ops@ex.com>\ncc_boss: [boss@ex.com]\n",
        encoding="utf-8")


def test_config_loaded():
    cfg = service.smtp_config()
    assert cfg["enabled"] is True and cfg["host"] == "smtp.example.com"


def test_send_requires_enabled(tmp_path, monkeypatch):
    empty = tmp_path / "empty"  # 全新空目录(autouse fixture 的配置不在其中)
    empty.mkdir()
    monkeypatch.chdir(empty)
    with pytest.raises(RuntimeError, match="未启用"):
        service.send_report_email(["a@x.com"], "s", "b", [])


def test_send_email_with_attachment(tmp_path):
    att = tmp_path / "巡检台账.xlsx"
    att.write_bytes(b"PK-fake")

    with patch("smtplib.SMTP_SSL") as mock_smtp:
        server = MagicMock()
        mock_smtp.return_value = server
        result = service.send_report_email(
            ["jiafang@ex.com"], "巡检报告", "请查收",
            [att], cc=["boss@ex.com"])

    assert result["ok"] is True
    mock_smtp.assert_called_once_with("smtp.example.com", 465, timeout=30)
    server.login.assert_called_once_with("ops@ex.com", "appkey")
    sent = server.sendmail.call_args.args
    assert "jiafang@ex.com" in sent[1] and "boss@ex.com" in sent[1]
    body = server.sendmail.call_args.args[2]
    assert "Content-Disposition" in body  # 含附件头


def test_customer_email_roundtrip(tmp_path):
    from patrol.api.store import CustomerStore, DeviceStore

    cs = CustomerStore(str(tmp_path / "c.yaml"))
    service.save_customer(cs, DeviceStore(str(tmp_path / "d.yaml")), None, {
        "name": "甲方A", "contact": "", "phone": "",
        "email": "a@x.com;b@x.com", "remark": ""})
    assert cs.get("甲方A")["email"] == "a@x.com;b@x.com"
