"""只读命令白名单校验器(销号清单 #7 / U-5)

产品级安全承诺:巡检仅执行只读命令。SSH 下发前双重校验——
1) 危险动词黑名单(save/undo/delete/reboot/system-view… 命中即拒);
2) 只读前缀白名单(display/show/dir/compare… 不匹配即拒)。
双闸确保拼接到命令里的写操作同样被拦截(如 "display cpu; save")。
"""
from __future__ import annotations

import re

# 只读命令前缀白义词(dis/sh 为厂商官方简写)
_READONLY_PREFIX = re.compile(
    r"^\s*(display|show|dir|compare|screen-length|terminal|"
    r"disp\b|dis\b|sh\b|get\b|cat\b)",
    re.IGNORECASE,
)

# 危险动词黑名单:动词后必须紧跟空白/分号/行尾(独立命令形态),
# 避免误伤连字符复合只读命令(如 display reboot-info / display device)
_DANGEROUS = re.compile(
    r"\b(save|undo|delete|reset|reboot|reload|shutdown|restore|format|"
    r"boot-loader|bootrom|rollback|copy|move|rename|mkdir|rmdir|clear|"
    r"system-view|sysname|configure|erase|write|"
    r"super\s+password|set\s+password|local-user|"
    r"shell|tftp|ftp|put|upload)(?=[\s;]|$)",
    re.IGNORECASE,
)


class ReadOnlyViolation(Exception):
    """命令未通过只读校验,拒绝下发。"""


def assert_readonly(command: str) -> None:
    """校验一条命令是否只读;违规则抛 ReadOnlyViolation。"""
    cmd = (command or "").strip()
    if not cmd:
        raise ReadOnlyViolation("拒绝下发空命令")
    if _DANGEROUS.search(cmd):
        raise ReadOnlyViolation(f"拒绝下发疑似写操作命令: {cmd[:80]}")
    if not _READONLY_PREFIX.match(cmd):
        raise ReadOnlyViolation(f"拒绝下发非白名单命令: {cmd[:80]}")
