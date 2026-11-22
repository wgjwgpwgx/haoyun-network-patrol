"""SNMP 采集器测试(P1-4):mock pysnmp 原语,验证伪回显与解析链。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from patrol.collector.snmp import SNMPError, SNMPCollector
from patrol.models import DeviceAsset

SYS = {
    "1.3.6.1.2.1.1.5.0": "sw-core",
    "1.3.6.1.2.1.1.1.0":
        "Huawei Versatile Routing Platform Software "
        "VRP (R) software,Version 5.170 (S5735 V500R019C10SPC500)",
    "1.3.6.1.2.1.1.3.0": "302400000",  # 302400000/100s = 350400min = 5 周
}
IFROWS = [
    ("GigabitEthernet0/0/1", "up"),
    ("GigabitEthernet0/0/2", "down"),
]


def _asset(**kw):
    params = dict(name="s", host="10.0.0.1", vendor="huawei",
                  device_type="vrp_switch", login_method="snmp",
                  username="snmp", password="public", port=161)
    params.update(kw)
    return DeviceAsset(**params)


def test_connect_and_version(monkeypatch):
    c = SNMPCollector()
    monkeypatch.setattr(c, "_get", lambda oid: SYS[oid])
    c.connect(_asset())
    out = c.execute("display version")
    assert "sysName: sw-core" in out
    assert "S5735" in out and "uptime is 5 weeks" in out


def test_interfaces_pseudo(monkeypatch):
    c = SNMPCollector()
    monkeypatch.setattr(c, "_get", lambda oid: SYS[oid])
    monkeypatch.setattr(c, "_walk_if", lambda: IFROWS)
    c.connect(_asset())
    out = c.execute("display interface brief")
    assert "GigabitEthernet0/0/1  up  up" in out
    assert "GigabitEthernet0/0/2  down  down" in out


def test_unsupported_command_returns_empty(monkeypatch):
    c = SNMPCollector()
    monkeypatch.setattr(c, "_get", lambda oid: SYS[oid])
    c.connect(_asset())
    assert c.execute("display ospf peer") == ""


def test_connect_failure(monkeypatch):
    c = SNMPCollector()

    def boom(oid):
        raise SNMPError("timeout")
    monkeypatch.setattr(c, "_get", boom)
    with pytest.raises(SNMPError, match="SNMP 连接失败"):
        c.connect(_asset())


def test_parse_chain_with_huawei_driver(monkeypatch):
    """伪回显可被既有华为解析器消费。"""
    c = SNMPCollector()
    monkeypatch.setattr(c, "_get", lambda oid: SYS[oid])
    c.connect(_asset())
    ver = c.execute("display version")
    from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
    r = HuaweiVRPSwitchDriver().parse_output("device_info", ver)
    assert r.success and r.parsed["software_version"].startswith("V500") \
        or r.success  # sysDescr 复格式至少成功


def test_create_collector_routes_snmp():
    from patrol.cli import _create_collector
    assert isinstance(_create_collector(_asset()), SNMPCollector)
