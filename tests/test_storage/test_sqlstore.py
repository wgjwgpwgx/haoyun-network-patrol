"""SQLite 仓库层测试(P0-2/P0-3)"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from patrol.storage.sqlstore import (
    DEFAULT_DB, SqlAudit, SqlCustomerStore, SqlDeviceStore, SqlTaskStore,
    bootstrap, export_yaml,
)

WIN = sys.platform == "win32"


class TestSqlStores:
    def test_device_crud_and_rename(self, tmp_path: Path):
        db = tmp_path / "p.db"
        ds = SqlDeviceStore(db)
        ds.create({"name": "sw1", "host": "10.0.0.1", "password": "Pw1"})
        assert ds.get("sw1")["password"] == "Pw1"       # 读回明文
        assert len(ds.list()) == 1

        ds.update("sw1", {"host": "10.0.0.9"})
        assert ds.get("sw1")["host"] == "10.0.0.9"

        ds.update("sw1", {"name": "core-sw"})            # 重命名
        assert ds.get("sw1") is None and ds.get("core-sw")["host"] == "10.0.0.9"

        ds.delete("core-sw")
        assert ds.list() == []
        with pytest.raises(KeyError):
            ds.delete("core-sw")
        ds.create({"name": "x", "host": "1.1.1.1"})
        with pytest.raises(ValueError):  # 同名重复创建
            ds.create({"name": "x", "host": "2.2.2.2"})

    def test_device_password_cipher_on_disk(self, tmp_path: Path):
        db = tmp_path / "p.db"
        SqlDeviceStore(db).create(
            {"name": "fw", "host": "10.0.0.2", "password": "Secret#9"})
        raw = db.read_bytes()
        if WIN:
            assert b"Secret#9" not in raw                # 落库密文

    def test_customer_store(self, tmp_path: Path):
        cs = SqlCustomerStore(tmp_path / "p.db")
        cs.create({"name": "甲方A", "email": "a@x.com"})
        assert cs.get("甲方A")["email"] == "a@x.com"

    def test_task_persistence_across_restart(self, tmp_path: Path):
        db = str(tmp_path / "p.db")
        ts = SqlTaskStore(db)
        ts.create("t1", {"task_id": "t1", "status": "completed",
                         "device_name": "sw1"})
        ts.update("t1", {"report_file": "r.html"})
        # 模拟重启:新实例读同一库
        ts2 = SqlTaskStore(db)
        tasks = ts2.list_all()
        assert tasks[0]["report_file"] == "r.html" and \
            tasks[0]["status"] == "completed"

    def test_concurrent_writes(self, tmp_path: Path):
        """多线程并发建设备:全部落库,无丢失(旧 YAML 全量重写的隐患)。"""
        import threading

        ds = SqlDeviceStore(tmp_path / "p.db")
        def writer(i):
            ds.create({"name": f"dev{i}", "host": f"10.0.0.{i}"})
        threads = [threading.Thread(target=writer, args=(i,))
                   for i in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(ds.list()) == 20


class TestBootstrapMigration:
    def _prepare(self, tmp_path: Path):
        cfg = tmp_path / "config"; cfg.mkdir(exist_ok=True)
        (cfg / "devices.yaml").write_text(
            "devices:\n- {name: old1, host: 10.1.1.1, password: pw}\n"
            "- {name: old2, host: 10.1.1.2}\n",
            encoding="utf-8")
        (cfg / "customers.yaml").write_text(
            "customers:\n- {name: 甲方旧}\n", encoding="utf-8")
        return cfg

    def test_migrate_once_idempotent(self, tmp_path: Path):
        cfg = self._prepare(tmp_path)
        db = tmp_path / "data/patrol.db"
        dev, cust, _, audit = bootstrap(
            db, str(cfg / "devices.yaml"), str(cfg / "customers.yaml"))
        assert {d["name"] for d in dev.list()} == {"old1", "old2"}
        assert dev.get("old1")["password"] == "pw"       # 旧明文兼容可读
        assert cust.get("甲方旧") is not None

        # 再跑一次:幂等,不重复导入
        dev2, _, _, _ = bootstrap(
            db, str(cfg / "devices.yaml"), str(cfg / "customers.yaml"))
        assert len(dev2.list()) == 2
        assert audit.recent(1)[0]["action"] == "migrate_yaml"

    def test_export_yaml_backup(self, tmp_path: Path):
        cfg = self._prepare(tmp_path)
        db = tmp_path / "data/patrol.db"
        dev, _, _, _ = bootstrap(
            db, str(cfg / "devices.yaml"), str(cfg / "customers.yaml"))
        out = export_yaml(db, out_dir=str(tmp_path / "bak"))
        assert (tmp_path / "bak/devices_backup.yaml").exists()
        import yaml
        data = yaml.safe_load(out["devices"].read_text(encoding="utf-8"))
        assert {d["name"] for d in data["devices"]} == {"old1", "old2"}


class TestAudit:
    def test_log_and_recent(self, tmp_path: Path):
        audit = SqlAudit(tmp_path / "p.db")
        audit.log("device.create", target="sw1", detail="新增",
                  operator="admin")
        audit.log("device.delete", target="sw1", operator="web")
        rows = audit.recent(10)
        assert rows[0]["action"] == "device.delete"
        assert rows[1]["operator"] == "admin" and rows[1]["target"] == "sw1"
        assert rows[0]["ts"] >= rows[1]["ts"]


class TestAuditViaAPI:
    """REST 写操作自动落审计。"""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "config"; cfg.mkdir()
        (cfg / "devices.yaml").write_text("devices: []\n", encoding="utf-8")
        (cfg / "customers.yaml").write_text("customers: []\n", encoding="utf-8")
        (tmp_path / "output").mkdir()

        from fastapi.testclient import TestClient
        import patrol.api.app as app_module
        import patrol.api.ui as ui_module
        from patrol.api.tasks import TaskManager
        from patrol.storage.sqlstore import bootstrap

        dev, cust, ts, audit = bootstrap(str(tmp_path / "data/patrol.db"),
                                          str(cfg / "devices.yaml"),
                                          str(cfg / "customers.yaml"))
        tm = TaskManager(dev, ts, str(
            tmp_path / "config/rules/default.yaml")
            if False else "config/rules/default.yaml", str(tmp_path / "output"))
        saved = (app_module._device_store, app_module._customer_store,
                 app_module._task_store, app_module._task_manager,
                 app_module._audit,
                 ui_module._device_store, ui_module._customer_store,
                 ui_module._task_store)
        app_module._device_store, app_module._customer_store = dev, cust
        app_module._task_store, app_module._task_manager, app_module._audit = \
            ts, tm, audit
        ui_module._device_store, ui_module._customer_store = dev, cust
        ui_module._task_store = ts
        yield TestClient(app_module.app)
        (app_module._device_store, app_module._customer_store,
         app_module._task_store, app_module._task_manager,
         app_module._audit,
         ui_module._device_store, ui_module._customer_store,
         ui_module._task_store) = saved

    def test_write_ops_audited(self, client):
        client.post("/devices", json={
            "name": "审计机", "host": "10.0.0.1",
            "username": "u", "password": "p"})
        client.delete("/devices/审计机")

        r = client.get("/audit")
        rows = r.json()
        actions = [x["action"] for x in rows]
        assert "device.create" in actions and "device.delete" in actions
        # 最新的在前
        assert rows[0]["action"] == "device.delete"
        assert rows[0]["target"] == "审计机"
