"""分析引擎抽象接口"""
from __future__ import annotations

from abc import ABC, abstractmethod

from patrol.drivers.base import ParsedResult
from patrol.models import CheckItem


class BaseAnalyzer(ABC):
    """分析引擎基类 - 将解析结果转换为带判定状态的检查项"""

    @abstractmethod
    def analyze(self, parsed: ParsedResult) -> CheckItem:
        """分析一条解析结果，返回带 PASS/FAIL/UNKNOWN 判定的检查项"""
        ...
