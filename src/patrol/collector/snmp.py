"""SNMP v2c 只读采集器(P1-4)

面向"甲方不提供登录账号"的场景:community 只读方式采集
sysName/sysDescr/sysUpTime 与接口状态表(ifTable),输出为
华为风格伪回显,复用现有 device_info / interface_status 解析器。

- 固定只读 OID 白名单,无命令注入面(不经 SSH 只读校验器)
- pysnmp 6.x asyncio hlapi(同步包装)
- password 字段复用为 SNMP community
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from patrol.collector.base import BaseCollector
from patrol.models import DeviceAsset

logger = logging.getLogger(__name__)

_OID_SYSNAME = "1.3.6.1.2.1.1.5.0"
_OID_SYSDESCR = "1.3.6.1.2.1.1.1.0"
_OID_SYSUPTIME = "1.3.6.1.2.1.1.3.0"
_OID_IF_TABLE = "1.3.6.1.2.1.2.2.1"
_IF_DESCR, _IF_OPER = 2, 8

_IF_STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant",
              6: "notPresent", 7: "lowerLayerDown"}


class SNMPError(Exception):
    """SNMP 采集失败(超时/community 错/不通)"""


class SNMPCollector(BaseCollector):
    """SNMP v2c 只读采集(连通性 + 基本信息 + 接口状态)"""

    def connect(self, asset: DeviceAsset) -> None:
        self._asset = asset
        self._community = asset.password or "public"
        self._dst = (asset.host, asset.port or 161)
        self._timeout = asset.timeout
        # 连接即验证:取 sysName,失败视为不通
        try:
            name = self._get(_OID_SYSNAME)
            logger.info("SNMP 连接成功 %s sysName=%s", asset.host, name)
        except SNMPError:
            raise SNMPError(
                f"SNMP 连接失败 {asset.host}:{asset.port or 161}"
                f"(检查 community 与 SNMP 服务)") from None

    def execute(self, command: str, timeout: int = 60) -> str:
        """按命令文本特征返回对应伪回显(供既有解析器消费)。"""
        low = command.lower()
        if "version" in low or "system" in low:
            return self._pseudo_version()
        if "interface" in low and "brief" in low or " ip int" in low:
            return self._pseudo_interfaces()
        return ""  # 其余命令 SNMP 通道不适用 → 上层判 UNKNOWN

    def disconnect(self) -> None:
        pass  # UDP 无连接

    # ── 采集原语 ─────────────────────────────────────────────

    def _get(self, oid: str) -> str:
        return asyncio.run(self._aget(oid))

    def _walk_if(self) -> list[tuple[str, str]]:
        return asyncio.run(self._awalk_if())

    async def _aget(self, oid: str) -> str:
        from pysnmp.hlapi.asyncio import (
            CommunityData, ObjectIdentity, ObjectType, SnmpEngine,
            UdpTransportTarget, getCmd,
        )
        iterator = await getCmd(
            SnmpEngine(),
            CommunityData(self._community, mpModel=1),
            await UdpTransportTarget(self._dst, timeout=self._timeout,
                                     retries=1),
            ObjectType(ObjectIdentity(oid)),
        )
        err, status, idx, binds = iterator
        if err:
            raise SNMPError(str(err))
        if status:
            raise SNMPError(str(status))
        return str(binds[0][1])

    async def _awalk_if(self) -> list[tuple[str, str]]:
        from pysnmp.hlapi.asyncio import (
            CommunityData, ObjectIdentity, ObjectType, SnmpEngine,
            UdpTransportTarget, nextCmd,
        )
        rows: list[tuple[str, str]] = []
        descr: dict[int, str] = {}
        status: dict[int, str] = {}
        for err, status_, idx, binds in await nextCmd(
                SnmpEngine(),
                CommunityData(self._community, mpModel=1),
                await UdpTransportTarget(self._dst, timeout=self._timeout,
                                         retries=1),
                ObjectType(ObjectIdentity(_OID_IF_TABLE)),
                lexicographicMode=False):
            if err or status_:
                break
            for oid, val in binds:
                parts = str(oid).split(".")
                if_idx = int(parts[-1]) if parts[-1].isdigit() else 0
                col = parts[-2] if len(parts) > 1 else ""
                if col == str(_IF_DESCR):
                    descr[if_idx] = str(val)
                elif col == str(_IF_OPER):
                    status[if_idx] = _IF_STATUS.get(int(val), "unknown")
            if not binds:
                break
        for i in sorted(descr):
            rows.append((descr[i], status.get(i, "unknown")))
        return rows

    # ── 伪回显构造(华为风格,复用既有解析器) ─────────────────

    def _pseudo_version(self) -> str:
        try:
            name = self._get(_OID_SYSNAME)
            descr = self._get(_OID_SYSDESCR)
            uptime_ticks = int(self._get(_OID_SYSUPTIME) or 0)
            weeks = uptime_ticks / 100 / 60 / 60 / 24 / 7
            lines = [f"sysName: {name}", f"sysDescr: {descr}"]
            if descr and "(" in descr:
                lines.insert(1, f"VRP (R) software, Version ({descr}")
            lines.append(f"uptime is {weeks:.0f} weeks")
            return "\n".join(lines)
        except SNMPError as e:
            raise e

    def _pseudo_interfaces(self) -> str:
        rows = self._walk_if()
        out = ["Interface Phy Protocol"]
        for descr, st in rows:
            out.append(f"{descr}  {st}  {st}")
        return "\n".join(out)
