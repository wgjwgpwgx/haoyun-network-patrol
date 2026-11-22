"""桌面小工具服务层单测(无界面,覆盖与 Web 端一致的业务闭环)"""
from __future__ import annotations

import json

import pytest

from patrol.api.store import CustomerStore, DeviceStore
from patrol.desktop import service


@pytest.fixture
def stores(tmp_path):
    return DeviceStore(str(tmp_path / "devices.yaml")), CustomerStore(str(tmp_path / "customers.yaml"))


@pytest.fixture
def out(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return d


def _device_fields(**over):
    fields = {
        "name": "核心交换机",
        "customer": "",
        "host": "10.0.0.1",
        "vendor": "h3c",
        "device_type": "comware_switch",
        "login_method": "ssh",
        "port": 22,
        "web_port": 443,
        "username": "admin",
        "password": "pass123",
        "super_password": "",
        "timeout": 30,
        "command_timeout": 120,
        "verify_ssl": True,
        "enabled": True,
    }
    fields.update(over)
    return fields


REPORT_DATA = {
    "title": "网络设备巡检报告",
    "devices": [{
        "name": "核心交换机", "customer": "甲公司", "host": "10.0.0.1",
        "vendor": "h3c", "device_type": "comware_switch",
        "pass_count": 1, "fail_count": 1, "unknown_count": 1,
        "check_items": [
            {"name": "CPU 利用率", "category": "性能", "command": "dis cpu",
             "raw_output": "...", "status": "PASS", "message": "正常",
             "details": {}},
            {"name": "风扇状态", "category": "硬件", "command": "dis fan",
             "raw_output": "...", "status": "FAIL", "message": "风扇故障",
             "details": {"severity": "critical", "suggestion": "更换风扇"}},
            {"name": "内存利用率", "category": "性能", "command": "dis memory",
             "raw_output": "...", "status": "UNKNOWN", "message": "指标值无法比较",
             "details": {}},
        ],
    }],
}


def _write_report(out, filename="patrol_10.0.0.1_20260101_000000.html", data=None):
    (out / filename).write_text("<html>报告</html>", encoding="utf-8")
    (out / filename.replace(".html", ".json")).write_text(
        json.dumps(data if data is not None else REPORT_DATA, ensure_ascii=False),
        encoding="utf-8")
    return filename


class TestSaveDevice:
    def test_create(self, stores):
        devices, customers = stores
        service.save_device(devices, customers, None, _device_fields())
        d = devices.get("核心交换机")
        assert d and d["host"] == "10.0.0.1" and d["password"] == "pass123"
        assert d["verify_ssl"] is True

    def test_create_requires_password(self, stores):
        devices, customers = stores
        with pytest.raises(ValueError, match="登录密码"):
            service.save_device(devices, customers, None, _device_fields(password=""))

    def test_create_rejects_bad_host(self, stores):
        devices, customers = stores
        with pytest.raises(ValueError, match="管理地址非法"):
            service.save_device(devices, customers, None,
                                _device_fields(host="../etc/passwd"))

    def test_create_rejects_unknown_customer(self, stores):
        devices, customers = stores
        with pytest.raises(ValueError, match="归属客户不存在"):
            service.save_device(devices, customers, None,
                                _device_fields(customer="不存在的客户"))

    def test_create_rejects_duplicate(self, stores):
        devices, customers = stores
        service.save_device(devices, customers, None, _device_fields())
        with pytest.raises(ValueError, match="设备已存在"):
            service.save_device(devices, customers, None, _device_fields())

    def test_update_blank_password_keeps_old(self, stores):
        devices, customers = stores
        service.save_device(devices, customers, None, _device_fields())
        service.save_device(devices, customers, "核心交换机",
                            _device_fields(password="", host="10.0.0.2"))
        d = devices.get("核心交换机")
        assert d["password"] == "pass123" and d["host"] == "10.0.0.2"

    def test_update_skip_tls_maps_verify_ssl(self, stores):
        devices, customers = stores
        service.save_device(devices, customers, None, _device_fields())
        service.save_device(devices, customers, "核心交换机",
                            _device_fields(password="", verify_ssl=False))
        assert devices.get("核心交换机")["verify_ssl"] is False


class TestSaveCustomer:
    def test_create_and_count(self, stores):
        devices, customers = stores
        service.save_customer(customers, devices, None,
                              {"name": "甲公司", "contact": "张三"})
        service.save_device(devices, customers, None,
                            _device_fields(customer="甲公司"))
        assert service.device_count_by_customer(devices) == {"甲公司": 1}

    def test_rename_cascades_to_devices(self, stores):
        devices, customers = stores
        service.save_customer(customers, devices, None,
                              {"name": "甲公司", "contact": "张三"})
        service.save_device(devices, customers, None,
                            _device_fields(customer="甲公司"))
        service.save_customer(customers, devices, "甲公司",
                              {"name": "乙公司", "contact": "李四"})
        assert customers.get("乙公司") is not None
        assert devices.get("核心交换机")["customer"] == "乙公司"

    def test_empty_name_rejected(self, stores):
        devices, customers = stores
        with pytest.raises(ValueError, match="客户名称不能为空"):
            service.save_customer(customers, devices, None, {"name": "  "})


class TestTaskSummary:
    def test_counts(self):
        tasks = [{"status": "completed"}, {"status": "failed"},
                 {"status": "running"}, {"status": "pending"}, {}]
        assert service.task_summary(tasks) == {
            "pending": 1, "running": 1, "completed": 1, "failed": 1}


class TestReports:
    def test_safe_report_name(self):
        assert service.safe_report_name("a.html")
        for bad in ("", "../a.html", "x/../a.html", "a.json", "C:\\a.html"):
            assert not service.safe_report_name(bad)

    def test_list_and_load(self, out):
        name = _write_report(out)
        reports = service.list_reports(out)
        assert reports and reports[0]["name"] == name
        assert reports[0]["has_preview"] is True and reports[0]["has_ai"] is False
        data = service.load_report_data(name, out)
        assert data["devices"][0]["name"] == "核心交换机"

    def test_load_rejects_unsafe(self, out):
        with pytest.raises(ValueError):
            service.load_report_data("../x.html", out)

    def test_summary(self, out):
        name = _write_report(out)
        summary = service.report_summary(service.load_report_data(name, out))
        assert summary["total_pass"] == 1
        assert summary["total_fail"] == 1
        assert summary["total_unknown"] == 1
        assert len(summary["fail_items"]) == 1
        assert summary["fail_items"][0]["severity"] == "critical"

    def test_delete_reports(self, out):
        name = _write_report(out)
        count = service.delete_reports([name, "../evil.html"], out)
        assert count == 1
        assert not (out / name).exists()
        assert not (out / name.replace(".html", ".json")).exists()

    def test_format_ai_conclusion(self):
        text = service.format_ai_conclusion({
            "health_score": 90, "overall_risk": "low",
            "executive_summary": "整体健康",
            "key_findings": ["风扇异常"],
            "recommendations": "更换风扇",
        })
        assert "健康评分: 90" in text and "整体健康" in text
        assert "1. 风扇异常" in text and "更换风扇" in text


class TestExport:
    def test_export_word(self, out):
        name = _write_report(out)
        path = service.export_word(name, out)
        assert path.suffix == ".docx" and path.exists()

    def test_export_pdf_unavailable(self, out, monkeypatch):
        monkeypatch.setattr("patrol.reporter.pdf.check_pdf_capability",
                            lambda: {"word": False, "libreoffice": False})
        name = _write_report(out)
        with pytest.raises(RuntimeError, match="PDF 转换不可用"):
            service.export_pdf(name, out)


class TestAiAnalysis:
    def test_unsafe_name(self, out):
        with pytest.raises(ValueError):
            service.run_ai_analysis("../x.html", out)

    def test_missing_json(self, out):
        with pytest.raises(RuntimeError, match="缺少报告数据文件"):
            service.run_ai_analysis("nope.html", out)

    def test_not_configured(self, out, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # 无 config/ai.yaml → 默认未启用
        name = _write_report(out)
        with pytest.raises(RuntimeError, match="AI 分析未启用"):
            service.run_ai_analysis(name, out)

    def test_success_updates_json_and_html(self, out, monkeypatch):
        name = _write_report(out)
        monkeypatch.setattr("patrol.ai.analyze_report",
                            lambda report, cfg: {"executive_summary": "ok",
                                                 "health_score": 88})
        monkeypatch.setattr("patrol.ai.load_ai_config",
                            lambda: type("C", (), {"ready": True})())
        service.run_ai_analysis(name, out)
        data = json.loads((out / name.replace(".html", ".json"))
                          .read_text(encoding="utf-8"))
        assert data["ai_analysis"]["health_score"] == 88
        html = (out / name).read_text(encoding="utf-8")
        assert "ok" in html


class TestAiConfig:
    @pytest.fixture(autouse=True)
    def _clean_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for k in ("PATROL_AI_API_KEY", "PATROL_AI_BASE_URL", "PATROL_AI_MODEL"):
            monkeypatch.delenv(k, raising=False)

    def test_save_validation(self):
        with pytest.raises(ValueError, match="接口地址不能为空"):
            service.ai_save(True, "", "k", "m")
        with pytest.raises(ValueError, match="http"):
            service.ai_save(True, "ftp://x", "k", "m")

    def test_save_keeps_key_when_blank(self):
        service.ai_save(True, "https://api.deepseek.com", "sk-123456", "deepseek-chat")
        assert service.ai_load_raw()["api_key"] == "sk-123456"
        service.ai_save(True, "https://api.deepseek.com", "", "m2")
        raw = service.ai_load_raw()
        assert raw["api_key"] == "sk-123456" and raw["model"] == "m2"
        assert service.ai_masked_key().endswith("3456")

    def test_test_requires_fields(self):
        assert service.ai_test("", "k", "m")["ok"] is False
        assert service.ai_test("http://x", "", "m")["ok"] is False
        assert service.ai_test("http://x", "k", "")["ok"] is False

    def test_test_success(self, monkeypatch):
        class FakeClient:
            def __init__(self, cfg):
                pass

            def chat(self, messages):
                return "OK"

        monkeypatch.setattr("patrol.ai.client.LLMClient", FakeClient)
        result = service.ai_test("http://x", "k", "m")
        assert result["ok"] is True and "OK" in result["message"]


class TestUpdate:
    def test_check_update(self, monkeypatch):
        monkeypatch.setattr("patrol.update.check_for_update",
                            lambda: {"status": "available", "latest": "9.9.9",
                                     "url": "http://u/p.zip"})
        result = service.check_update()
        assert result["latest"] == "9.9.9" and result["checked_at"]

    def test_download_no_update(self, monkeypatch):
        monkeypatch.setattr("patrol.update.check_for_update",
                            lambda: {"status": "uptodate"})
        with pytest.raises(RuntimeError, match="没有可用更新"):
            service.download_update()

    def test_download_and_stage(self, monkeypatch):
        called = {}
        monkeypatch.setattr("patrol.updater.download_package",
                            lambda url, ver, expected_sha256="": called.setdefault("dl", ver))
        monkeypatch.setattr("patrol.updater.stage_update",
                            lambda z, ver="": called.setdefault("stage", ver))
        result = service.download_update({
            "status": "available", "latest": "1.2.3", "url": "http://u/p.zip"})
        assert result["status"] == "downloaded"
        assert called == {"dl": "1.2.3", "stage": "1.2.3"}

    def test_install_without_pending(self, monkeypatch):
        monkeypatch.setattr("patrol.updater.load_pending", lambda root=None: None)
        with pytest.raises(RuntimeError, match="没有待安装"):
            service.install_update()

    def test_install_now(self, monkeypatch):
        called = {}
        monkeypatch.setattr("patrol.updater.load_pending",
                            lambda root=None: {"version": "2.0.0"})
        monkeypatch.setattr("patrol.updater.install_now",
                            lambda root=None: called.setdefault("installed", True))
        assert service.install_update() == "2.0.0"
        assert called["installed"] is True


class TestAccount:
    @pytest.fixture(autouse=True)
    def _clean_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PATROL_WEB_PASSWORD", raising=False)
        monkeypatch.delenv("PATROL_WEB_USER", raising=False)

    def test_change_account_closed_loop(self):
        from patrol.api.auth import load_auth_config, verify_login

        load_auth_config()  # 播种默认 admin/admin123
        msg = service.change_account("admin123", None, "newpass456")
        assert "已更新" in msg
        assert verify_login("admin", "newpass456")
        assert not verify_login("admin", "admin123")

    def test_wrong_current_password(self):
        from patrol.api.auth import load_auth_config

        load_auth_config()
        with pytest.raises(ValueError):
            service.change_account("wrong", None, "x1234567")
