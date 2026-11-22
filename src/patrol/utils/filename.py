"""文件名安全工具 - 用户可控值(设备名/host)拼入文件路径前的消毒"""
from __future__ import annotations

import re

# Windows/Linux 文件名非法字符与路径分隔符
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_component(value: str, max_len: int = 50, fallback: str = "device") -> str:
    """把任意字符串消毒为可安全拼入文件名的组件。

    去除路径分隔符/非法字符/..,空白转下划线,超长截断,空值回退。
    """
    cleaned = _UNSAFE_CHARS.sub("", str(value))
    cleaned = cleaned.replace("..", "").strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned[:max_len] or fallback
