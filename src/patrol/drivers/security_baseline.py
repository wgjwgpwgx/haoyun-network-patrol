"""等保 2.0 安全基线共用解析(销号清单 #4)

从 running-configuration 提取 5 项等保安全基线特征(登录失败锁定/口令策略/
管理源 ACL/日志外发/空闲超时),供华为 VRP 与 H3C Comware 系 parse_config_cur
嵌套输出;NTP 同步状态独立解析。

配置特征基于等保 2.0 基本要求与华为/H3C 加固惯例编写,标注:待真机验证。
"""
from __future__ import annotations

import re
from typing import Any


def extract_dengbao_checks(config: str) -> list[dict[str, Any]]:
    """提取 5 项等保安全基线嵌套检查(格式与 config_cur 的 checks 一致)。"""
    login_locked = bool(re.search(
        r"login-attempt|lock-out|password-control\s+enable|"
        r"local-aaa-user\s+password\s+policy", config, re.IGNORECASE))
    policy_ok = bool(re.search(
        r"password\s+(min-)?length|password-control\s+length|"
        r"password\s+complexity|complexity\s*\(?", config, re.IGNORECASE))
    acl_enabled = bool(re.search(
        r"acl\s+\S+\s+inbound", config, re.IGNORECASE))
    syslog_enabled = bool(re.search(
        r"info-center\s+loghost|logging\s+host", config, re.IGNORECASE))
    timeouts = [int(m) for m in re.findall(r"idle-timeout\s+(\d+)", config)]
    idle_min = min(timeouts) if timeouts else None  # 取最小(最严格线路上限)
    timeout_ok = idle_min is not None and idle_min <= 10

    return [
        {"name": "login_lock", "category": "安全基线",
         "parsed": {"login_locked": login_locked}},
        {"name": "password_policy", "category": "安全基线",
         "parsed": {"policy_ok": policy_ok}},
        {"name": "mgmt_acl", "category": "安全基线",
         "parsed": {"acl_enabled": acl_enabled}},
        {"name": "syslog_external", "category": "安全基线",
         "parsed": {"enabled": syslog_enabled}},
        {"name": "vty_idle_timeout", "category": "安全基线",
         "parsed": {"timeout_ok": timeout_ok, "idle_minutes": idle_min}},
    ]


def parse_ntp_status(output: str) -> dict[str, Any]:
    """解析 display ntp-service status

    标准格式:
      clock status: synchronized
      stratum: 2
      reference: 1.1.1.1
    """
    synced = bool(re.search(r"clock\s+status\s*[:：]?\s*synchronized",
                            output, re.IGNORECASE))
    stratum = None
    reference = ""
    m = re.search(r"stratum\s*[:：]?\s*(\d+)", output, re.IGNORECASE)
    if m:
        stratum = int(m.group(1))
    m = re.search(r"reference\s*[:：]?\s*(\S+)", output, re.IGNORECASE)
    if m:
        reference = m.group(1)
    return {"synced": synced, "stratum": stratum, "reference": reference}
