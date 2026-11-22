"""数据存储层测试"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.api.store import DeviceStore, TaskStore


@pytest.fixture
def config_path(tmp_path):
    p = tmp_path / "devices.yaml"
    p.write_text("devices: []\n", encoding="utf-8")
    return str(p)


class TestDeviceStore:
    def test_create_and_get(self, config_path):
        store = DeviceStore(config_path)
        data = {"name": "sw1", "host": "10.0.0.1", "username": "admin", "password": "pw"}
        store.create(data)
        result = store.get("sw1")
        assert result is not None
        assert result["host"] == "10.0.0.1"

    def test_create_duplicate(self, config_path):
        store = DeviceStore(config_path)
        data = {"name": "sw1", "host": "10.0.0.1"}
        store.create(data)
        with pytest.raises(ValueError, match="已存在"):
            store.create(data)

    def test_list(self, config_path):
        store = DeviceStore(config_path)
        store.create({"name": "sw1", "host": "10.0.0.1"})
        store.create({"name": "sw2", "host": "10.0.0.2"})
        assert len(store.list()) == 2

    def test_update(self, config_path):
        store = DeviceStore(config_path)
        store.create({"name": "sw1", "host": "10.0.0.1"})
        updated = store.update("sw1", {"host": "10.0.0.99"})
        assert updated["host"] == "10.0.0.99"

    def test_update_not_found(self, config_path):
        store = DeviceStore(config_path)
        with pytest.raises(KeyError):
            store.update("不存在", {"host": "10.0.0.1"})

    def test_delete(self, config_path):
        store = DeviceStore(config_path)
        store.create({"name": "sw1", "host": "10.0.0.1"})
        store.delete("sw1")
        assert store.get("sw1") is None

    def test_delete_not_found(self, config_path):
        store = DeviceStore(config_path)
        with pytest.raises(KeyError):
            store.delete("不存在")

    def test_persistence(self, config_path):
        """写入后重新加载应保留数据。"""
        store1 = DeviceStore(config_path)
        store1.create({"name": "sw1", "host": "10.0.0.1"})
        store2 = DeviceStore(config_path)
        assert store2.get("sw1") is not None


class TestAtomicSave:
    """问题 004:配置写盘原子化(临时文件 + os.replace)。"""

    def test_no_tmp_left_and_roundtrip(self, config_path):
        store = DeviceStore(config_path)
        store.create({"name": "sw1", "host": "10.0.0.1"})
        p = Path(config_path)
        assert not p.with_name(p.name + ".tmp").exists()
        assert DeviceStore(config_path).get("sw1") is not None


class TestTaskStoreLimit:
    """问题 005:任务内存无界 → 上限淘汰最旧。"""

    def test_evicts_oldest_beyond_cap(self, monkeypatch):
        import patrol.api.store as store_mod

        monkeypatch.setattr(store_mod, "MAX_TASKS", 3)
        ts = TaskStore()
        for i in range(5):
            ts.create(f"t{i}", {"task_id": f"t{i}"})
        assert [t["task_id"] for t in ts.list_all()] == ["t2", "t3", "t4"]

    def test_default_cap_200(self):
        from patrol.api.store import MAX_TASKS

        assert MAX_TASKS == 200


class TestTaskStore:
    def test_create_and_get(self):
        store = TaskStore()
        store.create("t1", {"status": "pending"})
        result = store.get("t1")
        assert result is not None
        assert result["status"] == "pending"

    def test_get_not_found(self):
        store = TaskStore()
        assert store.get("nonexistent") is None

    def test_update(self):
        store = TaskStore()
        store.create("t1", {"status": "pending"})
        store.update("t1", {"status": "running"})
        assert store.get("t1")["status"] == "running"

    def test_list_all(self):
        store = TaskStore()
        store.create("t1", {"status": "pending"})
        store.create("t2", {"status": "completed"})
        assert len(store.list_all()) == 2
