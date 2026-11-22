"""Driver 抽象接口 - 定义厂商设备的命令和解析逻辑

所有厂商差异（命令、回显解析、检查项定义）必须在 Driver 子类中实现。
业务层只通过 BaseDriver 接口与设备交互，不得直接使用厂商命令字符串。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckCommand:
    """一个待执行的检查命令定义

    由 Driver.get_check_commands() 返回，描述需要执行什么命令、
    属于什么检查类别。
    """

    name: str
    """检查项标识，如 'cpu_usage'"""

    category: str
    """检查类别，如 'CPU'"""

    command: str
    """设备命令，如 'display cpu-usage'"""

    description: str = ""
    """检查项说明"""


@dataclass
class ParsedResult:
    """命令回显解析后的结构化结果

    由 Driver.parse_output() 返回，是连接采集层和分析层的桥梁。
    success=False 时，error 字段说明原因，分析层应判定为 UNKNOWN。
    """

    name: str
    category: str
    command: str
    raw_output: str
    parsed: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str = ""


class BaseDriver(ABC):
    """厂商 Driver 抽象基类

    子类必须实现：
    - vendor / device_type / netmiko_device_type 属性
    - get_check_commands() 返回检查命令列表
    - parse_output() 解析命令回显
    """

    @property
    @abstractmethod
    def vendor(self) -> str:
        """厂商名称，如 'h3c'"""
        ...

    @property
    @abstractmethod
    def device_type(self) -> str:
        """设备类型标识，如 'comware_switch'"""
        ...

    @property
    @abstractmethod
    def netmiko_device_type(self) -> str:
        """Netmiko 的 device_type，用于 SSH 连接"""
        ...

    @property
    def netmiko_telnet_device_type(self) -> str:
        """Netmiko 的 Telnet device_type(空=该设备不支持 Telnet 登录)"""
        return ""

    @abstractmethod
    def get_check_commands(self) -> list[CheckCommand]:
        """返回该设备类型需要执行的所有检查命令"""
        ...

    @abstractmethod
    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        """解析命令回显，返回结构化数据。

        Args:
            name: 检查项名称（与 get_check_commands 中的 name 对应）
            raw_output: 命令原始回显

        Returns:
            ParsedResult: 包含解析后数据的结果对象
        """
        ...
