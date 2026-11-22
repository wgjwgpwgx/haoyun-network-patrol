"""采集器抽象接口"""
from __future__ import annotations

from abc import ABC, abstractmethod

from patrol.models import DeviceAsset


class BaseCollector(ABC):
    """采集器基类 - 负责连接设备并执行命令

    实现类必须保证：
    - connect 失败抛出明确异常（认证失败 / 连接超时 / 连接拒绝）
    - execute 返回原始命令输出
    - disconnect 总是安全的（即使未连接也不抛异常）
    """

    @abstractmethod
    def connect(self, asset: DeviceAsset) -> None:
        """根据设备资产建立连接。失败时抛出异常。"""
        ...

    @abstractmethod
    def execute(self, command: str, timeout: int = 60) -> str:
        """执行单条命令，返回原始回显文本。失败时抛出异常。"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接。未连接时静默返回。"""
        ...
