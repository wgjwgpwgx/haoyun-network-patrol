"""子网扫描发现(P1 到场准备)

输入网段(如 192.168.0.0/24)→ ICMP ping + SNMP sysDescr 并发扫描
→ 识别存活设备及厂商 → 一键建档。

对标:Auvik 自动发现 / Cisco DNA Center Discovery
"""
from __future__ import annotations

import concurrent.futures
import ipaddress
import logging
import re
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

# sysDescr 中的厂商特征 → (vendor, device_type)
# 注意:专用型号(USG/S7506/SecPath)必须在通配(HUAWEI/Comware)之前
_VENDOR_SIGNATURES = [
    (r"USG\s?\d{3}", "huawei", "usg_firewall"),
    (r"S7506|S75\d\d", "h3c", "s7506e"),
    (r"SecPath", "h3c", "secpath_firewall"),
    (r"HUAWEI|Huawei.*S\d{4}|VRP.*software", "huawei", "vrp_switch"),
    (r"Comware|H3C|Hangzhou.*H3C", "h3c", "comware_switch"),
    (r"Cisco IOS", "cisco", "ios_switch"),
    (r"Junos:|JUNOS", "juniper", "junos"),
    (r"Ruijie|RGOS", "ruijie", "rgos_switch"),
    (r"Sangfor|NGAF", "sangfor", "ngaf_firewall"),
    (r"DPtech|DPTECH", "dptech", "fw_firewall"),
]


def _ping(host: str, timeout: int = 2) -> bool:
    """ICMP ping 单台(Windows -n 1 -w ms)。"""
    try:
        param = "-n" if sys.platform == "win32" else "-c"
        timeout_param = "-w" if sys.platform == "win32" else "-W"
        r = subprocess.run(
            ["ping", param, "1", timeout_param, str(timeout * 1000), host],
            capture_output=True, text=True, timeout=timeout + 2)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _snmp_sysdescr(host: str, community: str = "public",
                   timeout: int = 3) -> str:
    """SNMP v2c 取 sysDescr(1.3.6.1.2.1.1.1.0)。"""
    try:
        from pysnmp.hlapi.asyncio import (
            CommunityData, ObjectIdentity, ObjectType, SnmpEngine,
            UdpTransportTarget, getCmd,
        )
        import asyncio

        async def _get():
            iterator = await getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                await UdpTransportTarget((host, 161), timeout=timeout,
                                         retries=1),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
            )
            err, status, idx, binds = iterator
            if err or status:
                return ""
            return str(binds[0][1])

        return asyncio.run(_get())
    except Exception:  # noqa: BLE001
        return ""


def _snmp_sysname(host: str, community: str = "public",
                  timeout: int = 3) -> str:
    """SNMP v2c 取 sysName(1.3.6.1.2.1.1.5.0)。"""
    try:
        from pysnmp.hlapi.asyncio import (
            CommunityData, ObjectIdentity, ObjectType, SnmpEngine,
            UdpTransportTarget, getCmd,
        )
        import asyncio

        async def _get():
            iterator = await getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                await UdpTransportTarget((host, 161), timeout=timeout,
                                         retries=1),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.5.0")),
            )
            err, status, idx, binds = iterator
            if err or status:
                return ""
            return str(binds[0][1])

        return asyncio.run(_get())
    except Exception:  # noqa: BLE001
        return ""


def _identify_vendor(sysdescr: str) -> tuple[str, str] | None:
    """从 sysDescr 识别厂商与设备类型。"""
    if not sysdescr or len(sysdescr.strip()) < 10:
        return None
    for pattern, vendor, device_type in _VENDOR_SIGNATURES:
        if re.search(pattern, sysdescr, re.IGNORECASE):
            return vendor, device_type
    return None


def _scan_one(host: str, community: str = "public") -> dict[str, Any]:
    """扫描单台:ping → SNMP → 识别。"""
    result: dict[str, Any] = {"host": host, "alive": False,
                              "vendor": "", "device_type": "",
                              "sysdescr": "", "sysname": ""}
    if not _ping(host):
        return result
    result["alive"] = True

    sysdescr = _snmp_sysdescr(host, community)
    result["sysdescr"] = sysdescr[:200]
    if sysdescr:
        result["sysname"] = _snmp_sysname(host, community)
        identified = _identify_vendor(sysdescr)
        if identified:
            result["vendor"], result["device_type"] = identified
    return result


def scan_subnet(cidr: str, community: str = "public",
                max_workers: int = 20) -> list[dict[str, Any]]:
    """扫描一个网段(如 192.168.0.0/24),返回存活设备列表。

    并发 ping+SNMP,按可达排序。返回 [{host, alive, vendor,
    device_type, sysdescr, sysname}]。
    """
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise ValueError(f"无效网段: {cidr}(示例: 192.168.0.0/24)")

    hosts = [str(ip) for ip in net.hosts()]
    if len(hosts) > 512:
        hosts = hosts[:512]  # 安全限制,避免扫描超大网段

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_one, h, community): h for h in hosts}
        for future in concurrent.futures.as_completed(futures):
            try:
                r = future.result(timeout=15)
                if r["alive"]:
                    results.append(r)
            except Exception:  # noqa: BLE001
                pass

    # 按可达+已识别排序
    results.sort(key=lambda x: (x["vendor"] == "", x["host"]))
    return results
