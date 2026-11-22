"""华为 VRP 交换机回显解析器

基于 S5735-S48P4X (V500R019C10SPC500) 真实回显编写。
无法解析的字段返回 None / 0 / [] / False，不猜测。
"""
from __future__ import annotations

import re
from typing import Any


def parse_device_info(output: str) -> dict[str, Any]:
    """解析 display version

    真实格式：
      VRP (R) software, Version 5.170 (S5735‑S48P4X V500R019C10SPC500)
      HUAWEI S5735‑S48P4X uptime is 35 weeks, 4 days, 22 hours, 13 minutes
      Main Board Serial No:2102354835106F000127
    """
    info: dict[str, Any] = {
        "model": "",
        "device_name": "",
        "software_version": "",
        "uptime": "",
        "serial_number": "",
    }

    for line in output.splitlines():
        # 型号 + 版本：Version 5.170 (S5735‑S48P4X V500R019C10SPC500)
        m = re.search(r"Version\s+[\d.]+\s+\((\S+)\s+(V\S+)\)", line)
        if m:
            info["model"] = m.group(1)
            info["software_version"] = m.group(2)

        # 运行时间：HUAWEI S5735‑S48P4X uptime is 35 weeks, ...
        m = re.search(r"uptime is\s+(.+?)(?:\s*$)", line, re.IGNORECASE)
        if m:
            info["uptime"] = m.group(1).strip()

        # 序列号：Main Board Serial No:2102354835106F000127
        m = re.search(r"Main Board Serial No\s*:\s*(\S+)", line, re.IGNORECASE)
        if m:
            info["serial_number"] = m.group(1).strip()

    return info


def parse_cpu_usage(output: str) -> dict[str, Any]:
    """解析 display cpu-usage

    真实格式：
      CPU Usage: 14.3%   Max: 72.6%
      CPU utilization for ten seconds:14.3%  one minute:13.7%  five minutes:12.1%
    """
    result: dict[str, Any] = {
        "usage_percent": None,
        "usage_10s": None,
        "usage_1m": None,
        "usage_5m": None,
        "max_usage": None,
    }

    # Control Plane CPU Usage: 14.3%
    for line in output.splitlines():
        if "Control Plane" in line:
            # 下一行包含 CPU Usage
            continue
        # CPU Usage: 14.3%   Max: 72.6%
        m = re.search(r"^CPU Usage:\s*([\d.]+)%\s+Max:\s*([\d.]+)%", line.strip())
        if m and result["usage_percent"] is None:
            result["usage_percent"] = float(m.group(1))
            result["max_usage"] = float(m.group(2))
            continue

        # CPU utilization for ten seconds:14.3%  one minute:13.7%  five minutes:12.1%
        m = re.search(
            r"ten seconds:([\d.]+)%\s+one minute:([\d.]+)%\s+five minutes:([\d.]+)%",
            line,
        )
        if m and result["usage_10s"] is None:
            result["usage_10s"] = float(m.group(1))
            result["usage_1m"] = float(m.group(2))
            result["usage_5m"] = float(m.group(3))

    # 取 Control Plane 的值作为主指标
    if result["usage_percent"] is not None:
        result["usage_percent"] = round(result["usage_percent"])
    return result


def parse_memory_usage(output: str) -> dict[str, Any]:
    """解析 display memory-usage

    真实格式：
      System Total Memory Is: 1610612736 bytes
      Total Memory Used Is: 418759315 bytes
      Memory Using Percentage Is: 26%
    """
    result: dict[str, Any] = {"total_bytes": None, "used_bytes": None, "usage_percent": None}

    for line in output.splitlines():
        m = re.search(r"System Total Memory Is:\s*(\d+)\s+bytes", line)
        if m:
            result["total_bytes"] = int(m.group(1))

        m = re.search(r"Total Memory Used Is:\s*(\d+)\s+bytes", line)
        if m:
            result["used_bytes"] = int(m.group(1))

        m = re.search(r"Memory Using Percentage Is:\s*(\d+)%", line)
        if m:
            result["usage_percent"] = int(m.group(1))

    return result


def parse_interface_status(output: str) -> dict[str, Any]:
    """解析 display interface brief

    真实格式（有表头和注释行）：
      Interface                         PHY   Protocol InUti OutUti   inErrors  outErrors
      GigabitEthernet0/0/1              up         up  0.01%  0.03%          0          0
      GigabitEthernet0/0/5‑48         down       down     0%     0%          0          0
      Vlanif10                          up         up      ‑      ‑          0          0
    """
    result: dict[str, Any] = {
        "interfaces": [],
        "abnormal_interfaces": [],
        "abnormal_count": 0,
        "total": 0,
        "error_interfaces": [],
    }

    for line in output.splitlines():
        line = line.strip()
        # 跳过空行、注释行、表头
        if not line or line.startswith(("PHY:", "*down", "^down", "(l)", "(s)", "(b)", "(e)", "(d)", "(DL)", "(T)", "Interface")):
            continue

        # 匹配接口行：接口名 PHY Protocol InUti OutUti inErrors outErrors
        # InUti/OutUti 可能是百分比或 ‑（U+2011 非断行连字符，表示无数据）
        m = re.match(
            r"((?:GigabitEthernet|XGigabitEthernet|Vlanif|MEth|Eth-Trunk|LoopBack|NULL)\S+)\s+"
            r"(up|\*?down|down)\s+"
            r"(up|down)\s+"
            r"(\S+)\s+"
            r"(\S+)\s+"
            r"(\d+)\s+"
            r"(\d+)",
            line,
        )
        if m:
            iface = m.group(1)
            phy = m.group(2).replace("*", "")
            proto = m.group(3)
            in_errors = int(m.group(6))
            out_errors = int(m.group(7))

            entry = {
                "name": iface,
                "phy_status": phy,
                "proto_status": proto,
                "in_errors": in_errors,
                "out_errors": out_errors,
            }
            result["interfaces"].append(entry)
            result["total"] += 1

            # 异常：物理或协议 down
            if phy == "down" or proto == "down":
                result["abnormal_interfaces"].append(iface)
                result["abnormal_count"] += 1

            # 错误包
            if in_errors > 0 or out_errors > 0:
                result["error_interfaces"].append(iface)

    return result


def parse_fan_status(output: str) -> dict[str, Any]:
    """解析 display fan

    真实格式：
      Fan 1:
        Status: Normal
    """
    result: dict[str, Any] = {"fans": [], "fan_count": 0, "abnormal_count": 0}
    current_fan = ""

    for line in output.splitlines():
        # Fan 1:
        m = re.match(r"Fan\s+(\d+)\s*:", line)
        if m:
            current_fan = f"Fan {m.group(1)}"
            continue

        # Status: Normal
        m = re.match(r"\s*Status:\s*(\S+)", line)
        if m and current_fan:
            state = m.group(1)
            result["fans"].append({"name": current_fan, "state": state})
            result["fan_count"] += 1
            if state.lower() != "normal":
                result["abnormal_count"] += 1
            current_fan = ""

    return result


def parse_power_status(output: str) -> dict[str, Any]:
    """解析 display power

    真实格式：
      Power 1:
        Status: Normal
    """
    result: dict[str, Any] = {"powers": [], "power_count": 0, "abnormal_count": 0}
    current_power = ""

    for line in output.splitlines():
        m = re.match(r"Power\s+(\d+)\s*:", line)
        if m:
            current_power = f"Power {m.group(1)}"
            continue

        m = re.match(r"\s*Status:\s*(\S+)", line)
        if m and current_power:
            state = m.group(1)
            result["powers"].append({"name": current_power, "state": state})
            result["power_count"] += 1
            if state.lower() != "normal":
                result["abnormal_count"] += 1
            current_power = ""

    return result


def parse_logbuffer(output: str) -> dict[str, Any]:
    """解析 display logbuffer

    真实格式（华为 VRP 日志）：
      %2026‑09‑21T14:18:22.412 HW_SW_CORE_02 %%01SHELL/6/SHELL_CMD(l):...
      严重级别在 /N/ 中：0-3 为告警
    """
    result: dict[str, Any] = {"total_lines": 0, "error_count": 0, "errors": []}
    severity_pattern = re.compile(r"/(\d)/")

    for line in output.splitlines():
        line = line.strip()
        if not line or not line.startswith("%"):
            continue
        result["total_lines"] += 1

        m = severity_pattern.search(line)
        if m:
            level = int(m.group(1))
            if level <= 3:
                result["error_count"] += 1
                result["errors"].append(line)

    return result


def parse_routing_table(output: str) -> dict[str, Any]:
    """解析 display ip routing-table

    真实格式：
      Destinations : 421        Routes : 421
    """
    result: dict[str, Any] = {"destinations": 0, "routes": 0}

    for line in output.splitlines():
        m = re.search(r"Destinations\s*:\s*(\d+)", line)
        if m:
            result["destinations"] = int(m.group(1))
        m = re.search(r"Routes\s*:\s*(\d+)", line)
        if m:
            result["routes"] = int(m.group(1))

    return result


def parse_config_cur(output: str) -> dict[str, Any]:
    """解析 display current-configuration

    提取子检查项：telnet、snmp、vty、stp。
    """
    telnet_enabled = False
    ssh_enabled = False
    communities: list[dict[str, str]] = []
    has_auth = False
    has_acl = False
    ssh_only = False
    stp_enabled = False

    in_vty = False
    for line in output.splitlines():
        stripped = line.strip().lower()

        # 华为 VRP 区分 telnet（不安全）和 stelnet（基于 SSH）
        if re.match(r"telnet\s+server\s+enable", stripped):
            telnet_enabled = True
        if re.match(r"(stelnet|ssh)\s+server\s+enable", stripped):
            ssh_enabled = True

        # SNMP
        m = re.search(r"snmp-agent\s+community\s+(read|write)\s+(\S+)", line, re.IGNORECASE)
        if m:
            communities.append({"level": m.group(1), "community": m.group(2)})

        # VTY
        if re.match(r"user-interface\s+vty", stripped):
            in_vty = True
        elif in_vty:
            if stripped == "#" or stripped == "return":
                in_vty = False
            else:
                if "authentication-mode" in stripped:
                    has_auth = True
                if "acl" in stripped and "inbound" in stripped:
                    has_acl = True
                if "protocol inbound ssh" in stripped:
                    ssh_only = True

        # STP
        if re.match(r"stp\s+enable", stripped):
            stp_enabled = True

    dangerous = [c for c in communities if c["community"].lower() in ("public", "private")]

    return {
        "checks": [
            {
                "name": "telnet_service",
                "category": "管理服务",
                "parsed": {"telnet_enabled": telnet_enabled, "ssh_enabled": ssh_enabled},
            },
            {
                "name": "snmp_community",
                "category": "SNMP",
                "parsed": {
                    "communities": communities,
                    "community_count": len(communities),
                    "dangerous_count": len(dangerous),
                    "has_dangerous": len(dangerous) > 0,
                },
            },
            {
                "name": "vty_auth",
                "category": "VTY 安全",
                "parsed": {
                    "has_authentication": has_auth,
                    "has_acl": has_acl,
                    "ssh_only": ssh_only,
                },
            },
            {
                "name": "stp_status",
                "category": "生成树",
                "parsed": {"stp_enabled": stp_enabled, "stp_root_primary": False},
            },
        ]
    }


# ── 九大类扩展检查(销号清单 #2,标准输出格式,待真机验证) ────────


def parse_temperature(output: str) -> dict[str, Any]:
    """解析 display temperature(VRP)

    标准格式:
      Slot No. 1
      Temperature status: Normal
      Temperature value: 38
    """
    result: dict[str, Any] = {"status": "", "value": None, "abnormal_count": 0}
    for line in output.splitlines():
        m = re.search(r"Temperature status\s*:\s*(\S+)", line, re.IGNORECASE)
        if m:
            result["status"] = m.group(1)
        m = re.search(r"Temperature value\s*:\s*(\d+)", line, re.IGNORECASE)
        if m:
            result["value"] = int(m.group(1))
    if (result["status"] and result["status"].lower() != "normal") or (
            result["value"] is not None and result["value"] > 60):
        result["abnormal_count"] = 1
    return result


_TRANS_PWR = re.compile(
    r"([Tt]x|[Rr]x)\s*[Pp]ower\(dBm\)\s*:\s*(-?[\d.]+)\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]")
_TRANS_IF = re.compile(r"(?:Interface[:\s]|transceiver diagnostics)\s*(\S+)")


def parse_transceiver(output: str) -> dict[str, Any]:
    """解析 display transceiver diagnosis(光模块 DDM 收发光功率 vs 厂商门限)"""
    modules: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in output.splitlines():
        m = _TRANS_IF.search(line)
        if m and ("diagnosis" in line.lower() or line.strip().startswith("Interface")):
            if current:
                modules.append(current)
            current = {"interface": m.group(1), "tx": None, "rx": None,
                       "tx_ok": True, "rx_ok": True}
            continue
        m = _TRANS_PWR.search(line)
        if m and current is not None:
            kind = m.group(1).lower()
            value, low, high = float(m.group(2)), float(m.group(3)), float(m.group(4))
            ok = low <= value <= high
            current[kind] = value
            current[f"{kind}_ok"] = ok
    if current:
        modules.append(current)
    abnormal = [x for x in modules if not (x.get("tx_ok") and x.get("rx_ok"))]
    return {"modules": modules, "total": len(modules), "abnormal_count": len(abnormal),
            "abnormal": [{"interface": x["interface"]} for x in abnormal]}


def parse_ospf_neighbor(output: str) -> dict[str, Any]:
    """解析 display ospf peer(邻居状态应全为 Full)"""
    result: dict[str, Any] = {"total": 0, "full_count": 0, "abnormal_count": 0,
                              "abnormal": []}
    for line in output.splitlines():
        # 数据行:邻居ID(IP) + Address(IP) + Pri + DeadTime + State
        m = re.match(
            r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+"      # 邻居 ID
            r"\d{1,3}(?:\.\d{1,3}){3}\s+"             # Address
            r"\d+\s+\S+\s+(\S+)",                     # Pri + Dead + State
            line)
        if not m:
            continue
        result["total"] += 1
        state = m.group(2)
        if state.lower().startswith("full"):
            result["full_count"] += 1
        else:
            result["abnormal_count"] += 1
            result["abnormal"].append({"neighbor": m.group(1), "state": state})
    return result


def parse_arp_count(output: str) -> dict[str, Any]:
    """解析 display arp all 尾部统计(Total:N / Total number of entries: N)"""
    result: dict[str, Any] = {"arp_count": None}
    for line in output.splitlines():
        m = re.search(r"Total\s+(?:number of\s+)?entries?\s*[:：]?\s*(\d+)", line,
                      re.IGNORECASE)
        if m:
            result["arp_count"] = int(m.group(1))
            break
        m = re.search(r"^\s*Total\s*[:：]\s*(\d+)\s*$", line, re.IGNORECASE)
        if m:
            result["arp_count"] = int(m.group(1))
            break
    return result


def parse_storage(output: str) -> dict[str, Any]:
    """解析 dir(flash 使用率,日志盘满会导致设备异常)"""
    result: dict[str, Any] = {"total_kb": None, "free_kb": None, "used_percent": None}
    m = re.search(
        r"([\d,]+)\s*KB\s+total\s*\(([\d,]+)\s*KB\s+free\)", output, re.IGNORECASE)
    if m:
        total = int(m.group(1).replace(",", ""))
        free = int(m.group(2).replace(",", ""))
        result["total_kb"], result["free_kb"] = total, free
        if total:
            result["used_percent"] = round((1 - free / total) * 100)
    return result


def parse_config_diff(output: str) -> dict[str, Any]:
    """解析 compare configuration(running 与 startup 一致性,未保存=高危)"""
    same = bool(re.search(r"the same as", output, re.IGNORECASE))
    diff_lines = [ln for ln in output.splitlines()
                  if ln.strip() and "same as" not in ln and not ln.startswith("<")
                  and not ln.startswith("Compare")][:20]
    return {"has_diff": (not same and bool(diff_lines)),
            "diff_lines": diff_lines if not same else []}


def parse_reboot_reason(output: str) -> dict[str, Any]:
    """解析 display rebootReason/display reboot-info(部分机型不支持→UNKNOWN)"""
    result: dict[str, Any] = {"reason": "", "abnormal_count": 0}
    for line in output.splitlines():
        m = re.search(r"(?:reboot|reset)\s+(?:reason|cause)\s*[:：]\s*(.+)", line,
                      re.IGNORECASE)
        if m:
            result["reason"] = m.group(1).strip()
    reason = result["reason"].lower()
    if reason and any(k in reason for k in ("crash", "abnormal", "exception", "error")):
        result["abnormal_count"] = 1
    return result


# 等保基线嵌套项(销号清单 #4):包装原 parse_config_cur,追加 5 项基线检查
_parse_config_cur_base = parse_config_cur


def parse_config_cur(output: str) -> dict[str, Any]:  # noqa: F811
    from patrol.drivers.security_baseline import extract_dengbao_checks

    result = _parse_config_cur_base(output)
    result["checks"] = result.get("checks", []) + extract_dengbao_checks(output)
    return result


def parse_ntp_status(output: str) -> dict[str, Any]:
    """解析 display ntp-service status(等保:NTP 时间同步)。"""
    from patrol.drivers.security_baseline import parse_ntp_status as _p
    return _p(output)
