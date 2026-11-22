"""AI 分析 Web 路由 + 巡检任务自动分析 集成测试(全部 mock,不出网)"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrol.api.app import app
from patrol.api.store import CustomerStore, DeviceStore, TaskStore
from patrol.api.tasks import TaskManager
from patrol.models import (
    CheckItem,
    CheckStatus,
    DeviceAsset,
    DeviceReport,
)

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "default.yaml"

MOCK_AI_RESULT = {
    "executive_summary": "整体存在 1 项关键故障。",
    "health_score": 60,
    "overall_risk": "high",
    "key_findings": [{
        "device": "测试交换机", "issue": "接口 DOWN", "severity": "high",
        "impact": "业务受影响", "recommendation": "检查线路",
    }],
    "recommendations": ["立即排查接口"],
    "maintenance_suggestions": [],
    "meta": {"model": "mock-model", "analyzed_at": "2026-01-01T00:00:00",
             "device_count": 1},
}


@pytest.fixture(autouse=True)
def isolated_ui_stores(tmp_path, monkeypatch):
    """隔离存储 + 输出目录。"""
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "devices.yaml"
    config_path.write_text("devices: []\n", encoding="utf-8")

    ds = DeviceStore(str(config_path))
    cs = CustomerStore(str(tmp_path / "customers.yaml"))
    ts = TaskStore()
    tm = TaskManager(ds, ts, str(RULES), str(tmp_path / "output"))

    import patrol.api.app as app_module
    import patrol.api.ui as ui_module

    saved = (app_module._device_store, app_module._task_store,
             app_module._task_manager, app_module._customer_store,
             ui_module._device_store, ui_module._task_store,
             ui_module._customer_store)
    app_module._device_store = ds
    app_module._task_store = ts
    app_module._task_manager = tm
    app_module._customer_store = cs
    ui_module._device_store = ds
    ui_module._task_store = ts
    ui_module._customer_store = cs

    yield {"ds": ds, "cs": cs, "ts": ts, "tm": tm}

    (app_module._device_store, app_module._task_store,
     app_module._task_manager, app_module._customer_store,
     ui_module._device_store, ui_module._task_store,
     ui_module._customer_store) = saved


@pytest.fixture
def client():
    return TestClient(app)


def _make_report(tmp_path, with_ai=False) -> Path:
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    data = {
        "title": "测试报告",
        "generated_at": "2026-01-01T00:00:00",
        "total_devices": 1,
        "has_failures": True,
        "devices": [{
            "name": "测试交换机", "customer": "", "host": "192.168.1.1",
            "vendor": "h3c", "device_type": "comware_switch",
            "model": "", "software_version": "", "uptime": "",
            "collected_at": "2026-01-01T00:00:00", "error": None,
            "pass_count": 1, "fail_count": 1, "unknown_count": 0,
            "summary": "PASS: 1, FAIL: 1, UNKNOWN: 0",
            "check_items": [
                {"name": "iface", "category": "接口", "command": "display int",
                 "raw_output": "GE1/0/2 DOWN", "status": "FAIL",
                 "message": "1 个接口 DOWN",
                 "details": {"severity": "critical", "suggestion": ""}},
            ],
        }],
    }
    if with_ai:
        data["ai_analysis"] = MOCK_AI_RESULT
    (out / "patrol_x.html").write_text("<html>old</html>", encoding="utf-8")
    (out / "patrol_x.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return out


@pytest.fixture
def ai_ready(monkeypatch):
    """让 AI 配置处于可用状态,并 mock 掉真正的 LLM 调用。"""
    from patrol.ai.config import AIConfig
    cfg = AIConfig(enabled=True, api_key="test")
    monkeypatch.setattr("patrol.ai.load_ai_config", lambda *a, **k: cfg)
    monkeypatch.setattr(
        "patrol.ai.analyze_report", lambda report, config=None: MOCK_AI_RESULT
    )
    return cfg


class TestAIAnalysisRoute:
    def test_success_updates_json_and_html(self, client, tmp_path, ai_ready):
        _make_report(tmp_path)
        resp = client.post(
            "/ui/reports/patrol_x.html/ai-analysis", follow_redirects=False
        )
        assert resp.status_code == 303
        assert "/preview" in resp.headers["location"]

        data = json.loads(
            (tmp_path / "output" / "patrol_x.json").read_text(encoding="utf-8")
        )
        assert data["ai_analysis"]["health_score"] == 60
        html = (tmp_path / "output" / "patrol_x.html").read_text(encoding="utf-8")
        assert "AI 综合分析" in html
        assert "接口 DOWN" in html

    def test_not_configured_shows_error(self, client, tmp_path, monkeypatch):
        from patrol.ai.config import AIConfig
        monkeypatch.setattr(
            "patrol.ai.load_ai_config", lambda *a, **k: AIConfig()
        )
        _make_report(tmp_path)
        resp = client.post(
            "/ui/reports/patrol_x.html/ai-analysis", follow_redirects=False
        )
        assert resp.status_code == 303
        assert "ai_error" in resp.headers["location"]

    def test_missing_json_redirects_back(self, client, tmp_path, ai_ready):
        out = tmp_path / "output"
        out.mkdir(exist_ok=True)
        (out / "patrol_y.html").write_text("<html></html>", encoding="utf-8")
        resp = client.post(
            "/ui/reports/patrol_y.html/ai-analysis", follow_redirects=False
        )
        assert resp.status_code == 303
        assert "ai_error" in resp.headers["location"]

    def test_traversal_blocked(self, client, ai_ready):
        resp = client.post(
            "/ui/reports/..%2Fdevices.yaml/ai-analysis", follow_redirects=False
        )
        assert resp.status_code in (303, 404)


class TestReportListAI:
    def test_list_shows_ai_button_state(self, client, tmp_path, ai_ready):
        _make_report(tmp_path, with_ai=True)
        (tmp_path / "output" / "patrol_n.html").write_text(
            "<html></html>", encoding="utf-8"
        )
        (tmp_path / "output" / "patrol_n.json").write_text(
            '{"title": "t", "devices": []}', encoding="utf-8"
        )
        html = client.get("/ui/reports").text
        assert "ai-analysis" in html          # AI 启用时展示分析按钮
        assert "重新 AI 分析" in html         # 已分析的显示重新分析

    def test_ai_disabled_hides_button(self, client, tmp_path, monkeypatch):
        from patrol.ai.config import AIConfig
        monkeypatch.setattr(
            "patrol.ai.load_ai_config", lambda *a, **k: AIConfig()
        )
        _make_report(tmp_path, with_ai=True)
        html = client.get("/ui/reports").text
        assert "ai-analysis" not in html


class TestPreviewAI:
    def test_preview_renders_ai_section(self, client, tmp_path):
        _make_report(tmp_path, with_ai=True)
        html = client.get("/ui/reports/patrol_x.html/preview").text
        assert "AI 综合分析" in html
        assert "健康评分" in html
        assert "关键发现" in html

    def test_preview_without_ai_shows_placeholder_when_enabled(
        self, client, tmp_path, ai_ready
    ):
        _make_report(tmp_path)
        html = client.get("/ui/reports/patrol_x.html/preview").text
        assert "立即分析" in html

    def test_preview_ai_error_displayed(self, client, tmp_path):
        _make_report(tmp_path)
        html = client.get(
            "/ui/reports/patrol_x.html/preview?ai_error=测试错误"
        ).text
        assert "测试错误" in html


class TestTaskAutoAnalysis:
    def test_task_attaches_ai_to_report(
        self, client, isolated_ui_stores, ai_ready, monkeypatch
    ):
        import patrol.api.tasks as tasks_mod

        stores = isolated_ui_stores
        stores["ds"].create({
            "name": "auto-dev", "host": "192.168.1.9", "vendor": "h3c",
            "device_type": "comware_switch", "login_method": "ssh",
            "port": 22, "username": "u", "password": "p",
            "timeout": 10, "command_timeout": 10, "enabled": True,
        })

        def fake_inspection(asset, driver, engine):
            dev = DeviceReport(asset=DeviceAsset(
                name=asset.name, host=asset.host, vendor=asset.vendor,
                device_type=asset.device_type,
            ))
            dev.check_items = [CheckItem(
                name="iface", category="接口", command="display int",
                raw_output="GE1/0/1 UP", status=CheckStatus.PASS,
                message="正常",
            )]
            return dev

        monkeypatch.setattr(tasks_mod, "run_inspection", fake_inspection)
        monkeypatch.setattr(tasks_mod, "get_driver", lambda v, t: object())

        task = stores["tm"].create_task("auto-dev")
        for _ in range(50):
            if stores["ts"].get(task.task_id)["status"] in (
                "completed", "failed"
            ):
                break
            time.sleep(0.1)
        final = stores["ts"].get(task.task_id)
        assert final["status"] == "completed"
        assert final["ai_analyzed"] is True

        report_file = final["report_file"]
        data = json.loads(
            (Path("output") / report_file.replace(".html", ".json"))
            .read_text(encoding="utf-8")
        )
        assert data["ai_analysis"]["overall_risk"] == "high"
        html = (Path("output") / report_file).read_text(encoding="utf-8")
        assert "AI 综合分析" in html

    def test_task_survives_ai_failure(
        self, client, isolated_ui_stores, monkeypatch
    ):
        import patrol.api.tasks as tasks_mod
        from patrol.ai.config import AIConfig

        stores = isolated_ui_stores
        cfg = AIConfig(enabled=True, api_key="k")
        monkeypatch.setattr("patrol.ai.load_ai_config", lambda *a, **k: cfg)

        def boom(report, config=None):
            raise RuntimeError("LLM 服务宕机")

        monkeypatch.setattr("patrol.ai.analyze_report", boom)

        stores["ds"].create({
            "name": "auto-dev2", "host": "192.168.1.10", "vendor": "h3c",
            "device_type": "comware_switch", "login_method": "ssh",
            "port": 22, "username": "u", "password": "p",
            "timeout": 10, "command_timeout": 10, "enabled": True,
        })

        def fake_inspection(asset, driver, engine):
            return DeviceReport(asset=DeviceAsset(
                name=asset.name, host=asset.host, vendor=asset.vendor,
                device_type=asset.device_type,
            ))

        monkeypatch.setattr(tasks_mod, "run_inspection", fake_inspection)
        monkeypatch.setattr(tasks_mod, "get_driver", lambda v, t: object())

        task = stores["tm"].create_task("auto-dev2")
        for _ in range(50):
            if stores["ts"].get(task.task_id)["status"] in (
                "completed", "failed"
            ):
                break
            time.sleep(0.1)
        final = stores["ts"].get(task.task_id)
        assert final["status"] == "completed"   # AI 失败不影响巡检
        assert final["ai_analyzed"] is False
