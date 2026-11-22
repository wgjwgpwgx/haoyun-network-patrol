"""数据存储层

设备配置持久化到 YAML 文件，巡检任务保存在内存中。
设备密码只存在于内存和 YAML 文件，不通过 API 响应返回。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

from patrol.utils.fs import atomic_write_text

logger = logging.getLogger(__name__)


class DeviceStore:
    """设备配置存储（YAML 文件持久化）"""

    def __init__(self, config_path: str = "config/devices.yaml") -> None:
        self._path = Path(config_path)
        self._lock = threading.Lock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """从 YAML 文件加载设备列表。"""
        if not self._path.exists():
            self._devices = {}
            return
        with self._path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        from patrol.utils.crypto import decrypt_device_dict
        for raw in data.get("devices", []):
            name = raw.get("name", "")
            if name:
                self._devices[name] = decrypt_device_dict(raw)

    def _save(self) -> None:
        """将设备列表写回 YAML 文件(原子写;凭据 DPAPI 加密后落盘)。"""
        from patrol.utils.crypto import encrypt_device_dict
        data: dict[str, Any] = {
            "devices": [encrypt_device_dict(d) for d in self._devices.values()]}
        atomic_write_text(
            self._path,
            yaml.safe_dump(data, allow_unicode=True, default_flow_style=False),
        )

    def list(self) -> list[dict[str, Any]]:
        """返回所有设备配置（包含密码，内部使用）。"""
        with self._lock:
            return list(self._devices.values())

    def get(self, name: str) -> dict[str, Any] | None:
        """获取单个设备配置（包含密码，内部使用）。"""
        with self._lock:
            return self._devices.get(name)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建设备。如果同名设备已存在则抛 ValueError。"""
        name = data["name"]
        with self._lock:
            if name in self._devices:
                raise ValueError(f"设备已存在: {name}")
            self._devices[name] = data
            self._save()
            return data

    def update(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """更新设备。如果设备不存在则抛 KeyError。"""
        with self._lock:
            if name not in self._devices:
                raise KeyError(f"设备不存在: {name}")
            existing = self._devices[name]
            # 只更新非 None 字段
            for k, v in data.items():
                if v is not None:
                    existing[k] = v
            # 如果更新了 name，需要重新索引
            new_name = existing.get("name", name)
            if new_name != name:
                if new_name in self._devices:
                    raise ValueError(f"设备名已存在: {new_name}")
                del self._devices[name]
                self._devices[new_name] = existing
            self._save()
            return existing

    def delete(self, name: str) -> None:
        """删除设备。如果设备不存在则抛 KeyError。"""
        with self._lock:
            if name not in self._devices:
                raise KeyError(f"设备不存在: {name}")
            del self._devices[name]
            self._save()


class CustomerStore:
    """客户(甲方公司)信息存储（YAML 文件持久化）"""

    def __init__(self, config_path: str = "config/customers.yaml") -> None:
        self._path = Path(config_path)
        self._lock = threading.Lock()
        self._customers: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """从 YAML 文件加载客户列表。"""
        if not self._path.exists():
            self._customers = {}
            return
        with self._path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for raw in data.get("customers", []):
            name = raw.get("name", "")
            if name:
                self._customers[name] = raw

    def _save(self) -> None:
        """将客户列表写回 YAML 文件(原子写,问题 004)。"""
        data: dict[str, Any] = {"customers": list(self._customers.values())}
        atomic_write_text(
            self._path,
            yaml.safe_dump(data, allow_unicode=True, default_flow_style=False),
        )

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._customers.values())

    def get(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            return self._customers.get(name)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建客户。同名已存在抛 ValueError。"""
        name = data["name"]
        with self._lock:
            if name in self._customers:
                raise ValueError(f"客户已存在: {name}")
            self._customers[name] = data
            self._save()
            return data

    def update(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """更新客户（含重命名）。不存在抛 KeyError。"""
        with self._lock:
            if name not in self._customers:
                raise KeyError(f"客户不存在: {name}")
            existing = self._customers[name]
            for k, v in data.items():
                if v is not None:
                    existing[k] = v
            new_name = existing.get("name", name)
            if new_name != name:
                if new_name in self._customers:
                    raise ValueError(f"客户名已存在: {new_name}")
                del self._customers[name]
                self._customers[new_name] = existing
            self._save()
            return existing

    def delete(self, name: str) -> None:
        with self._lock:
            if name not in self._customers:
                raise KeyError(f"客户不存在: {name}")
            del self._customers[name]
            self._save()


MAX_TASKS = 200  # 任务记录内存上限(问题 005),超出后按创建顺序淘汰最旧


class TaskStore:
    """巡检任务存储（内存）"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def create(self, task_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._tasks[task_id] = data
            while len(self._tasks) > MAX_TASKS:
                self._tasks.pop(next(iter(self._tasks)))

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(updates)

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._tasks.values())
