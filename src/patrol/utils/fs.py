"""文件原子写入(问题 004:YAML/JSON 直接覆写,进程中途崩溃会损坏配置)

统一走"同目录临时文件 + os.replace"模式:替换在同一卷上是原子操作,
读者永远看到完整旧文件或完整新文件,不会出现写一半的截断文件。
"""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """原子写入文本文件:先写 <文件名>.tmp,成功后 os.replace 到目标。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)
