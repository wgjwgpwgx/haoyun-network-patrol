"""表格勾选列与批量操作目标行

覆盖 2026-09-23 用户反馈"删除要加个选中框,不然批量删除没法多选"的控件层实现。
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from patrol.desktop.widgets import (  # noqa: E402
    CHECK_OFF,
    CHECK_ON,
    checked_rows,
    insert_row,
    keep_checks,
    make_tree,
    set_check,
    severity_cn,
    target_rows,
    toggle_all_checks,
    toggle_check,
)


@pytest.fixture
def root():
    import time

    for attempt in range(5):
        try:
            r = tk.Tk()
            r.withdraw()
            break
        except tk.TclError:
            if attempt == 4:
                raise
            time.sleep(0.3)
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def tree(root):
    t, _wrap = make_tree(root, [("name", "名称", 80), ("host", "地址", 80)],
                         height=5, checkbox=True)
    insert_row(t, ("A", "1.1.1.1"), iid="a")
    insert_row(t, ("B", "2.2.2.2"), iid="b")
    insert_row(t, ("C", "3.3.3.3"), iid="c")
    return t


class TestCheckColumn:
    def test_insert_marks_unchecked(self, tree):
        assert tree["columns"][0] == "chk"
        assert [tree.set(i, "chk") for i in tree.get_children()] == [CHECK_OFF] * 3

    def test_toggle_check(self, tree):
        toggle_check(tree, "b")
        assert checked_rows(tree) == ["b"]
        assert tree.set("b", "chk") == CHECK_ON
        toggle_check(tree, "b")
        assert checked_rows(tree) == []

    def test_toggle_all_checks_both_ways(self, tree):
        toggle_all_checks(tree)  # 全部未勾选 → 全选
        assert set(checked_rows(tree)) == {"a", "b", "c"}
        toggle_all_checks(tree)  # 已有勾选 → 全部取消
        assert checked_rows(tree) == []

    def test_target_rows_prefers_checked(self, tree):
        tree.selection_set("c")
        assert target_rows(tree) == ["c"]  # 无勾选 → 选中行
        set_check(tree, "a", True)
        set_check(tree, "b", True)
        assert target_rows(tree) == ["a", "b"]  # 有勾选 → 勾选行优先

    def test_keep_checks_survives_reinsert(self, tree):
        set_check(tree, "a", True)
        set_check(tree, "c", True)
        kept = checked_rows(tree)
        tree.delete(*tree.get_children())
        insert_row(tree, ("A", "1.1.1.1"), iid="a")
        insert_row(tree, ("B", "2.2.2.2"), iid="b")
        keep_checks(tree, kept)
        assert checked_rows(tree) == ["a"]  # c 行已不存在,勾选忽略

    def test_check_click_toggles_only_check_column(self, tree, monkeypatch):
        """点勾选列切换勾选并拦截;点其他列放行(不改变行选中语义)。"""
        from patrol.desktop.widgets import _check_click

        class E:
            x = 0
            y = 0

        monkeypatch.setattr(tree, "identify_region", lambda x, y: "cell")
        monkeypatch.setattr(tree, "identify_column", lambda x: "#1")
        monkeypatch.setattr(tree, "identify_row", lambda y: "b")
        assert _check_click(tree, E()) == "break"
        assert checked_rows(tree) == ["b"]  # 已切换

        monkeypatch.setattr(tree, "identify_column", lambda x: "#2")
        assert _check_click(tree, E()) is None
        assert checked_rows(tree) == ["b"]  # 其他列点击不改勾选

        monkeypatch.setattr(tree, "identify_region", lambda x, y: "heading")
        assert _check_click(tree, E()) is None  # 表头走全选 command,单击放行


class TestPlainTreeUnaffected:
    def test_plain_tree_has_no_check_column(self, root):
        t, _wrap = make_tree(root, [("name", "名称", 80)], height=3)
        insert_row(t, ("A",), iid="a")
        t.selection_set("a")
        assert tuple(t.item("a", "values")) == ("A",)  # 不带勾选前缀
        assert checked_rows(t) == []
        assert target_rows(t) == ["a"]


class TestSeverityCn:
    def test_maps_known_values(self):
        assert severity_cn("critical") == "严重"
        assert severity_cn("warning") == "警告"
        assert severity_cn("info") == "提示"

    def test_unknown_value_passthrough(self):
        assert severity_cn("high") == "high"
