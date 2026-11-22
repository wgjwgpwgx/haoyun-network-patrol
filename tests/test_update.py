"""软件更新服务测试(patron.update)"""
from __future__ import annotations

import json

import pytest

from patrol.update import (
    check_for_update,
    load_update_url,
    parse_version,
    save_update_url,
)


class TestParseVersion:
    def test_plain(self):
        assert parse_version("0.2.0") == (0, 2, 0)

    def test_v_prefix(self):
        assert parse_version("v0.2.0") == (0, 2, 0)

    def test_comparison_orders_numerically(self):
        assert parse_version("0.10.0") > parse_version("0.2.0")
        assert parse_version("v1.0") > parse_version("0.9.9")
        assert parse_version("1.0.0") == parse_version("v1.0.0")

    def test_empty_or_garbage(self):
        assert parse_version("") == (0,)
        assert parse_version("abc") == (0,)


class TestUpdateUrl:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_update_url(tmp_path / "nope.yaml") == ""

    def test_save_then_load(self, tmp_path):
        path = tmp_path / "settings.yaml"
        save_update_url("https://example.com/manifest.json", path)
        assert load_update_url(path) == "https://example.com/manifest.json"

    def test_save_preserves_other_keys(self, tmp_path):
        path = tmp_path / "settings.yaml"
        path.write_text("update_manifest_url: ''\nother: keepme\n", encoding="utf-8")
        save_update_url("https://x/y.json", path)
        text = path.read_text(encoding="utf-8")
        assert "keepme" in text
        assert "https://x/y.json" in text

    def test_default_path_uses_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        save_update_url("http://a/b.json")
        assert load_update_url() == "http://a/b.json"
        assert (tmp_path / "config" / "settings.yaml").exists()


class TestCheckForUpdate:
    def _manifest(self, tmp_path, **over):
        data = {"version": "0.2.0", "url": "https://dl/x.zip", "notes": "新增设置模块"}
        data.update(over)
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_unconfigured(self):
        r = check_for_update(manifest_url="")
        assert r["status"] == "unconfigured"
        assert r["message"]

    def test_available_local_file(self, tmp_path):
        r = check_for_update(manifest_url=self._manifest(tmp_path), current="0.1.0")
        assert r["status"] == "available"
        assert r["latest"] == "0.2.0"
        assert r["url"] == "https://dl/x.zip"
        assert r["notes"] == "新增设置模块"

    def test_uptodate(self, tmp_path):
        r = check_for_update(manifest_url=self._manifest(tmp_path), current="0.2.0")
        assert r["status"] == "uptodate"

    def test_uptodate_when_local_is_newer(self, tmp_path):
        r = check_for_update(manifest_url=self._manifest(tmp_path), current="0.3.0")
        assert r["status"] == "uptodate"

    def test_missing_version_is_error(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"url": "x"}), encoding="utf-8")
        r = check_for_update(manifest_url=str(p), current="0.1.0")
        assert r["status"] == "error"

    def test_bad_json_is_error(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text("not json", encoding="utf-8")
        r = check_for_update(manifest_url=str(p), current="0.1.0")
        assert r["status"] == "error"
        assert "检查更新失败" in r["message"]

    def test_missing_file_is_error(self, tmp_path):
        r = check_for_update(manifest_url=str(tmp_path / "nope.json"), current="0.1.0")
        assert r["status"] == "error"

    def test_non_dict_manifest_is_error(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text(json.dumps(["a"]), encoding="utf-8")
        r = check_for_update(manifest_url=str(p), current="0.1.0")
        assert r["status"] == "error"
