"""pytest 公共 fixtures"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.analyzer.engine import RuleEngine
from patrol.models import DeviceAsset

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RULES_FILE = Path(__file__).parent.parent / "config" / "rules" / "default.yaml"


@pytest.fixture
def h3c_fixtures() -> Path:
    """H3C Comware 交换机测试回显文件目录。"""
    return FIXTURES_DIR / "h3c" / "comware_switch"


@pytest.fixture
def load_fixture(h3c_fixtures: Path):
    """加载回显文件的辅助函数。"""
    def _load(filename: str) -> str:
        return (h3c_fixtures / filename).read_text(encoding="utf-8")
    return _load


@pytest.fixture
def sample_asset() -> DeviceAsset:
    """一台示例设备资产，用于测试。"""
    return DeviceAsset(
        name="测试交换机",
        host="192.168.1.1",
        vendor="h3c",
        device_type="comware_switch",
        port=22,
        username="admin",
        password="test123",
        enabled=True,
        timeout=30,
        command_timeout=60,
    )


@pytest.fixture
def rule_engine() -> RuleEngine:
    """加载默认规则的 RuleEngine 实例。"""
    rules = RuleEngine.load_file(RULES_FILE)
    return RuleEngine(rules)


@pytest.fixture(autouse=True)
def _web_auth_off(request, monkeypatch):
    """默认关闭 Web 登录认证,既有用例不受影响;test_auth.py 自行管理认证状态。"""
    mod = getattr(request.node.module, "__name__", "") or ""
    if mod.endswith("test_auth"):
        return
    monkeypatch.setattr("patrol.api.auth.auth_enabled", lambda: False)
