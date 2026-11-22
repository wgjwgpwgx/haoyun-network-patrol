"""SQLite 历史数据存储 - 巡检结果持久化与趋势分析

表结构：
  patrol_runs   - 每次巡检的执行记录
  check_results - 每次巡检的检查项结果

支持：
  - 保存巡检结果
  - 查询历史记录
  - 趋势分析（按设备统计 PASS/FAIL/UNKNOWN 变化）
  - 按客户/项目分组查询
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class HistoryStore:
    """SQLite 巡检历史存储"""

    def __init__(self, db_path: str = "data/patrol_history.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS patrol_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_name TEXT NOT NULL,
                    device_host TEXT NOT NULL,
                    device_type TEXT NOT NULL DEFAULT '',
                    vendor TEXT NOT NULL DEFAULT '',
                    customer TEXT NOT NULL DEFAULT '',
                    project TEXT NOT NULL DEFAULT '',
                    run_time TEXT NOT NULL,
                    pass_count INTEGER NOT NULL DEFAULT 0,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    unknown_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    report_file TEXT
                );

                CREATE TABLE IF NOT EXISTS check_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    check_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    suggestion TEXT NOT NULL DEFAULT '',
                    value REAL,
                    FOREIGN KEY (run_id) REFERENCES patrol_runs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_runs_device
                    ON patrol_runs(device_name, run_time);
                CREATE INDEX IF NOT EXISTS idx_runs_customer
                    ON patrol_runs(customer, project);
                CREATE INDEX IF NOT EXISTS idx_results_run
                    ON check_results(run_id);
            """)

    def save_run(
        self,
        device_name: str,
        device_host: str,
        device_type: str,
        vendor: str,
        customer: str,
        project: str,
        pass_count: int,
        fail_count: int,
        unknown_count: int,
        check_items: list[dict[str, Any]],
        error: str | None = None,
        report_file: str | None = None,
        run_time: str | None = None,
    ) -> int:
        """保存一次巡检记录，返回 run_id(run_time 可注入,默认当前时间)。"""
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """INSERT INTO patrol_runs
                       (device_name, device_host, device_type, vendor,
                        customer, project, run_time,
                        pass_count, fail_count, unknown_count,
                        error, report_file)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        device_name, device_host, device_type, vendor,
                        customer, project,
                        run_time or datetime.now().isoformat(),
                        pass_count, fail_count, unknown_count,
                        error, report_file,
                    ),
                )
                run_id = cursor.lastrowid

                for item in check_items:
                    conn.execute(
                        """INSERT INTO check_results
                           (run_id, check_name, category, status,
                            severity, message, suggestion, value)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            run_id,
                            item.get("name", ""),
                            item.get("category", ""),
                            item.get("status", ""),
                            item.get("severity", ""),
                            item.get("message", ""),
                            item.get("suggestion", ""),
                            item.get("value"),
                        ),
                    )

                conn.commit()
                return run_id
            finally:
                conn.close()

    def get_runs(
        self,
        device_name: str | None = None,
        customer: str | None = None,
        project: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询巡检历史。"""
        conditions: list[str] = []
        params: list[Any] = []

        if device_name:
            conditions.append("device_name = ?")
            params.append(device_name)
        if customer:
            conditions.append("customer = ?")
            params.append(customer)
        if project:
            conditions.append("project = ?")
            params.append(project)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    f"SELECT * FROM patrol_runs{where} ORDER BY run_time DESC LIMIT ?",
                    params + [limit],
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_run_detail(self, run_id: int) -> dict[str, Any] | None:
        """查询单次巡检的详细结果。"""
        with self._lock:
            conn = self._get_conn()
            try:
                run = conn.execute(
                    "SELECT * FROM patrol_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if not run:
                    return None
                result = dict(run)
                items = conn.execute(
                    "SELECT * FROM check_results WHERE run_id = ? ORDER BY id",
                    (run_id,),
                ).fetchall()
                result["check_items"] = [dict(r) for r in items]
                return result
            finally:
                conn.close()

    def _ensure_value_column(self, conn) -> None:
        """老库升级:check_results 缺 value 列则补(P1-3)。"""
        cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(check_results)").fetchall()]
        if cols and "value" not in cols:
            conn.execute("ALTER TABLE check_results ADD COLUMN value REAL")

    def metric_series(self, device_name: str, check_name: str,
                      limit: int = 20) -> list[tuple[str, float]]:
        """某设备某检查项的历史值序列(时间正序,供趋势图)。"""
        with self._lock:
            conn = self._get_conn()
            try:
                self._ensure_value_column(conn)
                rows = conn.execute(
                    """SELECT r.run_time, c.value FROM check_results c
                       JOIN patrol_runs r ON r.id = c.run_id
                       WHERE r.device_name = ? AND c.check_name = ?
                         AND c.value IS NOT NULL
                       ORDER BY r.run_time DESC LIMIT ?""",
                    (device_name, check_name, limit)).fetchall()
                return [(r["run_time"], float(r["value"]))
                        for r in reversed(rows)]
            finally:
                conn.close()

    def get_trend(
        self,
        device_name: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """查询设备巡检趋势数据（最近 N 次）。"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    """SELECT run_time, pass_count, fail_count, unknown_count
                       FROM patrol_runs
                       WHERE device_name = ?
                       ORDER BY run_time DESC LIMIT ?""",
                    (device_name, limit),
                ).fetchall()
                return [dict(r) for r in reversed(rows)]
            finally:
                conn.close()

    def get_summary_by_customer(self) -> list[dict[str, Any]]:
        """按客户/项目汇总巡检统计。"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    """SELECT customer, project,
                              COUNT(*) as run_count,
                              SUM(fail_count) as total_failures,
                              MAX(run_time) as last_run
                       FROM patrol_runs
                       WHERE customer != ''
                       GROUP BY customer, project
                       ORDER BY customer, project"""
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ── 上期复查支持(销号清单 #8) ─────────────────────────────

    def prev_fail_items(self, before_time: str,
                        device_names: list[str] | None = None,
                        ) -> dict[tuple[str, str], dict[str, Any]]:
        """取 before_time 之前每台设备最近一次巡检中的 FAIL 项。

        返回 {(device_name, check_name): {run_time, severity, message}}。
        """
        with self._lock:
            conn = self._get_conn()
            try:
                cond = ""
                params: list[Any] = [before_time]
                if device_names:
                    marks = ",".join("?" * len(device_names))
                    cond = f"AND device_name IN ({marks})"
                    params += device_names
                rows = conn.execute(
                    f"""SELECT r.id, r.device_name, r.run_time,
                               c.check_name, c.severity, c.message
                        FROM patrol_runs r
                        JOIN check_results c ON c.run_id = r.id
                        WHERE c.status = 'FAIL' AND r.run_time < ? {cond}
                          AND r.id = (
                              SELECT MAX(r2.id) FROM patrol_runs r2
                              WHERE r2.device_name = r.device_name
                                AND r2.run_time < ?)
                        """,
                    params + [before_time],
                ).fetchall()
                return {(r["device_name"], r["check_name"]): {
                    "run_time": r["run_time"], "severity": r["severity"],
                    "message": r["message"]} for r in rows}
            finally:
                conn.close()

    def fail_streaks(self, limit_per_device: int = 50,
                     ) -> dict[tuple[str, str], int]:
        """统计各(设备, 检查项)从最近一次往前连续 FAIL 的期数。"""
        with self._lock:
            conn = self._get_conn()
            try:
                devices = [r["device_name"] for r in conn.execute(
                    "SELECT DISTINCT device_name FROM patrol_runs")]
                streaks: dict[tuple[str, str], int] = {}
                for dev in devices:
                    runs = conn.execute(
                        """SELECT r.id FROM patrol_runs r
                           WHERE r.device_name = ?
                           ORDER BY r.run_time DESC LIMIT ?""",
                        (dev, limit_per_device)).fetchall()
                    statuses: dict[str, list[str]] = {}
                    for run in runs:
                        for row in conn.execute(
                                "SELECT check_name, status FROM check_results "
                                "WHERE run_id = ?", (run["id"],)):
                            statuses.setdefault(row["check_name"], []) \
                                .append(row["status"])
                    for check, seq in statuses.items():
                        n = 0
                        for s in seq:  # seq 按时间倒序
                            if s == "FAIL":
                                n += 1
                            else:
                                break
                        if n >= 2:  # 连续 2 期及以上才入跟踪
                            streaks[(dev, check)] = n
                return streaks
            finally:
                conn.close()
