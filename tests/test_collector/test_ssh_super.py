"""SSH 采集器 Super 密码提权测试"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from patrol.collector.ssh import SSHCollector
from patrol.models import DeviceAsset


def _asset(**overrides) -> DeviceAsset:
    params = dict(name="t", host="192.0.2.1", vendor="h3c",
                  device_type="comware_switch", username="u", password="p")
    params.update(overrides)
    return DeviceAsset(**params)


class TestSuperMode:
    @patch("patrol.collector.ssh.ConnectHandler")
    def test_super_password_sent_when_configured(self, mock_handler):
        conn = MagicMock()
        mock_handler.return_value = conn
        # super 命令回显出现密码提示 → 应回填 super 密码
        conn.send_command_timing.side_effect = [
            "Password: ", "Now user privilege is 3"
        ]

        SSHCollector().connect(_asset(super_password="sup987"))

        calls = [c.args[0] for c in conn.send_command_timing.call_args_list]
        assert calls[0] == "super"
        assert calls[1] == "sup987"

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_no_super_interaction_without_password(self, mock_handler):
        conn = MagicMock()
        mock_handler.return_value = conn

        SSHCollector().connect(_asset())

        conn.send_command_timing.assert_not_called()

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_no_password_prompt_still_connects(self, mock_handler):
        """super 命令未出现密码提示(已是最高权限)时不应发送密码。"""
        conn = MagicMock()
        mock_handler.return_value = conn
        conn.send_command_timing.return_value = "Already super user."

        SSHCollector().connect(_asset(super_password="sup987"))

        assert conn.send_command_timing.call_count == 1
        sent = conn.send_command_timing.call_args_list[0].args[0]
        assert sent == "super"

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_super_failure_does_not_break_connection(self, mock_handler):
        conn = MagicMock()
        mock_handler.return_value = conn
        conn.send_command_timing.side_effect = RuntimeError("timeout")

        collector = SSHCollector()
        collector.connect(_asset(super_password="sup987"))  # 不应抛异常
        collector.disconnect()
