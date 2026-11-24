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


def unique_filename(directory, filename: str) -> str:
    """同名报告已存在时追加序号。

    报告文件名里的时间戳只到秒,同一秒内完成的两个任务会互相覆盖。
    HTML 与伴生的 .json 任一已存在即视为重名。
    """
    from pathlib import Path

    # 必须在最后一个点切分:主机地址本身带点(patrol_192.0.2.1_xxx.html),
    # 按第一个点切会把重名文件拼成 patrol_192_2.0.2.1_xxx.html
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate, n = filename, 2
    base = Path(directory) / candidate
    while base.exists() or base.with_suffix(".json").exists():
        candidate = f"{stem}_{n}{suffix}"
        base = Path(directory) / candidate
        n += 1
    return candidate
