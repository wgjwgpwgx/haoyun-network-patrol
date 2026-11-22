"""子网扫描发现测试(P1 第一批 ①)"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from patrol.netscan import (
    _identify_vendor, _ping, _scan_one, scan_subnet,
)


class TestIdentifyVendor:
    @pytest.mark.parametrize("sysdescr,vendor,device_type", [
        ("Huawei Versatile Routing Platform Software VRP S5735", "huawei", "vrp_switch"),
        ("H3C Comware Platform Software S7506E", "h3c", "s7506e"),
        ("ZTE ZXR10 5250 Series Software", "zte", "zxr10_switch"),
        ("MyPower S3100V2 Software Version 2.10.13", "maipu", "mypower_switch"),
        ("Ruijie RGOS 10.4", "ruijie", "rgos_switch"),
        ("Sangfor NGAF v8.0", "sangfor", "ngaf_firewall"),
        ("Huawei USG6000V VRP", "huawei", "usg_firewall"),
    ])
    def test_known_vendors(self, sysdescr, vendor, device_type):
        r = _identify_vendor(sysdescr)
        assert r == (vendor, device_type)

    def test_unknown(self):
        assert _identify_vendor("") is None
        assert _identify_vendor("some random device") is None


class TestScanOne:
    def test_alive_with_snmp(self):
        with patch("patrol.netscan._ping", return_value=True), \
             patch("patrol.netscan._snmp_sysdescr",
                   return_value="Huawei Versatile Routing S5735"), \
             patch("patrol.netscan._snmp_sysname", return_value="sw-01"):
            r = _scan_one("10.0.0.1")
            assert r["alive"] is True
            assert r["vendor"] == "huawei"
            assert r["device_type"] == "vrp_switch"
            assert r["sysname"] == "sw-01"

    def test_alive_no_snmp(self):
        with patch("patrol.netscan._ping", return_value=True), \
             patch("patrol.netscan._snmp_sysdescr", return_value=""):
            r = _scan_one("10.0.0.2")
            assert r["alive"] is True
            assert r["vendor"] == ""

    def test_dead(self):
        with patch("patrol.netscan._ping", return_value=False):
            r = _scan_one("10.0.0.3")
            assert r["alive"] is False


class TestScanSubnet:
    def test_invalid_cidr(self):
        with pytest.raises(ValueError, match="无效网段"):
            scan_subnet("not-a-cidr")

    def test_scan_with_mocks(self):
        def fake_scan(host, community="public"):
            if host.endswith(".1"):
                return {"host": host, "alive": True, "vendor": "huawei",
                        "device_type": "vrp_switch", "sysdescr": "Huawei",
                        "sysname": "sw-01"}
            elif host.endswith(".2"):
                return {"host": host, "alive": True, "vendor": "",
                        "device_type": "", "sysdescr": "", "sysname": ""}
            return {"host": host, "alive": False, "vendor": "",
                    "device_type": "", "sysdescr": "", "sysname": ""}

        with patch("patrol.netscan._scan_one", side_effect=fake_scan):
            results = scan_subnet("10.0.0.0/29")  # 6 台主机
        alive = [r for r in results if r["alive"]]
        assert len(alive) == 2
        # 已识别排前
        assert alive[0]["vendor"] == "huawei"
