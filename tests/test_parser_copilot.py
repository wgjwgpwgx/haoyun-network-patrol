"""解析器 Copilot 测试(P2)"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from patrol.parser_copilot import (
    apply_saved_rule, generate_with_ai, parse_ai_rules, parse_with_rules,
    save_rule,
)


class TestDeclarativeParse:
    def test_fields_extracted(self):
        raw = "CPU Usage Stat:  27%  Max: 81%"
        fields = {"usage_percent": {"regex": r"CPU Usage[^:]*:\s*(\d+)",
                                    "type": "int"},
                  "max_usage": {"regex": r"Max:\s*(\d+)", "type": "int"}}
        out = parse_with_rules(raw, fields)
        assert out == {"usage_percent": 27, "max_usage": 81}

    def test_missing_field_omitted(self):
        out = parse_with_rules("nothing here",
                               {"x": {"regex": r"(\d+)", "type": "int"}})
        assert out == {}

    def test_bad_regex_ignored(self):
        out = parse_with_rules("1", {"x": {"regex": "([", "type": "int"},
                                     "y": {"regex": r"(\d)", "type": "int"}})
        assert out == {"y": 1}


class TestRulesStore:
    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        save_rule("huawei", "vrp_switch", "temperature",
                  {"value": {"regex": r"(\d+) C", "type": "int"}})
        # run_inspection 回退入口
        pr = apply_saved_rule("huawei", "vrp_switch", "temperature",
                              "Slot1 42 C")
        assert pr is not None and pr.parsed["value"] == 42
        # 覆盖同项保留他项
        save_rule("huawei", "vrp_switch", "fan_status",
                  {"total": {"regex": r"Fan", "type": "str"}})
        pr2 = apply_saved_rule("huawei", "vrp_switch", "temperature", "50 C")
        assert pr2.parsed["value"] == 50
        # 无规则返回 None
        assert apply_saved_rule("h3c", "s7506e", "nothing", "x") is None


class TestAIRules:
    def test_parse_ai_reply_with_fence(self):
        reply = '```json\n{"fields": {"u": {"regex": "(\\\\d+)", '
        reply += '"type": "int"}}}\n```'
        rules = parse_ai_rules(reply)
        assert "u" in rules

    def test_parse_ai_bad_json(self):
        with pytest.raises(ValueError, match="JSON"):
            parse_ai_rules("not json at all")

    def test_parse_ai_invalid_regex_filtered(self):
        reply = json.dumps({"fields": {
            "bad": {"regex": "(["},
            "ok": {"regex": r"(\d+)", "type": "int"}}})
        rules = parse_ai_rules(reply)
        assert set(rules) == {"ok"}

    def test_generate_with_ai_mock(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from patrol.ai import config as ai_config

        cfg = MagicMock(enabled=True)
        client = MagicMock()
        client.chat.return_value = json.dumps({"fields": {
            "usage_percent": {"regex": "CPU[^\\d]*(\\d+)", "type": "int"}}})
        with patch.object(ai_config, "load_ai_config", return_value=cfg), \
             patch("patrol.ai.client.LLMClient", return_value=client):
            result = generate_with_ai("cpu_usage", "CPU  : 33 percent")
        assert result["ok"] is True
        assert result["sample"]["usage_percent"] == 33

    def test_generate_ai_disabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = MagicMock(enabled=False)
        from patrol.ai import config as ai_config
        with patch.object(ai_config, "load_ai_config", return_value=cfg):
            result = generate_with_ai("cpu_usage", "x")
        assert result["ok"] is False and "未启用" in result["error"]


class TestFallbackInInspection:
    def test_unknown_falls_back_to_saved_rule(self, tmp_path, monkeypatch):
        """驱动解析失败 → 已入库 Copilot 规则命中 → PASS。"""
        monkeypatch.chdir(tmp_path)
        from patrol.analyzer.engine import RuleEngine
        from patrol.cli import run_inspection
        from patrol.collector.ssh import SSHCollector
        from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
        from patrol.models import DeviceAsset

        save_rule("huawei", "vrp_switch", "temperature",
                  {"value": {"regex": r"Temp: (\d+)", "type": "int"},
                   "abnormal_count": {"regex": r"alarms: (\d+)",
                                      "type": "int"}})

        def fake_execute(self, command, timeout=60):
            if "temperature" in command:
                return "Slot1 Temp: 44, alarms: 0"
            return ""  # 其余命令空回显(UNKNOWN,正常)

        with patch.object(SSHCollector, "connect"), \
             patch.object(SSHCollector, "disconnect"), \
             patch.object(SSHCollector, "execute", fake_execute):
            asset = DeviceAsset(name="t", host="10.0.0.1", vendor="huawei",
                                device_type="vrp_switch",
                                username="u", password="p")
            rules_path = Path(__file__).parent.parent / "config" / \
                "rules" / "default.yaml"
            report = run_inspection(asset, HuaweiVRPSwitchDriver(),
                                    RuleEngine(RuleEngine.load_file(
                                        str(rules_path))))
        temp = next(i for i in report.check_items
                    if i.name == "temperature")
        assert temp.status.value == "PASS"  # R006: abnormal_count=0
        assert temp.details["value"] == 44
