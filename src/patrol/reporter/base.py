"""报告生成器抽象接口"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from patrol.models import PatrolReport


class BaseReporter(ABC):
    """报告生成器基类"""

    @abstractmethod
    def generate(self, report: PatrolReport, output_path: Path) -> Path:
        """生成报告文件，返回实际输出路径"""
        ...
