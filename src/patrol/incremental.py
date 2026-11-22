"""增量巡检模式(P1 第三批 ①)

快速模式:只跑核心 5 项(CPU/内存/温度/电源/风扇)+ 上次异常项,
跳过上次稳定的检查项。全量模式不变(默认)。

对标:华为 NCE 智能巡检分级
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 核心检查项(快速模式必跑)
CORE_CHECKS = {
    "cpu_usage", "memory_usage", "temperature",
    "power_status", "fan_status", "device_info",
}


def get_incremental_checks(vendor: str, device_type: str,
                           all_checks: list[Any]) -> list[Any]:
    """返回增量模式下应执行的检查命令子集。

    逻辑:核心项 ∪ 上次巡检中 FAIL/UNKNOWN 的项。
    无历史数据时退化为全量(首次巡检)。
    """
    from patrol.storage.history import HistoryStore

    # 上次异常项
    previous_fails: set[str] = set()
    try:
        hist = HistoryStore()
        # 取该厂商/类型最近一次巡检中 FAIL/UNKNOWN 的检查项名
        # 遍历所有设备太重;按 check_results 表反查
        # 简化:取全部最新 FAIL/UNKNOWN 项(跨设备但同 check_name 语义一致)
        import sqlite3
        with sqlite3.connect(str(hist._db)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT DISTINCT c.check_name FROM check_results c
                JOIN patrol_runs r ON r.id = c.run_id
                WHERE c.status IN ('FAIL', 'UNKNOWN')
                  AND r.id = (SELECT MAX(r2.id) FROM patrol_runs r2)
            """).fetchall()
            previous_fails = {r["check_name"] for r in rows}
    except Exception:  # noqa: BLE001 - 历史不可用退化为全量
        return all_checks

    # 核心项 ∪ 上次异常项
    should_run = CORE_CHECKS | previous_fails
    subset = [c for c in all_checks if c.name in should_run]

    if not subset:
        return all_checks  # 安全兜底

    logger.info("增量模式: %d/%d 条检查项", len(subset), len(all_checks))
    return subset
