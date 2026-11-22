"""设备台账智能导入模块

工程师手头的用户名密码表(Word/Excel/CSV,格式不齐)→ 自动识别字段 →
预览确认 → 批量建档。识别策略:表头同义词(高置信)+ 内容特征(兜底),
最终由预览界面人工确认,保证入库正确率 100%。
"""
from patrol.importer.readers import TableData, UnsupportedFormat, read_table
from patrol.importer.detect import detect_columns
from patrol.importer.service import import_rows, preview_file

__all__ = [
    "TableData", "UnsupportedFormat", "read_table",
    "detect_columns", "preview_file", "import_rows",
]
