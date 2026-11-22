"""SSH 采集器测试 - 使用 mock 模拟网络连接"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from patrol.collector.ssh import (
    SSHAuthenticationError,
    SSHCollector,
    SSHCommandError,
    SSHConnectionError,
)
from patrol.models import DeviceAsset


@pytest.fixture
def asset() -> DeviceAsset:
    return DeviceAsset(
        name="测试设备",
        host="192.168.1.1",
        vendor="h3c",
        device_type="comware_switch",
        username="admin",
        password="test123",
        timeout=10,
        command_timeout=30,
    )


class TestSSHConnect:
    @patch("patrol.collector.ssh.ConnectHandler")
    def test_connect_success(self, mock_connect, asset):
        collector = SSHCollector()
        collector.connect(asset)
        mock_connect.assert_called_once()
        # 验证密码不出现在日志中（这里只验证连接参数传递正确）
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["host"] == "192.168.1.1"
        assert call_kwargs["password"] == "test123"

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_connect_auth_failure(self, mock_connect, asset):
        mock_connect.side_effect = NetmikoAuthenticationException("auth failed")
        collector = SSHCollector()
        with pytest.raises(SSHAuthenticationError):
            collector.connect(asset)

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_connect_timeout(self, mock_connect, asset):
        mock_connect.side_effect = NetmikoTimeoutException("timeout")
        collector = SSHCollector()
        with pytest.raises(SSHConnectionError):
            collector.connect(asset)

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_connect_refused(self, mock_connect, asset):
        mock_connect.side_effect = OSError("Connection refused")
        collector = SSHCollector()
        with pytest.raises(SSHConnectionError):
            collector.connect(asset)


class TestSSHExecute:
    @patch("patrol.collector.ssh.ConnectHandler")
    def test_execute_success(self, mock_connect, asset):
        mock_conn = MagicMock()
        mock_conn.send_command.return_value = "output text"
        mock_connect.return_value = mock_conn

        collector = SSHCollector()
        collector.connect(asset)
        result = collector.execute("display version")

        assert result == "output text"
        mock_conn.send_command.assert_called_once_with(
            "display version",
            read_timeout=60,
            strip_prompt=True,
            strip_command=True,
        )

    def test_execute_without_connect(self):
        collector = SSHCollector()
        with pytest.raises(SSHCommandError, match="未连接"):
            collector.execute("display version")

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_execute_failure(self, mock_connect, asset):
        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = Exception("command failed")
        mock_connect.return_value = mock_conn

        collector = SSHCollector()
        collector.connect(asset)
        with pytest.raises(SSHCommandError):
            collector.execute("display version")


class TestSSHDisconnect:
    @patch("patrol.collector.ssh.ConnectHandler")
    def test_disconnect_success(self, mock_connect, asset):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        collector = SSHCollector()
        collector.connect(asset)
        collector.disconnect()

        mock_conn.disconnect.assert_called_once()

    def test_disconnect_without_connect(self):
        collector = SSHCollector()
        # 不应抛异常
        collector.disconnect()
