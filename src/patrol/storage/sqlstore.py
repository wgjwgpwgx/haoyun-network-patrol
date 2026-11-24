"""SQLite 统一仓库层(P0 数据层迁移)

设备/客户/任务从 YAML/内存迁移到单一 SQLite(data/patrol.db):
  - 事务安全、锁外磁盘 IO、任务持久化(重启不丢)
  - 对外接口与旧 DeviceStore/CustomerStore/TaskStore 完全一致,
    生产装配点直接替换,上层(api/ui/desktop/cli)无感
  - 首次启动自动从旧 YAML 一次性迁移(幂等);提供 export_yaml 备份导出
  - 凭据字段沿用 DPAPI 加密(密文存库)
  - audit_log 操作审计表(P0-3)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from patrol.utils.crypto import decrypt_device_dict, encrypt_device_dict

logger = logging.getLogger(__name__)

DEFAULT_DB = "data/patrol.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class _JsonTableStore:
    """通用 JSON 表仓库基类:主键列 pk,数据列 data。"""

    _table: str = ""
    _pk: str = "name"

    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        # 锚定绝对路径:实例生命周期内 CWD 变化不影响后续连接
        self._db = Path(db_path).resolve()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock, _connect(self._db) as conn:
            conn.executescript(_SCHEMA)

    def _row(self, conn, key: str) -> dict | None:
        r = conn.execute(
            f"SELECT data FROM {self._table} WHERE {self._pk} = ?", (key,)
        ).fetchone()
        return json.loads(r["data"]) if r else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock, _connect(self._db) as conn:
            rows = conn.execute(
                f"SELECT data FROM {self._table}").fetchall()
        return [json.loads(r["data"]) for r in rows]

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock, _connect(self._db) as conn:
            return self._row(conn, key)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        key = data[self._pk]
        with self._lock, _connect(self._db) as conn:
            if self._row(conn, key) is not None:
                raise ValueError(f"已存在: {key}")
            conn.execute(
                f"INSERT INTO {self._table} ({self._pk}, data) VALUES (?, ?)",
                (key, json.dumps(data, ensure_ascii=False)))
        return data

    def update(self, key: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock, _connect(self._db) as conn:
            current = self._row(conn, key)
            if current is None:
                raise KeyError(f"不存在: {key}")
            for k, v in changes.items():
                if v is not None:
                    current[k] = v
            new_key = current[self._pk]
            if new_key != key:  # 重命名
                if self._row(conn, new_key) is not None:
                    raise ValueError(f"已存在: {new_key}")
                conn.execute(
                    f"DELETE FROM {self._table} WHERE {self._pk} = ?", (key,))
            conn.execute(
                f"INSERT OR REPLACE INTO {self._table} ({self._pk}, data) "
                "VALUES (?, ?)",
                (new_key, json.dumps(current, ensure_ascii=False)))
            return current
        return current  # pragma: no cover

    def delete(self, key: str) -> None:
        with self._lock, _connect(self._db) as conn:
            if self._row(conn, key) is None:
                raise KeyError(f"不存在: {key}")
            conn.execute(
                f"DELETE FROM {self._table} WHERE {self._pk} = ?", (key,))


class SqlDeviceStore(_JsonTableStore):
    """设备仓库(凭据字段加密存库,读取解密)。"""
    _table = "devices"

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        return decrypt_device_dict(
            super().create(encrypt_device_dict(data)))

    def update(self, key: str, changes: dict[str, Any]) -> dict[str, Any]:
        return decrypt_device_dict(
            super().update(key, encrypt_device_dict(dict(changes))))

    def get(self, key: str):
        row = super().get(key)
        return decrypt_device_dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        return [decrypt_device_dict(d) for d in super().list()]


class SqlCustomerStore(_JsonTableStore):
    _table = "customers"


class SqlTaskStore(_JsonTableStore):
    """任务仓库(持久化,重启不丢)。接口对齐旧 TaskStore。"""
    _table = "tasks"
    _pk = "task_id"

    def create(self, key_or_data, data: dict | None = None) -> dict:
        """兼容两种签名:create(task_id, data) 与 create(data含task_id)。"""
        if data is None:
            data = dict(key_or_data)
        else:
            data = {"task_id": key_or_data, **data}
        return super().create(data)

    def list_all(self) -> list[dict[str, Any]]:
        return self.list()


class SqlAudit:
    """操作审计(P0-3):谁/何时/做了什么。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self._db = Path(db_path).resolve()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self._db) as conn:
            conn.executescript(_SCHEMA)

    def log(self, action: str, target: str = "", detail: str = "",
            operator: str = "local") -> None:
        with _connect(self._db) as conn:
            conn.execute(
                "INSERT INTO audit_log (ts, operator, action, target, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"),
                 operator, action, target, detail[:300]))

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with _connect(self._db) as conn:
            rows = conn.execute(
                "SELECT ts, operator, action, target, detail FROM audit_log "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def _meta(db_path: str | Path, key: str, value: str | None = None) -> str | None:
    """读/写 meta 表(传 value 即写入,不传即读取)。"""
    with _connect(db_path) as conn:
        if value is None:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    return None


def bootstrap(db_path: str | Path = DEFAULT_DB,
              devices_yaml: str = "config/devices.yaml",
              customers_yaml: str = "config/customers.yaml",
              ) -> tuple[SqlDeviceStore, SqlCustomerStore, SqlTaskStore, SqlAudit]:
    """生产装配入口:建库并从旧 YAML 一次性迁移(带标记,只做一次),返回四个仓库。"""
    import yaml

    dev_store = SqlDeviceStore(db_path)
    cust_store = SqlCustomerStore(db_path)
    task_store = SqlTaskStore(db_path)
    audit = SqlAudit(db_path)

    # 迁移只做一次并留标记:否则界面里删掉的旧设备每次启动都会从 YAML 复活
    if _meta(db_path, "yaml_migrated") is not None:
        return dev_store, cust_store, task_store, audit

    migrated = 0
    for yaml_path, store, label in (
            (devices_yaml, dev_store, "devices"),
            (customers_yaml, cust_store, "customers")):
        p = Path(yaml_path)
        if not p.exists():
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001 - 迁移失败不阻断启动
            logger.warning("迁移源 %s 读取失败: %s", yaml_path, e)
            continue
        existing = {d.get("name") for d in store.list()}
        for raw in data.get(label, []):
            name = raw.get("name", "")
            if name and name not in existing:
                store.create(raw)
                migrated += 1
    if migrated:
        audit.log("migrate_yaml", target=str(db_path),
                  detail=f"从旧 YAML 迁移 {migrated} 条记录")
        logger.info("YAML→SQLite 迁移完成: %d 条", migrated)
    _meta(db_path, "yaml_migrated",
          datetime.now().isoformat(timespec="seconds"))
    return dev_store, cust_store, task_store, audit


def export_yaml(db_path: str | Path = DEFAULT_DB,
                out_dir: str = "config") -> dict[str, Path]:
    """把库中设备/客户导出为 YAML(备份/交付;凭据以密文导出)。"""
    import yaml

    out = {}
    for table, filename in (("devices", "devices_backup.yaml"),
                            ("customers", "customers_backup.yaml")):
        with _connect(db_path) as conn:
            rows = conn.execute(f"SELECT data FROM {table}").fetchall()
        data = {table: [json.loads(r["data"]) for r in rows]}
        path = Path(out_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8")
        out[table] = path
    return out
