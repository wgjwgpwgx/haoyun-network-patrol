"""设备自动识别(销号清单 #6 / U-2)

工程师只填 IP + 用户名 + 密码,工具用 netmiko generic 通道登录
(SSH 失败自动降级 Telnet),执行 display/show version,按回显特征词
判定厂商与设备类型,回填设备档案。
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 特征规则(按优先级):正则 → (厂商, 设备类型)
_VERSION_SIGNATURES: list[tuple[str, tuple[str, str]]] = [
    (r"USG\s?\d{3,4}", ("huawei", "usg_firewall")),
    (r"HUAWEI|Huawei\s+S\d|VRP\s*\(R\)\s*software", ("huawei", "vrp_switch")),
    (r"S7506|S75\d\d", ("h3c", "s7506e")),
    (r"SecPath", ("h3c", "secpath_firewall")),
    (r"Comware|H3C|Hangzhou\s+H3C", ("h3c", "comware_switch")),
    (r"Ruijie|RGOS", ("ruijie", "rgos_switch")),
    (r"ZXR10|ZTE\s+ZXR10", ("zte", "zxr10_switch")),
    (r"MyPower|Maipu", ("maipu", "mypower_switch")),
]

# 型号提取正则(按厂商)
_MODEL_PATTERNS = [
    (r"HUAWEI\s+(\S+?)(?:\s+uptime|\s*\()", "huawei"),
    (r"H3C\s+(\S+?)(?:\s+uptime|\s*\()", "h3c"),
    (r"ZXR10\s+(\S+)\s+uptime", "zte"),
    (r"ZXR10\s+(\S+)\s+Series", "zte"),
    (r"MyPower\s+(\S+)\s+uptime", "maipu"),
    (r"MyPower\s+(\S+)\s+Software", "maipu"),
    (r"(S\d{4}[A-Za-z0-9\-]*)", None),
    (r"(USG\s?\d{3,4})", None),
]

# 软件版本提取
_VERSION_PATTERNS = [
    r"Version\s+([\d()A-Za-z.\-]+)",
    r"V\d{3}R\d{3}C\d{2,3}(?:SPC\d{3})?",
]


def detect_from_version(output: str) -> dict[str, Any] | None:
    """从 version 回显识别厂商/设备类型/型号/版本。

    返回 {vendor, device_type, model, software_version} 或 None(无法识别)。
    """
    if not output or len(output.strip()) < 20:
        return None
    vendor = device_type = None
    for pattern, (v, dt) in _VERSION_SIGNATURES:
        if re.search(pattern, output, re.IGNORECASE):
            vendor, device_type = v, dt
            break
    if vendor is None:
        return None

    model = ""
    for pattern, expect in _MODEL_PATTERNS:
        m = re.search(pattern, output, re.IGNORECASE)
        if m and (expect is None or expect == vendor):
            model = m.group(1).strip("() ,")
            break

    version = ""
    for pattern in _VERSION_PATTERNS:
        m = re.search(pattern, output, re.IGNORECASE)
        if m:
            version = m.group(1) if m.lastindex else m.group(0)
            version = version.strip("() ,")
            break

    return {"vendor": vendor, "device_type": device_type,
            "model": model, "software_version": version}


def probe_device(host: str, username: str, password: str,
                 login_method: str = "ssh", port: int | None = None,
                 timeout: int = 15) -> dict[str, Any]:
    """登录设备取 version 回显并识别(SSH 失败自动降级 Telnet)。

    返回 {ok, method, result(识别结果或 None), raw(回显节选), error}。
    """
    from netmiko import ConnectHandler

    attempts: list[tuple[str, str, int]] = []
    if login_method == "telnet":
        attempts.append(("telnet", "generic_termserver", port or 23))
    else:
        attempts.append(("ssh", "generic", port or 22))
        if not port:  # 未显式指定端口才尝试降级
            attempts.append(("telnet", "generic_termserver", 23))

    last_error = ""
    for method, nm_type, use_port in attempts:
        conn = None
        try:
            conn = ConnectHandler(
                device_type=nm_type, host=host, username=username,
                password=password, port=use_port,
                conn_timeout=timeout, banner_timeout=timeout,
                auth_timeout=timeout,
            )
            raw = conn.send_command("display version", read_timeout=timeout)
            if not raw or len(raw.strip()) < 20:
                raw = conn.send_command("show version", read_timeout=timeout)
            result = detect_from_version(raw or "")
            return {"ok": result is not None, "method": method,
                    "result": result,
                    "raw": (raw or "").strip()[:400], "error": ""}
        except Exception as e:  # noqa: BLE001 - 逐通道尝试,最后汇总
            last_error = f"{method}: {e}"
            logger.info("自动识别 %s 通道失败: %s", host, last_error)
        finally:
            if conn is not None:
                try:
                    conn.disconnect()
                except Exception:  # noqa: BLE001 - 清理容错
                    pass
    return {"ok": False, "method": "", "result": None, "raw": "",
            "error": last_error}
