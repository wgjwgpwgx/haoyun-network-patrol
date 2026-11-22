"""报告归档(销号清单 #11):导出的 Word/Excel 副本归档到 output/{客户}/{年月}/

HTML 巡检报告保持平铺(网页报告列表依赖),归档仅针对交付物副本。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def archive_report(path: Path, customer: str) -> Path | None:
    """把报告副本归档到 output/{客户}/{YYYY-MM}/;无客户返回 None。"""
    from patrol.utils.filename import safe_component

    customer = (customer or "").strip()
    if not customer or not path.exists():
        return None
    dest_dir = Path("output") / safe_component(customer) / \
        datetime.now().strftime("%Y-%m")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    dest.write_bytes(path.read_bytes())
    return dest
