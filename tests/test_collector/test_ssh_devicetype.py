"""H1 回归测试:SSH 采集器的 netmiko device_type 解析

背景缺陷(2026-09-22 代码层验收发现):ssh.py 曾按 vendor + "_" + device_type
拼接 netmiko 类型,拼出 huawei_vrp_switch / ruijie_rgos_switch 等非法值,
导致华为、锐捷 SSH 巡检必然失败。修复后以各 Driver 声明的
netmiko_device_type 属性为单一数据源。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import patrol.drivers  # noqa: F401  统一注册
from patrol.collector.ssh import (
    SSHCollector,
    SSHConnectionError,
    _resolve_netmiko_device_type,
)
from patrol.drivers.registry import list_drivers, get_driver
from patrol.models import DeviceAsset


def _asset(vendor: str, device_type: str) -> DeviceAsset:
    return DeviceAsset(
        name="t", host="192.0.2.1", vendor=vendor,
        device_type=device_type, username="u", password="p",
    )


class TestNetmikoDeviceTypeResolution:
    def test_h3c_uses_hp_comware(self):
        for dt in ("s7506e", "comware_switch"):
            assert _resolve_netmiko_device_type(_asset("h3c", dt)) == "hp_comware"

    def test_huawei_uses_huawei(self):
        # 修复前会拼出非法的 "huawei_vrp_switch"
        assert _resolve_netmiko_device_type(_asset("huawei", "vrp_switch")) == "huawei"

    def test_ruijie_uses_ruijie_os(self):
        # 修复前会拼出非法的 "ruijie_rgos_switch"
        assert _resolve_netmiko_device_type(_asset("ruijie", "rgos_switch")) == "ruijie_os"

    def test_generic_driver_rejected_with_clear_error(self):
        """Web/API 设备(sangfor/dptech)声明 generic,SSH 应给出明确报错。"""
        for vendor, dt in (("sangfor", "ngaf_firewall"), ("dptech", "fw_firewall")):
            with pytest.raises(SSHConnectionError, match="不支持 SSH"):
                _resolve_netmiko_device_type(_asset(vendor, dt))

    def test_unknown_driver_rejected(self):
        with pytest.raises(KeyError):
            _resolve_netmiko_device_type(_asset("foo", "bar"))


class TestDriverTypeValidity:
    def test_every_ssh_capable_driver_declares_valid_netmiko_type(self):
        """所有声明了非 generic netmiko 类型的驱动,其类型必须在 netmiko 支持清单内。

        这是 H1 的根本回归测试:今后新增厂商驱动若声明非法类型,此处立即失败。
        """
        import netmiko

        checked = 0
        for key in list_drivers():
            vendor, dt = key.split("/", 1)
            driver = get_driver(vendor, dt)
            nm_type = driver.netmiko_device_type
            if not nm_type or nm_type == "generic":
                continue  # Web/API 采集设备,不适用 SSH
            assert nm_type in netmiko.platforms, (
                f"{key} 声明了 netmiko 不支持的类型: {nm_type!r}"
            )
            checked += 1
        assert checked >= 3, "SSH 驱动数量异常,注册可能未生效"


class TestTelnetDeviceType:
    """Telnet 通道回归(销号清单 #1):netmiko *_telnet 类型映射与路由。"""

    def test_all_telnet_types_valid(self):
        """声明了 telnet 类型的驱动,其类型必须在 netmiko 平台清单内。"""
        import netmiko

        checked = 0
        for key in list_drivers():
            vendor, dt = key.split("/", 1)
            driver = get_driver(vendor, dt)
            tel = driver.netmiko_telnet_device_type
            if not tel:
                continue  # Web/API 设备不支持 Telnet,合法
            assert tel in netmiko.platforms, f"{key} 非法 telnet 类型: {tel}"
            checked += 1
        assert checked >= 8  # 8 个 CLI 驱动(含继承防火墙)

    def test_expected_mapping(self):
        assert get_driver("huawei", "vrp_switch").netmiko_telnet_device_type == "huawei_telnet"
        assert get_driver("huawei", "usg_firewall").netmiko_telnet_device_type == "huawei_telnet"
        assert get_driver("h3c", "s7506e").netmiko_telnet_device_type == "hp_comware_telnet"
        assert get_driver("h3c", "secpath_firewall").netmiko_telnet_device_type == "hp_comware_telnet"

    def test_resolve_routes_by_login_method(self):
        a = DeviceAsset(name="t", host="192.0.2.1", vendor="huawei",
                        device_type="vrp_switch", login_method="telnet")
        assert _resolve_netmiko_device_type(a) == "huawei_telnet"

    def test_web_device_rejects_telnet(self):
        a = DeviceAsset(name="t", host="192.0.2.1", vendor="sangfor",
                        device_type="ngaf_firewall", login_method="telnet")
        with pytest.raises(SSHConnectionError, match="不支持 Telnet"):
            _resolve_netmiko_device_type(a)


class TestConsoleChannel:
    """销号清单 #13a:本机串口通道(host=COM 口,port=波特率)。"""

    def test_resolve_console(self):
        a = DeviceAsset(name="t", host="COM3", vendor="huawei",
                        device_type="vrp_switch", login_method="console")
        assert _resolve_netmiko_device_type(a) == "cisco_ios_serial"

    @patch("patrol.collector.ssh.ConnectHandler")
    def test_connect_uses_serial_settings(self, mock_ch):
        a = DeviceAsset(name="t", host="COM3", vendor="huawei",
                        device_type="vrp_switch", login_method="console",
                        username="u", password="p", port=115200)
        SSHCollector().connect(a)
        kwargs = mock_ch.call_args.kwargs
        assert kwargs["serial_settings"] == {"port": "COM3",
                                             "baudrate": 115200}
        assert "host" not in kwargs and "port" not in kwargs
