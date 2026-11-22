"""配置快照留存与对比(销号清单 #9)

巡检时自动保存 running-configuration 快照到 output/configs/{设备}/,
Word 报告"配置变更对比"章节用最近两期快照做 unified diff。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path("output/configs")


def save_config_snapshot(device_name: str, config_text: str) -> Path | None:
    """保存一期配置快照,返回文件路径(空配置不保存)。"""
    from patrol.utils.filename import safe_component

    if not config_text or not config_text.strip():
        return None
    d = CONFIG_DIR / safe_component(device_name)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = d / f"{ts}.txt"
    path.write_text(config_text, encoding="utf-8")
    return path


def list_snapshots(device_name: str) -> list[Path]:
    """某设备的全部快照(按时间正序)。"""
    from patrol.utils.filename import safe_component

    d = CONFIG_DIR / safe_component(device_name)
    if not d.exists():
        return []
    return sorted(d.glob("*.txt"))


def previous_snapshot(device_name: str,
                      current_text: str) -> tuple[str, str] | None:
    """取与本期文本不同的最近一期快照(跳过完全相同的重复期)。

    返回 (快照文本, 快照时间戳) 或 None(无历史或全部相同)。
    """
    snaps = list_snapshots(device_name)
    for path in reversed(snaps):
        text = path.read_text(encoding="utf-8")
        if text.strip() != (current_text or "").strip():
            return text, path.stem
    return None
