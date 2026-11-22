"""LLDP 邻居解析与拓扑数据(P1-2)

支持三种回显风格(标准格式,待真机验证):
  huawei  列表行:本地接口 对端设备 对端接口 (华为/锐捷/Juniper 列序)
  cisco   列表行:对端设备 本地接口 ... 对端接口
  h3c     块状:   端口章节内 PortID/System name 键值对
"""
from __future__ import annotations

import re
from typing import Any


def _clean(tokens: list[str]) -> bool:
    header_words = ("intf", "device", "neighbor", "chassisid", "portid",
                    "local", "system", "hold", "capability", "total",
                    "neighbor-information", "lldp")
    return not any(w in tokens[0].lower() for w in header_words) and \
        len(tokens) >= 3


def parse_lldp(output: str, style: str = "huawei") -> dict[str, Any]:
    neighbors: list[dict[str, str]] = []

    if style == "h3c":
        local = ""
        for line in output.splitlines():
            m = re.search(r"port\s+\d+\[(.+?)\]", line, re.IGNORECASE)
            if m:
                local = m.group(1).strip()
                continue
            m = re.search(r"PortID.*?:\s*(.+)", line)
            if m and local:
                peer_port = m.group(1).strip()
                # System name 通常紧随其后
                neighbors.append({"local_intf": local,
                                  "peer_device": "", "peer_port": peer_port})
                continue
            m = re.search(r"System name\s*[:：]\s*(\S+)", line)
            if m and neighbors and not neighbors[-1]["peer_device"]:
                neighbors[-1]["peer_device"] = m.group(1)
        neighbors = [n for n in neighbors if n["peer_device"]]
    else:
        for line in output.splitlines():
            tokens = line.split()
            if len(tokens) < 3 or not _clean(tokens):
                continue
            if style == "cisco":
                peer, local, port = tokens[0], tokens[1], tokens[-1]
            else:  # huawei/juniper/ruijie 列序
                local, peer, port = tokens[0], tokens[1], tokens[2]
            if re.match(r"^\d+[smhd]?$", local):   # hold-time 落首位等异常
                continue
            neighbors.append({"local_intf": local, "peer_device": peer,
                              "peer_port": port})

    return {"neighbors": neighbors, "neighbor_count": len(neighbors)}
