"""敏感信息脱敏工具

逐行处理:行内出现敏感关键字(password / secret / community / cipher / key 等)
时,跳过紧随其后的编码方式词(simple / cipher / read 等),把真正的值连同该行
余下内容一并遮蔽。

早期实现只遮"关键字后的第一个词",对 `local-user admin password simple 明文`
这类最常见的写法遮住的是 simple,明文原样留在报告里;SNMP 团体字、预共享密钥、
USM 用户等写法则完全没有匹配。
"""
from __future__ import annotations

import re

# 行内出现即视为含敏感信息(不区分大小写)。password-control / password-recover
# 是纯策略开关、没有值,排除在外。
_SECRET_KEYWORD = re.compile(
    r"\b(?:snmp(?:-server)?\s+user"
    r"|password(?!-(?:control|recover\w*)\b)"
    r"|passwd|secret|community|cipher|usm-user|authkey|privkey"
    r"|key[\w-]*)",
    re.IGNORECASE,
)

# 关键字与真正的值之间的编码方式/读写属性词
_MODIFIERS = re.compile(
    r"\s+(?:read|write|ro|rw|simple|cipher|hash|plain|md5"
    r"|sha[\w-]*|des[\w-]*|aes[\w-]*|irreversible[\w-]*|reversible[\w-]*)\b",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """对文本中的敏感信息进行脱敏处理(幂等,可重复调用)。"""
    if not text:
        return text
    lines = []
    for line in text.splitlines(keepends=True):
        hit = _SECRET_KEYWORD.search(line)
        if hit:
            pos = hit.end()
            mod = _MODIFIERS.match(line, pos)
            while mod:
                pos = mod.end()
                mod = _MODIFIERS.match(line, pos)
            body = line[pos:]
            value = body.rstrip("\r\n")
            if value.strip():  # 关键字后没有值(独立成行的 password 等)保持原样
                line = line[:pos] + "******" + body[len(value):]
        lines.append(line)
    return "".join(lines)
