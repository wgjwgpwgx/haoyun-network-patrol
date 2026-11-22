"""H3C 家族(Comware/S7506E/SecPath)共用扩展解析

温度命令 H3C 为 display environment(格式与华为 display temperature 不同),
独立实现;其余六项(光模块/OSPF/ARP/存储/配置一致性/重启原因)的输出格式
与 VRP 同族,直接复用 huawei.parsers 的纯函数。
标准输出格式编写,待真机验证。
"""
from __future__ import annotations

import re
from typing import Any

from patrol.drivers.huawei.parsers import (
    parse_arp_count,
    parse_config_diff,
    parse_ospf_neighbor,
    parse_reboot_reason,
    parse_storage,
    parse_transceiver,
)

__all__ = [
    "parse_temperature_h3c", "parse_transceiver", "parse_ospf_neighbor",
    "parse_arp_count", "parse_storage", "parse_config_diff", "parse_reboot_reason",
]


def parse_temperature_h3c(output: str) -> dict[str, Any]:
    """解析 display environment

    标准格式:
      System temperature information:
      Slot 1
        Sensor 1: 38 C
      Slot 2
        Sensor 1: 41 C
    """
    values: list[int] = []
    for m in re.finditer(r"Sensor\s+\S+\s*[:：]\s*(-?\d+)\s*C", output, re.IGNORECASE):
        values.append(int(m.group(1)))
    over = [v for v in values if v > 60]
    return {
        "values": values, "max_value": max(values) if values else None,
        "abnormal_count": len(over),
    }
