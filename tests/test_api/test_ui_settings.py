"""系统设置界面测试:产品信息/MIT/API Key/软件更新"""
from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from patrol.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """settings 模块读写相对路径 config/*,隔离到 tmp_path。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ai.yaml").write_text(
        "enabled: false\nbase_url: https://api.deepseek.com/v1\n"
        "api_key: sk-old1234567890abcd\nmodel: deepseek-chat\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "settings.yaml").write_text(
        "update_manifest_url: ''\n", encoding="utf-8"
    )
    yield tmp_path


class TestSettingsPage:
    def test_page_renders_product_info(self, client):
        resp = client.get("/ui/settings")
        assert resp.status_code == 200
        assert "系统设置" in resp.text
        assert "昊云网络巡检助手" in resp.text
        assert "作者" in resp.text and "昊云" in resp.text
        assert "370428679" in resp.text

    def test_page_shows_mit_license(self, client):
        resp = client.get("/ui/settings")
        assert "MIT License" in resp.text
        assert "Permission is hereby granted" in resp.text
        assert "允许二次开发" in resp.text

    def test_page_shows_update_button(self, client):
        resp = client.get("/ui/settings")
        assert "检查更新" in resp.text
        assert "/ui/settings/check-update" in resp.text

    def test_api_key_masked_on_page(self, client):
        resp = client.get("/ui/settings")
        assert "sk-old1234567890abcd" not in resp.text  # 明文不得回显
        assert "abcd" in resp.text  # 只露末 4 位

    def test_sidebar_entry_present(self, client):
        resp = client.get("/ui/settings")
        assert '/ui/settings' in resp.text


class TestSaveAiConfig:
    def test_save_full(self, client, isolated_config):
        resp = client.post("/ui/settings/ai", data={
            "enabled": "on",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "sk-newkey9999",
            "model": "glm-4-flash",
        }, follow_redirects=False)
        assert resp.status_code == 303
        data = yaml.safe_load(
            (isolated_config / "config" / "ai.yaml").read_text(encoding="utf-8")
        )
        assert data["enabled"] is True
        assert data["api_key"] == "sk-newkey9999"
        assert data["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
        assert data["model"] == "glm-4-flash"
        assert data["timeout"] == 120  # 默认字段补齐

    def test_blank_api_key_keeps_old(self, client, isolated_config):
        resp = client.post("/ui/settings/ai", data={
            "enabled": "on",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",
            "model": "deepseek-chat",
        }, follow_redirects=False)
        assert resp.status_code == 303
        data = yaml.safe_load(
            (isolated_config / "config" / "ai.yaml").read_text(encoding="utf-8")
        )
        assert data["api_key"] == "sk-old1234567890abcd"

    def test_enabled_without_base_url_rejected(self, client, isolated_config):
        resp = client.post("/ui/settings/ai", data={
            "enabled": "on", "base_url": "", "api_key": "", "model": "",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]

    def test_invalid_scheme_rejected(self, client, isolated_config):
        resp = client.post("/ui/settings/ai", data={
            "enabled": "on", "base_url": "ftp://x", "api_key": "", "model": "",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]

    def test_save_reflected_on_page(self, client, isolated_config):
        client.post("/ui/settings/ai", data={
            "enabled": "on", "base_url": "https://api.moonshot.cn/v1",
            "api_key": "sk-moonshot2026key", "model": "moonshot-v1-8k",
        }, follow_redirects=False)
        resp = client.get("/ui/settings?saved=ai")
        assert "moonshot-v1-8k" in resp.text
        assert "https://api.moonshot.cn/v1" in resp.text
        assert "sk-moonshot2026key" not in resp.text

    def test_save_preserves_comment_header(self, client, isolated_config):
        ai_path = isolated_config / "config" / "ai.yaml"
        ai_path.write_text(
            "# 使用说明:把 enabled 改为 true\n"
            "# 第二行注释\n"
            "enabled: false\napi_key: k1\n",
            encoding="utf-8",
        )
        client.post("/ui/settings/ai", data={
            "enabled": "on", "base_url": "https://api.deepseek.com/v1",
            "api_key": "", "model": "deepseek-chat",
        }, follow_redirects=False)
        text = ai_path.read_text(encoding="utf-8")
        assert "# 使用说明:把 enabled 改为 true" in text
        assert "# 第二行注释" in text


class TestUpdateFlow:
    def test_save_update_url(self, client, isolated_config):
        resp = client.post("/ui/settings/update-url", data={
            "update_url": "https://dl.example.com/manifest.json",
        }, follow_redirects=False)
        assert resp.status_code == 303
        data = yaml.safe_load(
            (isolated_config / "config" / "settings.yaml").read_text(encoding="utf-8")
        )
        assert data["update_manifest_url"] == "https://dl.example.com/manifest.json"

    def test_check_update_unconfigured(self, client):
        resp = client.post("/ui/settings/check-update")
        assert resp.status_code == 200
        assert "未配置更新源" in resp.text

    def test_check_update_available_closed_loop(self, client, isolated_config):
        # 闭环:保存本地清单 → 检查 → 页面显示新版本与下载按钮
        manifest = isolated_config / "manifest.json"
        manifest.write_text(json.dumps({
            "version": "9.9.9",
            "url": "https://dl.example.com/patrol.zip",
            "notes": "重大更新",
        }, ensure_ascii=False), encoding="utf-8")
        client.post("/ui/settings/update-url", data={"update_url": str(manifest)},
                    follow_redirects=False)
        resp = client.post("/ui/settings/check-update")
        assert resp.status_code == 200
        assert "发现新版本" in resp.text
        assert "9.9.9" in resp.text
        assert "重大更新" in resp.text
        assert "https://dl.example.com/patrol.zip" in resp.text  # 下载按钮

    def test_check_update_uptodate(self, client, isolated_config):
        manifest = isolated_config / "manifest.json"
        manifest.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
        client.post("/ui/settings/update-url", data={"update_url": str(manifest)},
                    follow_redirects=False)
        resp = client.post("/ui/settings/check-update")
        assert resp.status_code == 200
        assert "已是最新版本" in resp.text

    def test_check_update_error_bad_manifest(self, client, isolated_config):
        manifest = isolated_config / "manifest.json"
        manifest.write_text("oops", encoding="utf-8")
        client.post("/ui/settings/update-url", data={"update_url": str(manifest)},
                    follow_redirects=False)
        resp = client.post("/ui/settings/check-update")
        assert resp.status_code == 200
        assert "检查更新失败" in resp.text


class TestLlmPresets:
    def test_page_renders_vendor_presets(self, client):
        resp = client.get("/ui/settings")
        assert "厂商预设" in resp.text
        for name in ("DeepSeek", "智谱", "通义千问", "Kimi", "豆包", "文心", "星火",
                     "混元", "MiniMax", "百川", "硅基流动", "Ollama", "自定义"):
            assert name in resp.text, f"缺少预设: {name}"

    def test_presets_have_verified_base_urls(self, client):
        resp = client.get("/ui/settings")
        assert "https://api.deepseek.com" in resp.text
        assert "https://open.bigmodel.cn/api/paas/v4" in resp.text
        assert "https://qianfan.baidubce.com/v2" in resp.text   # 千帆是 /v2
        assert "https://ark.cn-beijing.volces.com/api/v3" in resp.text
        assert "https://dashscope.aliyuncs.com/compatible-mode/v1" in resp.text

    def test_match_preset_roundtrip(self):
        from patrol.ai.presets import match_preset

        assert match_preset("https://api.moonshot.cn/v1") == "kimi"
        assert match_preset("https://api.moonshot.cn/v1/") == "kimi"
        assert match_preset("https://api.deepseek.com/v1") == "deepseek"  # /v1 别名
        assert match_preset("https://qianfan.baidubce.com/v2") == "ernie"
        assert match_preset("https://unknown.example/v1") is None
        assert match_preset("") is None


class TestAiConnectivity:
    def _write_ai(self, tmp_path, key: str):
        (tmp_path / "config" / "ai.yaml").write_text(
            f"enabled: false\nbase_url: https://api.deepseek.com\n"
            f"api_key: \"{key}\"\nmodel: deepseek-chat\n",
            encoding="utf-8",
        )

    def test_missing_base_url(self, client):
        resp = client.post("/ui/settings/test-ai", data={
            "enabled": "on", "base_url": "", "api_key": "sk-x", "model": "m",
        })
        assert "请先选择厂商或填写接口地址" in resp.text

    def test_missing_key(self, client, isolated_config):
        self._write_ai(isolated_config, "")
        resp = client.post("/ui/settings/test-ai", data={
            "enabled": "on", "base_url": "https://api.deepseek.com",
            "api_key": "", "model": "deepseek-chat",
        })
        assert "请先填写 API Key" in resp.text

    def test_missing_model(self, client):
        resp = client.post("/ui/settings/test-ai", data={
            "enabled": "on", "base_url": "https://api.deepseek.com",
            "api_key": "sk-x", "model": "",
        })
        assert "请先填写模型名" in resp.text

    def test_connectivity_success_and_not_saved(self, client, isolated_config):
        class FakeLLM:
            def __init__(self, cfg):
                self.cfg = cfg

            def chat(self, messages, json_mode=False):
                return "OK"

        import patrol.ai.client as client_mod
        client_mod.LLMClient = FakeLLM  # noqa
        try:
            resp = client.post("/ui/settings/test-ai", data={
                "enabled": "on", "base_url": "https://api.deepseek.com",
                "api_key": "sk-temptest", "model": "deepseek-chat",
            })
        finally:
            from patrol.ai.client import LLMClient as Real
            client_mod.LLMClient = Real
        assert "连接成功" in resp.text and "OK" in resp.text
        data = yaml.safe_load(
            (isolated_config / "config" / "ai.yaml").read_text(encoding="utf-8")
        )
        assert data["api_key"] == "sk-old1234567890abcd"  # 测试不落盘

    def test_connectivity_failure_shows_error(self, client, monkeypatch):
        from patrol.ai.client import LLMError

        class FakeLLM:
            def __init__(self, cfg):
                pass

            def chat(self, messages, json_mode=False):
                raise LLMError("401 Unauthorized")

        monkeypatch.setattr("patrol.ai.client.LLMClient", FakeLLM)
        resp = client.post("/ui/settings/test-ai", data={
            "enabled": "on", "base_url": "https://api.deepseek.com",
            "api_key": "sk-bad", "model": "deepseek-chat",
        })
        assert "连接失败" in resp.text and "401" in resp.text


class TestAutoUpdateUi:
    def _make_pkg_zip(self, tmp_path):
        import zipfile

        zpath = tmp_path / "update-pkg.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("昊云网络巡检助手/启动巡检助手.exe", b"MZ-new-build")
            zf.writestr("昊云网络巡检助手/使用说明.txt", b"readme")
        return zpath

    def _point_manifest(self, client, tmp_path, **fields):
        data = {"version": "9.9.9", "url": "", "notes": "auto update test"}
        data.update(fields)
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        client.post("/ui/settings/update-url",
                    data={"update_url": str(manifest)}, follow_redirects=False)

    def test_download_then_install_closed_loop(self, client, isolated_config):
        zpath = self._make_pkg_zip(isolated_config)
        self._point_manifest(client, isolated_config, url=str(zpath))

        resp = client.post("/ui/settings/download-update")
        assert resp.status_code == 200
        assert "已下载并校验" in resp.text
        assert "重启并安装" in resp.text

        staging = isolated_config / "update" / "staging"
        assert (staging / "启动巡检助手.exe").read_bytes() == b"MZ-new-build"
        assert not (staging / "config").exists()  # 用户数据永不进入暂存区
        assert (isolated_config / "update" / "pending.json").exists()

        # 开发模式安装 → 明确提示仅绿色包支持(脚本不启动)
        resp2 = client.post("/ui/settings/install-update")
        assert "源码运行模式" in resp2.text

    def test_download_rejected_when_uptodate(self, client, isolated_config):
        zpath = self._make_pkg_zip(isolated_config)
        self._point_manifest(client, isolated_config,
                             version="0.1.0", url=str(zpath))
        resp = client.post("/ui/settings/download-update")
        assert "当前没有可用更新" in resp.text

    def test_download_sha256_mismatch_shows_error(self, client, isolated_config):
        zpath = self._make_pkg_zip(isolated_config)
        self._point_manifest(client, isolated_config, url=str(zpath),
                             sha256="0" * 64)
        resp = client.post("/ui/settings/download-update")
        assert "校验失败" in resp.text

    def test_install_without_pending_shows_error(self, client):
        resp = client.post("/ui/settings/install-update")
        assert "没有待安装的更新包" in resp.text

    def test_pending_banner_on_settings_page(self, client, isolated_config):
        zpath = self._make_pkg_zip(isolated_config)
        self._point_manifest(client, isolated_config, url=str(zpath))
        client.post("/ui/settings/download-update")
        resp = client.get("/ui/settings")
        assert "已下载 v9.9.9 更新包" in resp.text
