"""Driver 注册与发现"""
from __future__ import annotations

import logging
from typing import Type

from patrol.drivers.base import BaseDriver

logger = logging.getLogger(__name__)

_registry: dict[str, Type[BaseDriver]] = {}


def register(driver_cls: Type[BaseDriver]) -> Type[BaseDriver]:
    """注册一个 Driver 类。用作装饰器。"""
    # vendor/device_type 是 @property，需要实例化才能获取值
    instance = driver_cls()
    key = f"{instance.vendor}/{instance.device_type}"
    _registry[key] = driver_cls
    logger.debug("Registered driver: %s", key)
    return driver_cls


def get_driver(vendor: str, device_type: str) -> BaseDriver:
    """根据厂商和设备类型获取 Driver 实例。

    Raises:
        KeyError: 未找到匹配的 Driver
    """
    key = f"{vendor}/{device_type}"
    cls = _registry.get(key)
    if cls is None:
        available = list(_registry.keys())
        raise KeyError(
            f"未找到 Driver: {key}。已注册的 Driver: {available}"
        )
    return cls()


def list_drivers() -> list[str]:
    """列出所有已注册的 Driver 标识。"""
    return list(_registry.keys())
