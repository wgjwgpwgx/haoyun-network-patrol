"""AI 配置加载测试"""
from __future__ import annotations

import pytest

from patrol.ai.config import AIConfig, load_ai_config


class TestDefaults:
    def test_default_not_ready(self):
        assert AIConfig().ready is False

    def test_ready_when_enabled_with_key(self):
        assert AIConfig(enabled=True, api_key="sk-x").ready is True

    def test_blank_key_not_ready(self):
        assert AIConfig(enabled=True, api_key="   ").ready is False


class TestYamlLoad:
    def test_load_from_file(self, tmp_path):
        cfg_file = tmp_path / "ai.yaml"
        cfg_file.write_text(
            "enabled: true\nbase_url: http://localhost:11434/v1\n"
            "api_key: k1\nmodel: qwen2.5:7b\ntimeout: 60\n",
            encoding="utf-8",
        )
        cfg = load_ai_config(cfg_file)
        assert cfg.enabled is True
        assert cfg.base_url == "http://localhost:11434/v1"
        assert cfg.model == "qwen2.5:7b"
        assert cfg.timeout == 60
        assert cfg.ready is True

    def test_missing_file_uses_defaults(self, tmp_path):
        cfg = load_ai_config(tmp_path / "nope.yaml")
        assert cfg.enabled is False

    def test_bad_yaml_uses_defaults(self, tmp_path):
        cfg_file = tmp_path / "ai.yaml"
        cfg_file.write_text("enabled: [unclosed\n", encoding="utf-8")
        cfg = load_ai_config(cfg_file)
        assert cfg.enabled is False


class TestEnvOverride:
    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "ai.yaml"
        cfg_file.write_text(
            "enabled: false\napi_key: from-yaml\n", encoding="utf-8"
        )
        monkeypatch.setenv("PATROL_AI_ENABLED", "true")
        monkeypatch.setenv("PATROL_AI_API_KEY", "from-env")
        monkeypatch.setenv("PATROL_AI_MODEL", "glm-4-flash")
        cfg = load_ai_config(cfg_file)
        assert cfg.enabled is True
        assert cfg.api_key == "from-env"
        assert cfg.model == "glm-4-flash"

    def test_env_disable(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "ai.yaml"
        cfg_file.write_text("enabled: true\napi_key: k\n", encoding="utf-8")
        monkeypatch.setenv("PATROL_AI_ENABLED", "false")
        assert load_ai_config(cfg_file).enabled is False
