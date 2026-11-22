"""集成测试 - 场景 3：异常处理

验证连接失败、认证失败时的错误处理。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from patrol.analyzer.engine import RuleEngine
from patrol.cli import run_inspection
from patrol.collector.ssh import (
    SSHAuthenticationError,
    SSHCollector,
    SSHConnectionError,
    SSHCommandError,
)
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.models import CheckStatus, DeviceAsset

RULES = Path(__file__).parent.parent.parent / "config" / "rules" / "vrp_switch.yaml"


@pytest.fixture
def asset():
    return DeviceAsset(
        name="不可达设备", host="192.0.2.1", vendor="huawei",
        device_type="vrp_switch", login_method="ssh",
        username="admin", password="wrong",
    )


@pytest.fixture
def engine():
    return RuleEngine(RuleEngine.load_file(str(RULES)))


@pytest.fixture
def driver():
    return HuaweiVRPSwitchDriver()


class TestConnectionFailure:
    """场景 3：异常处理"""

    @patch.object(SSHCollector, "connect", side_effect=SSHConnectionError("连接超时 192.0.2.1:22"))
    def test_connection_timeout(self, mock_connect, asset, driver, engine):
        """连接超时 → report.error 有值，无检查项"""
        report = run_inspection(asset, driver, engine)

        assert report.error is not None
        assert "连接超时" in report.error
        assert len(report.check_items) == 0
        assert report.pass_count == 0
        assert report.fail_count == 0

    @patch.object(SSHCollector, "connect", side_effect=SSHAuthenticationError("认证失败 192.0.2.1:22"))
    def test_authentication_failure(self, mock_connect, asset, driver, engine):
        """认证失败 → report.error 有值，无检查项"""
        report = run_inspection(asset, driver, engine)

        assert report.error is not None
        assert "认证失败" in report.error
        assert len(report.check_items) == 0

    @patch.object(SSHCollector, "connect", side_effect=SSHConnectionError("Connection refused"))
    def test_connection_refused(self, mock_connect, asset, driver, engine):
        """连接被拒绝 → report.error 有值"""
        report = run_inspection(asset, driver, engine)

        assert report.error is not None
        assert "Connection refused" in report.error

    @patch.object(SSHCollector, "connect", return_value=None)
    @patch.object(SSHCollector, "disconnect", return_value=None)
    @patch.object(SSHCollector, "execute", side_effect=SSHCommandError("命令执行超时"))
    def test_command_failure(self, mock_exec, mock_disconnect, mock_connect, asset, driver, engine):
        """命令执行失败 → 检查项为 UNKNOWN"""
        report = run_inspection(asset, driver, engine)

        assert report.error is None  # 连接成功
        assert len(report.check_items) > 0
        # 所有检查项应为 UNKNOWN（命令执行失败）
        for item in report.check_items:
            assert item.status == CheckStatus.UNKNOWN
            assert "采集失败" in item.message or "解析失败" in item.message
