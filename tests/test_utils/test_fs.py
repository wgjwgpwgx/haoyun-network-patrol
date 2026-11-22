"""原子写入工具测试(问题 004:YAML/JSON 非原子写)"""
from __future__ import annotations

from patrol.utils.fs import atomic_write_text


class TestAtomicWriteText:
    def test_creates_file_with_content(self, tmp_path):
        p = tmp_path / "a.yaml"
        atomic_write_text(p, "hello\n")
        assert p.read_text(encoding="utf-8") == "hello\n"
        assert not p.with_name("a.yaml.tmp").exists()

    def test_replaces_existing(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text("old", encoding="utf-8")
        atomic_write_text(p, "new")
        assert p.read_text(encoding="utf-8") == "new"
        assert not p.with_name("a.yaml.tmp").exists()

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "sub" / "dir" / "a.yaml"
        atomic_write_text(p, "x")
        assert p.read_text(encoding="utf-8") == "x"
