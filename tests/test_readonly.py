"""只读白名单校验器测试(销号清单 #7 / U-5)"""
from __future__ import annotations

import pytest

import patrol.drivers  # noqa: F401
from patrol.collector.ssh import SSHCollector, SSHCommandError
from patrol.drivers.registry import list_drivers, get_driver
from patrol.readonly import ReadOnlyViolation, assert_readonly


class TestAllow:
    @pytest.mark.parametrize("cmd", [
        "display cpu-usage", "show version", "dir flash:",
        "compare configuration", "  display  device  ",
        "SHOW ENV ALL", "display transceiver diagnosis interface",
        "display reboot-info",            # 连字符复合只读,不得误伤
        "display current-configuration",  # 含 "configure"? 不,configuration 独立词
        "screen-length disable",
        "show ip interface brief",
    ])
    def test_readonly_commands_pass(self, cmd):
        assert_readonly(cmd)  # 不抛即通过


class TestBlock:
    @pytest.mark.parametrize("cmd", [
        "save", "save config", "undo stp enable", "delete /unreserved flash:xx",
        "reboot", "reboot fast", "reset saved-configuration",
        "system-view", "sysname newname", "configure terminal",
        "erase startup-config", "write memory", "shell ls /",
        "copy flash:xx tftp://1.1.1.1", "clear arp all",
        "mkdir flash:test", "format flash:", "local-user bad",
        "display cpu-usage; save",      # 拼接写操作
        "display cpu | include save; reboot fast",
        "tftp 1.1.1.1 get xx",
    ])
    def test_dangerous_commands_blocked(self, cmd):
        with pytest.raises(ReadOnlyViolation, match="拒绝下发"):
            assert_readonly(cmd)

    def test_unknown_prefix_blocked(self):
        with pytest.raises(ReadOnlyViolation):
            assert_readonly("foo bar")

    def test_empty_blocked(self):
        with pytest.raises(ReadOnlyViolation):
            assert_readonly("  ")


class TestSSHIntegration:
    def test_execute_blocked_before_send(self, monkeypatch):
        collector = SSHCollector()
        collector._conn = object()  # 伪连接,若下发会 AttributeError 暴露
        collector._host = "1.2.3.4"
        with pytest.raises(SSHCommandError, match="拒绝下发"):
            collector.execute("save")
        with pytest.raises(SSHCommandError, match="拒绝下发"):
            collector.execute("display cpu; system-view")

    def test_execute_allows_display(self, monkeypatch):
        collector = SSHCollector()
        collector._host = "1.2.3.4"
        sent = []
        monkeypatch.setattr(
            collector, "_conn",
            type("C", (), {"send_command": staticmethod(
                lambda cmd, **kw: sent.append(cmd) or "OK")})())
        out = collector.execute("display cpu-usage")
        assert out == "OK" and sent == ["display cpu-usage"]


class TestAllCommandTables:
    def test_every_ssh_command_is_readonly(self):
        """全部 SSH 驱动的命令表白名单化(机制化"逐条评审"):
        未来任何人向命令表加入写命令,此测试立即失败。"""
        checked = 0
        for key in list_drivers():
            driver = get_driver(*key.split("/", 1))
            if driver.netmiko_device_type == "generic":
                continue  # Web/API 采集不走 SSH 通道
            for c in driver.get_check_commands():
                assert_readonly(c.command)  # 违规即 AssertionError 带 reason
                checked += 1
        assert checked >= 80, f"命令表扫描异常: 仅 {checked} 条"
