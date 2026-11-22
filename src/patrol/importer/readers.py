"""台账文件读取器:xlsx/csv/docx 统一为带表头的行数据"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from patrol.importer.detect import looks_like_header


class UnsupportedFormat(Exception):
    """不支持的文件格式(附用户可操作的解决提示)"""


@dataclass
class TableData:
    """统一表格数据。无表头时列名用"第N列"占位(即无表头模式的信号)。"""
    headers: list[str]
    rows: list[list[str]]
    source: str = ""


def _cell_str(value) -> str:
    """单元格值转字符串(数值列去掉 .0 尾巴,如端口 22.0→22)。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _split_header(matrix: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """去掉全空行;首行像表头则拆出,否则全部视为数据行。"""
    matrix = [r for r in matrix if any(v for v in r)]
    if not matrix:
        return [], []
    width = max(len(r) for r in matrix)
    matrix = [r + [""] * (width - len(r)) for r in matrix]
    if looks_like_header(matrix[0]):
        headers = [h or f"第{i+1}列" for i, h in enumerate(matrix[0])]
        return headers, matrix[1:]
    return [f"第{i+1}列" for i in range(width)], matrix


def _read_openpyxl(path: Path) -> tuple[list[str], list[list[str]], str]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        # 多 Sheet 时取非空单元格最多的
        best = max(
            wb.worksheets,
            key=lambda ws: sum(1 for row in ws.iter_rows() for c in row if c.value),
        )
        matrix = [[_cell_str(c.value) for c in row] for row in best.iter_rows()]
        desc = f"工作表:{best.title}"
    finally:
        wb.close()
    headers, rows = _split_header(matrix)
    return headers, rows, desc


def _read_csv(path: Path) -> tuple[list[str], list[list[str]], str]:
    """CSV:UTF-8 优先,失败退 GBK(工程现场表格常见编码)。"""
    data = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnsupportedFormat("CSV 编码无法识别(支持 UTF-8/GBK),请用 Excel 另存为 xlsx")
    matrix = [[(v or "").strip() for v in row] for row in csv.reader(text.splitlines())]
    headers, rows = _split_header(matrix)
    return headers, rows, "CSV"


def _read_docx(path: Path) -> tuple[list[str], list[list[str]], str]:
    """Word:取单元格数最多的表格(用户密码表常为 Word 表格)。"""
    import docx

    doc = docx.Document(str(path))
    tables = list(doc.tables)
    if not tables:
        raise UnsupportedFormat("Word 文档中没有表格,请把设备清单整理成表格后重试")
    best = max(tables, key=lambda t: len(t.rows) * len(t.columns))
    matrix = [[_cell_str(cell.text) for cell in row.cells] for row in best.rows]
    headers, rows = _split_header(matrix)
    return headers, rows, f"Word 表格(共 {len(tables)} 个,取最大)"


def read_table(path: str | Path) -> TableData:
    """读取台账文件为统一表格。支持 xlsx/xlsm/csv/docx。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        headers, rows, src = _read_openpyxl(p)
    elif suffix == ".csv":
        headers, rows, src = _read_csv(p)
    elif suffix == ".docx":
        headers, rows, src = _read_docx(p)
    elif suffix == ".xls":
        raise UnsupportedFormat(
            "暂不支持 97-2003 的 .xls 老格式:请用 Excel 打开后另存为 .xlsx 再导入")
    else:
        raise UnsupportedFormat(f"不支持的文件类型: {suffix}(支持 xlsx/csv/docx)")
    return TableData(headers=headers, rows=rows, source=src)
