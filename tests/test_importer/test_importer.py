"""设备台账智能导入测试:野格式识别 + 批量建档"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.api.store import CustomerStore, DeviceStore
from patrol.importer import (
    UnsupportedFormat,
    detect_columns,
    import_rows,
    preview_file,
    read_table,
)


# ── 测试样本构造 ──────────────────────────────────────────────


def _make_xlsx(path: Path, headers: list[str], rows: list[list[str]]):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(str(path))


def _make_docx(path: Path, headers: list[str], rows: list[list[str]]):
    import docx

    doc = docx.Document()
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row):
            table.rows[r].cells[c].text = v
    doc.save(str(path))


ROWS_FULL = [
    ["核心交换", "10.0.0.1", "SSH", "admin01", "Pw#2026!x", "Sup@2026", "华为", "研发楼A"],
    ["接入交换", "10.0.0.2", "SSH", "admin01", "Pw#2026!x", "", "华三", "研发楼B"],
    ["出口防火墙", "10.0.0.3", "Web", "admin", "Fw#9981", "", "深信服", "机房"],
]

# 野格式表头:顺序乱、叫法不一、全角空格
WILD_HEADERS = ["设备名称", "管 理 地 址", "接入方式", "登录账号", "口令",
                "特权密码", "品牌", "机房位置"]


@pytest.fixture
def stores(tmp_path):
    devices = DeviceStore(str(tmp_path / "devices.yaml"))
    customers = CustomerStore(str(tmp_path / "customers.yaml"))
    customers.create({"name": "演示单位", "contact": "", "phone": "", "remark": ""})
    return devices, customers


# ── 读取器 ────────────────────────────────────────────────────


class TestReaders:
    def test_xlsx(self, tmp_path):
        p = tmp_path / "t.xlsx"
        _make_xlsx(p, WILD_HEADERS, ROWS_FULL)
        table = read_table(p)
        assert table.headers[1] == "管 理 地 址"
        assert len(table.rows) == 3

    def test_csv_gbk(self, tmp_path):
        p = tmp_path / "t.csv"
        p.write_text(
            "设备名称,管理地址,登录账号,密码\n核心交换,10.0.0.9,admin,Pass1234",
            encoding="gbk")
        table = read_table(p)
        assert len(table.rows) == 1

    def test_docx_table(self, tmp_path):
        p = tmp_path / "t.docx"
        _make_docx(p, WILD_HEADERS, ROWS_FULL)
        table = read_table(p)
        assert len(table.rows) == 3
        assert "Word" in table.source

    def test_xls_rejected_with_hint(self, tmp_path):
        p = tmp_path / "t.xls"
        p.write_bytes(b"\xd0\xcf\x11\xa0")
        with pytest.raises(UnsupportedFormat, match="另存为"):
            read_table(p)

    def test_headerless_uses_placeholder(self, tmp_path):
        p = tmp_path / "t.xlsx"
        _make_xlsx(p, ["10.0.0.1", "admin", "Pass1234"], [])  # 首行是数据
        table = read_table(p)
        assert table.headers[0] == "第1列"  # 首行不像表头 → 全部当数据


# ── 字段识别 ──────────────────────────────────────────────────


class TestDetect:
    def test_wild_header_exact(self):
        matches = detect_columns(WILD_HEADERS, ROWS_FULL)
        by_field = {m.field: m for m in matches.values()}
        assert by_field["host"].column == 1 and by_field["host"].confidence == 1.0
        assert by_field["username"].column == 3       # 登录账号
        assert by_field["password"].column == 4       # 口令
        assert by_field["super_password"].column == 5  # 特权密码
        assert by_field["name"].column == 0
        assert by_field["login_method"].column == 2
        assert by_field["vendor"].column == 6
        assert by_field["remark"].column == 7         # 机房位置→备注

    def test_header_contains_match(self):
        headers = ["设备管理IP地址", "登录用户名", "登录密码"]
        matches = detect_columns(headers, [])
        by_field = {m.field: m for m in matches.values()}
        assert by_field["host"].column == 0 and by_field["host"].confidence == 0.9

    def test_headerless_content_detection(self):
        """无表头:IP/登录方式强特征,用户名密码启发式(标黄)。"""
        headers = ["第1列", "第2列", "第3列", "第4列"]
        rows = [
            ["核心交换1", "10.1.1.1", "admin01", "Pw2026ab"],
            ["核心交换2", "10.1.1.2", "netops", "Pw2026cd"],
            ["防火墙", "10.1.1.3", "rootops", "Fw9981xy"],
        ]
        matches = detect_columns(headers, rows)
        by_field = {m.field: m for m in matches.values()}
        assert by_field["host"].column == 1 and by_field["host"].confidence >= 0.9
        pw = by_field["password"]
        assert pw.column == 3 and pw.confidence < 0.8  # 启发式 → 标黄待确认

    def test_one_column_one_field(self):
        """一列不会被两个字段争抢(高置信优先)。"""
        headers = ["IP地址", "地址"]  # 都像 host,取第一个精确命中
        matches = detect_columns(headers, [])
        hosts = [m for m in matches.values() if m.field == "host"]
        assert len(hosts) == 1


# ── 预览与导入 ────────────────────────────────────────────────


class TestPreviewAndImport:
    def test_preview_structure(self, tmp_path):
        p = tmp_path / "t.xlsx"
        _make_xlsx(p, WILD_HEADERS, ROWS_FULL)
        pv = preview_file(p)
        assert pv["row_count"] == 3
        assert pv["missing_required"] == []
        assert "host" in pv["mapping"] and pv["mapping"]["host"]["confidence"] == 1.0

    def test_import_creates_devices(self, tmp_path, stores):
        devices, customers = stores
        p = tmp_path / "t.xlsx"
        _make_xlsx(p, WILD_HEADERS, ROWS_FULL)
        table = read_table(p)
        matches = detect_columns(table.headers, table.rows)
        mapping = {m.field: m.column for m in matches.values()}
        result = import_rows(devices, customers, table, mapping,
                             default_customer="演示单位")
        assert result["created"] == 3 and result["skipped"] == 0

        fw = devices.get("出口防火墙")
        assert fw["login_method"] == "web"           # Web → 归一
        assert fw["vendor"] == "sangfor"             # 深信服 → 归一
        assert fw["super_password"] == ""            # 空即未配置
        sw = devices.get("核心交换")
        assert sw["super_password"] == "Sup@2026"
        assert sw["customer"] == "演示单位"

    def test_import_skips_invalid_rows(self, tmp_path, stores):
        devices, customers = stores
        p = tmp_path / "t.xlsx"
        rows = [
            ["好设备", "10.0.0.1", "SSH", "u1", "p1", "", "华为", ""],
            ["缺密码", "10.0.0.2", "SSH", "u2", "", "", "", ""],      # 缺必填
            ["坏地址", "a/b", "SSH", "u3", "p3", "", "", ""],          # 非法 host
            ["好设备", "10.0.0.4", "SSH", "u4", "p4", "", "", ""],     # 设备名重复
        ]
        _make_xlsx(p, WILD_HEADERS, rows)
        table = read_table(p)
        matches = detect_columns(table.headers, table.rows)
        mapping = {m.field: m.column for m in matches.values()}
        result = import_rows(devices, customers, table, mapping,
                             default_customer="演示单位")
        assert result["created"] == 1 and result["skipped"] == 3
        reasons = " / ".join(e["reason"] for e in result["errors"])
        assert "缺少必填" in reasons and "管理地址非法" in reasons

    def test_telnet_default_port(self, tmp_path, stores):
        devices, customers = stores
        p = tmp_path / "t.xlsx"
        _make_xlsx(p, ["设备名", "地址", "方式", "账号", "密码"],
                   [["老交换", "10.0.0.5", "Telnet", "u", "p"]])
        table = read_table(p)
        matches = detect_columns(table.headers, table.rows)
        mapping = {m.field: m.column for m in matches.values()}
        import_rows(devices, customers, table, mapping)
        dev = devices.get("老交换")
        assert dev["login_method"] == "telnet" and dev["port"] == 23
