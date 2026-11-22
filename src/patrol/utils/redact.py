"""敏感信息脱敏工具"""
from __future__ import annotations

import re

# 需要脱敏的模式：密码、密钥、SNMP Community
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # password lines in config: "password 123456" or "set password 123456"
    (re.compile(r"(password\s+)(\S+)", re.IGNORECASE), r"\1******"),
    # secret lines: "secret 123456"
    (re.compile(r"(secret\s+)(\S+)", re.IGNORECASE), r"\1******"),
    # snmp community: "snmp-agent community read public"
    (re.compile(r"(snmp-agent\s+community\s+\S+\s+)(\S+)", re.IGNORECASE), r"\1******"),
    # authorization key: "authorization key 123456"
    (re.compile(r"(authorization\s+key\s+)(\S+)", re.IGNORECASE), r"\1******"),
    # super password: "super password simple 123456"
    (re.compile(r"(super\s+password\s+\S+\s+)(\S+)", re.IGNORECASE), r"\1******"),
]


def redact(text: str) -> str:
    """对文本中的敏感信息进行脱敏处理。"""
    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result
