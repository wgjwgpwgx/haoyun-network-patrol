"""安全加固回归:交接包越界写入、替换导入丢数据、登录配置损坏、更新包校验、规则引擎取不到值"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from patrol import knowledge as kb
from patrol.analyzer.engine import RuleEngine
from patrol.drivers.base import ParsedResult
from patrol.models import CheckStatus
from patrol.updater import UpdateError, download_package, update_dir


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 交接包、auth.yaml 都按相对路径落盘
    return tmp_path


def _zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


class TestHandoffPackageIsUntrusted:
    """交接包是人与人之间交换的文件:成员名不可信。"""

    def test_members_escaping_target_dir_are_rejected(self, sandbox):
        (sandbox / "config" / "rules").mkdir(parents=True)
        victim = sandbox / "victim.txt"
        victim.write_text("original", encoding="utf-8")
        zpath = _zip(sandbox / "evil.zip", {
            "config/rules/../../victim.txt": "pwned",   # 越界覆盖任意文件
            "config/rules/../../auth.yaml": "pwned",
            "config/rules/evil.py": "print(1)",         # 非 yaml
            "parser_copilot/../../x.yaml": "pwned",
            "config/rules/good.yaml": "rules: []",      # 正常成员
        })

        counts = kb.import_all(zpath)

        assert counts["rejected"] == 4 and counts["rules"] == 1
        assert victim.read_text(encoding="utf-8") == "original"
        assert not (sandbox / "auth.yaml").exists()
        assert not (sandbox / "x.yaml").exists()
        assert not (sandbox / "config" / "rules" / "evil.py").exists()
        assert (sandbox / "config" / "rules" / "good.yaml").exists()

    def test_legitimate_package_round_trips(self, sandbox):
        kb.import_text("display version\nHUAWEI S5735", "客户A", "设备A")
        package = kb.export_all(sandbox / "handoff.zip")
        assert package.exists()

        kb.delete_device("客户A", "设备A")
        assert kb.list_snapshots("客户A", "设备A") == []

        counts = kb.import_all(package)
        assert counts["rejected"] == 0
        assert len(kb.list_snapshots("客户A", "设备A")) == 1


class TestReplaceImportKeepsOldDataOnFailure:
    """"替换导入"必须先确认新资料导入成功,再清旧资料。"""

    def _client(self):
        from fastapi.testclient import TestClient
        import patrol.api.app as app_module
        return TestClient(app_module.app)

    def test_broken_file_keeps_existing_snapshots(self, sandbox):
        kb.import_text("display version\nHUAWEI S5735", "客户A", "设备A")
        before = [p.name for p in kb.snapshot_paths("客户A", "设备A")]
        assert len(before) == 1

        r = self._client().post(
            "/ui/knowledge/import",
            data={"customer": "客户A", "device": "设备A", "replace": "on"},
            files={"file": ("broken.docx", b"this is not a docx",
                            "application/octet-stream")},
            follow_redirects=False)

        assert r.status_code == 303 and "error=" in r.headers["location"]
        assert [p.name for p in kb.snapshot_paths("客户A", "设备A")] == before, \
            "导入失败时旧资料被删了"

    def test_successful_replace_swaps_old_for_new(self, sandbox):
        kb.import_text("display clock\n2026-01-01", "客户A", "设备A")

        r = self._client().post(
            "/ui/knowledge/import",
            data={"customer": "客户A", "device": "设备A", "replace": "on",
                  "text": "display version\nHUAWEI S5735"},
            follow_redirects=False)

        assert r.status_code == 303 and "error=" not in r.headers["location"]
        # 只剩一份快照,且装的是新资料(快照文件名只精确到秒,新旧可能同名覆盖)
        import json
        snaps = kb.list_snapshots("客户A", "设备A")
        assert len(snaps) == 1
        record = kb.load_snapshot("客户A", "设备A", snaps[0]["file"])
        text = json.dumps(record, ensure_ascii=False)
        assert "HUAWEI S5735" in text and "display clock" not in text


class TestRemoteUpdatePackageNeedsChecksum:
    def test_remote_url_without_sha256_is_refused(self, sandbox):
        with pytest.raises(UpdateError, match="sha256"):
            download_package("https://updates.example.com/pkg.zip", "9.9.9",
                             root=sandbox)
        assert not (update_dir(sandbox) / "downloads").exists()

    def test_local_file_without_checksum_is_still_allowed(self, sandbox):
        src = sandbox / "pkg.zip"
        src.write_bytes(b"local package")
        assert download_package(str(src), "9.9.9", root=sandbox).exists()


class TestEngineDoesNotPassWhenValueIsMissing:
    """true/false 运算符在取不到指标时不能当"未触发"——那是把"不知道"判成通过。"""

    @staticmethod
    def _evaluate(operator: str, parsed: dict) -> CheckStatus:
        rules = RuleEngine.parse_rules({"rules": [{
            "id": "T", "check_name": "telnet_service", "name": "x",
            "severity": "warning", "vendors": ["*"], "device_types": ["*"],
            "metric": "telnet_enabled", "operator": operator}]})
        return RuleEngine(rules).evaluate(ParsedResult(
            name="telnet_service", category="c", command="cmd",
            raw_output="", parsed=parsed, success=True)).status

    def test_true_with_missing_value_is_unknown(self):
        assert self._evaluate("true", {}) == CheckStatus.UNKNOWN

    def test_false_with_missing_value_is_unknown(self):
        assert self._evaluate("false", {}) == CheckStatus.UNKNOWN

    def test_present_values_are_still_judged(self):
        assert self._evaluate("true", {"telnet_enabled": True}) == CheckStatus.FAIL
        assert self._evaluate("true", {"telnet_enabled": False}) == CheckStatus.PASS

    def test_exists_operator_treats_missing_as_absent(self):
        rule = RuleEngine.parse_rules({"rules": [{
            "id": "E", "check_name": "x", "name": "x", "severity": "warning",
            "vendors": ["*"], "device_types": ["*"], "metric": "acl",
            "operator": "exists"}]})
        item = RuleEngine(rule).evaluate(ParsedResult(
            name="x", category="c", command="cmd", raw_output="", parsed={},
            success=True))
        assert item.status == CheckStatus.PASS
