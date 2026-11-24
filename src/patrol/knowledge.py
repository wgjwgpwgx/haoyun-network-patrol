"""设备知识库(经验沉淀)

- 巡检自动沉淀:每次巡检把该设备全部命令的原始回显存为一份快照
  (output/knowledge/{客户}/{设备}/{YYYYMMDD_HHMMSS}.yaml)
- 历史资料导入:旧巡检文本/Word 导入,启发式切分"命令-回显"对
- 价值:多客户多型号的真实回显语料 → 解析器 Copilot 离线适配、
  设备差异对比、故障复盘的经验库
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from patrol.utils.redact import redact

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path("output/knowledge")

# 命令行启发式:行首为已知只读命令动词,或显式"命令:"标记
_CMD_LINE = re.compile(
    r"^\s*(?:命令\s*[:：]\s*)?"
    r"((?:display|show|dis\b|sh\b|dir|compare)\s+[^\s].{0,100})\s*$",
    re.IGNORECASE)


def _safe(name: str) -> str:
    from patrol.utils.filename import safe_component
    return safe_component(name or "未归类")


def save_snapshot(device_meta: dict, items: list[dict],
                  source: str = "patrol", error: str | None = None) -> Path:
    """沉淀一份设备全量快照。items: [{name, command, raw_output}]"""
    import yaml

    customer = _safe(device_meta.get("customer"))
    dev = _safe(device_meta.get("name"))
    d = KNOWLEDGE_DIR / customer / dev
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,           # patrol=巡检自动 / import=资料导入
        "device": {
            "name": device_meta.get("name", ""),
            "host": device_meta.get("host", ""),
            "vendor": device_meta.get("vendor", ""),
            "device_type": device_meta.get("device_type", ""),
            "model": device_meta.get("model", ""),
            "software_version": device_meta.get("software_version", ""),
        },
        "error": error,
        "items": [
            {"name": it.get("name", ""), "command": it.get("command", ""),
             "raw_output": redact(it.get("raw_output", ""))}  # 落盘即脱敏
            for it in items if (it.get("raw_output") or "").strip()
        ],
    }
    path = d / f"{ts}_{source}.yaml"
    path.write_text(
        yaml.safe_dump(record, allow_unicode=True, default_flow_style=False,
                       width=4096),
        encoding="utf-8")
    logger.info("知识库快照已保存: %s(%d 条回显)", path, len(record["items"]))
    return path


# ── 浏览 ─────────────────────────────────────────────────────


def list_customers() -> list[str]:
    if not KNOWLEDGE_DIR.exists():
        return []
    return sorted(p.name for p in KNOWLEDGE_DIR.iterdir() if p.is_dir())


def list_devices(customer: str) -> list[str]:
    d = KNOWLEDGE_DIR / _safe(customer)
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def list_snapshots(customer: str, device: str) -> list[dict]:
    d = KNOWLEDGE_DIR / _safe(customer) / _safe(device)
    if not d.exists():
        return []
    import yaml

    out = []
    for p in sorted(d.glob("*.yaml"), reverse=True):
        try:
            rec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            out.append({
                "file": p.name,
                "captured_at": rec.get("captured_at", ""),
                "source": rec.get("source", ""),
                "model": rec.get("device", {}).get("model", ""),
                "items": len(rec.get("items", [])),
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def load_snapshot(customer: str, device: str, filename: str) -> dict | None:
    import yaml

    if ".." in filename or "/" in filename or "\\" in filename:
        return None
    p = KNOWLEDGE_DIR / _safe(customer) / _safe(device) / filename
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def delete_snapshot(customer: str, device: str, filename: str) -> bool:
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    p = KNOWLEDGE_DIR / _safe(customer) / _safe(device) / filename
    if p.exists():
        p.unlink()
        return True
    return False


# ── 历史资料导入 ─────────────────────────────────────────────


def split_text_to_items(text: str) -> list[dict]:
    """把旧巡检文本切分为 [{name, command, raw_output}]。

    启发式:遇到"命令行"(display/show/dir/compare 开头 或 '命令:' 标记)
    开新块;否则并入当前块回显。无任何命令行时整文作为一条。
    """
    items: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = _CMD_LINE.match(line)
        if m:
            if current:
                items.append(current)
            cmd = m.group(1).strip()
            current = {"name": _guess_name(cmd), "command": cmd,
                       "raw_output": ""}
        elif current is not None:
            current["raw_output"] += line + "\n"
        # 命令行之前的文字(报告说明等)忽略
    if current:
        items.append(current)
    if not items and text.strip():
        items.append({"name": "全文", "command": "(导入原文)",
                      "raw_output": text})
    return items


_NAME_HINTS = [
    ("version", "device_info"), ("cpu", "cpu_usage"),
    ("memory", "memory_usage"), ("temperature", "temperature"),
    ("environment", "temperature"), ("transceiver", "transceiver"),
    ("interface brief", "interface_status"), ("int bri", "interface_status"),
    ("ospf peer", "ospf_neighbor"), ("lldp", "lldp_neighbor"),
    ("fan", "fan_status"), ("power", "power_status"),
    ("current-configuration", "config_cur"), ("running-config", "config_cur"),
    ("arp", "arp_count"), ("ntp", "ntp_status"), ("logbuffer", "logbuffer"),
    ("log", "logbuffer"), ("dir", "storage"),
]


def _guess_name(cmd: str) -> str:
    low = cmd.lower()
    for hint, name in _NAME_HINTS:
        if hint in low:
            return name
    return "imported"


def import_text(text: str, customer: str, device: str,
                host: str = "", vendor: str = "",
                model: str = "") -> Path:
    """导入一段历史巡检文本为知识库快照。"""
    items = split_text_to_items(text)
    # 尝试从文本提取设备信息增强
    if not model:
        m = re.search(
            r"(?:型号|Model)\s*[:：]\s*(\S+)", text) or re.search(
            r"HUAWEI\s+(\S+)|H3C\s+(\S+)|ZXR10\s+(\S+)|MyPower\s+(\S+)", text, re.IGNORECASE)
        if m:
            model = next(g for g in m.groups() if g)
    return save_snapshot(
        {"customer": customer, "name": device, "host": host,
         "vendor": vendor, "model": model},
        items, source="import")


def import_docx(path: Path, customer: str, device: str = "",
                host: str = "") -> Path:
    """导入 Word 巡检报告(全文提取后按文本导入;device 缺省用文件名)。"""
    import docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for tb in d.tables:  # 表格内容也纳入(命令-回显常在表格里)
        for row in tb.rows:
            parts.append("\n".join(c.text for c in row.cells))
    text = "\n".join(parts)
    dev = device or path.stem
    return import_text(text, customer, dev, host=host)


# ── 内置种子语料(②)+ 历史报告导入(①) ───────────────────────


def seed_builtin(force: bool = False) -> int:
    """载入内置样例语料(五厂商)。幂等:已存在同 source=builtin 的
    固定名快照则跳过(force=True 覆盖)。返回导入设备数。"""
    from patrol.knowledge_seed import SEED_DEVICES

    count = 0
    for dev in SEED_DEVICES:
        customer = "内置样例"
        d = KNOWLEDGE_DIR / _safe(customer) / _safe(dev["name"])
        existing = list(d.glob("seed_builtin.yaml")) if d.exists() else []
        if existing and not force:
            continue
        items = [{"name": _guess_name(cmd), "command": cmd,
                  "raw_output": text}
                 for cmd, text in dev["responses"].items()]
        import yaml as _yaml
        record = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "source": "builtin",
            "device": {"name": dev["name"], "host": "(内置样例)",
                       "vendor": dev["vendor"],
                       "device_type": dev["device_type"],
                       "model": dev["model"],
                       "software_version": dev["software_version"]},
            "error": None, "items": items,
        }
        d.mkdir(parents=True, exist_ok=True)
        (d / "seed_builtin.yaml").write_text(
            _yaml.safe_dump(record, allow_unicode=True,
                            default_flow_style=False, width=4096),
            encoding="utf-8")
        count += 1
    return count


def import_report_json(path: Path) -> tuple[str, int]:
    """导入本项目历史巡检报告 JSON(output/*.json)为知识库快照。

    返回 (设备名, 回显条数);结构不符抛 ValueError。
    """
    import json
    import yaml

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    devices = data.get("devices", [])
    if not devices:
        raise ValueError(f"{path.name} 中无设备数据")
    dev = devices[0]
    items = [{"name": it.get("name", ""), "command": it.get("command", ""),
              "raw_output": it.get("raw_output", "")}
             for it in dev.get("check_items", [])
             if (it.get("raw_output") or "").strip()]
    customer = dev.get("customer") or "未归类"
    meta = {"customer": customer, "name": dev.get("name", path.stem),
            "host": dev.get("host", ""), "vendor": dev.get("vendor", ""),
            "device_type": dev.get("device_type", ""),
            "model": dev.get("model", ""),
            "software_version": dev.get("software_version", "")}
    d = KNOWLEDGE_DIR / _safe(customer) / _safe(meta["name"])
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "captured_at": data.get("generated_at",
                                datetime.now().isoformat(timespec="seconds")),
        "source": "import",
        "device": meta, "error": None, "items": items,
    }
    (d / f"{path.stem}.yaml").write_text(
        yaml.safe_dump(record, allow_unicode=True,
                       default_flow_style=False, width=4096),
        encoding="utf-8")
    return meta["name"], len(items)


def import_all_reports(output_dir: str = "output") -> dict:
    """一键导入本机全部巡检报告 JSON。返回 {imported, skipped, errors}。"""
    out = Path(output_dir)
    imported = skipped = 0
    errors: list[str] = []
    for p in sorted(out.glob("*.json")):
        try:
            import_report_json(p)
            imported += 1
        except ValueError:
            skipped += 1  # 非巡检报告结构(配置/AI 等)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p.name}: {e}")
    return {"imported": imported, "skipped": skipped, "errors": errors}


def delete_device(customer: str, device: str) -> int:
    """删除某设备的全部快照,返回删除数。"""
    import shutil

    d = KNOWLEDGE_DIR / _safe(customer) / _safe(device)
    if not d.exists():
        return 0
    count = len(list(d.glob("*.yaml")))
    shutil.rmtree(d)
    # 清理空客户目录
    parent = d.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
    return count


def delete_customer(customer: str) -> int:
    """删除某客户的全部设备与快照,返回删除快照总数。"""
    import shutil

    d = KNOWLEDGE_DIR / _safe(customer)
    if not d.exists():
        return 0
    count = sum(1 for _ in d.rglob("*.yaml"))
    shutil.rmtree(d)
    return count


def device_snapshot_count(customer: str, device: str) -> int:
    """某设备当前快照数(替换前查询用)。"""
    d = KNOWLEDGE_DIR / _safe(customer) / _safe(device)
    if not d.exists():
        return 0
    return len(list(d.glob("*.yaml")))


def search(keyword: str, limit: int = 50) -> list[dict]:
    """全文搜索知识库:关键词在回显/命令/设备名中匹配。

    返回 [{customer, device, file, check_name, command, snippet}]。
    """
    import yaml

    if not keyword.strip() or not KNOWLEDGE_DIR.exists():
        return []
    results: list[dict] = []
    kw = keyword.lower()
    for cust_dir in sorted(KNOWLEDGE_DIR.iterdir()):
        if not cust_dir.is_dir():
            continue
        for dev_dir in sorted(cust_dir.iterdir()):
            if not dev_dir.is_dir():
                continue
            for f in dev_dir.glob("*.yaml"):
                try:
                    rec = yaml.safe_load(f.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                for it in rec.get("items", []):
                    text = it.get("raw_output", "") + " " + it.get("command", "")
                    if kw in text.lower() or kw in dev_dir.name.lower():
                        # 截取匹配位置附近的片段
                        raw = it.get("raw_output", "")
                        pos = raw.lower().find(kw)
                        snippet = (raw[max(0, pos - 30):pos + 60]
                                   .replace("\n", " ")
                                   if pos >= 0 else raw[:60])
                        results.append({
                            "customer": cust_dir.name,
                            "device": dev_dir.name,
                            "file": f.name,
                            "check_name": it.get("name", ""),
                            "command": it.get("command", ""),
                            "snippet": snippet,
                        })
                        if len(results) >= limit:
                            return results
    return results


def export_all(output_path: Path | None = None) -> Path:
    """一键交接:导出设备+知识库+解析规则+报告样式为 zip。

    接手人解压后放入对应目录即可恢复全部数据。
    """
    import shutil
    import zipfile

    if output_path is None:
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("output") / f"巡检助手交接包_{ts}.zip"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. 知识库
        if KNOWLEDGE_DIR.exists():
            for f in KNOWLEDGE_DIR.rglob("*.yaml"):
                zf.write(f, f"knowledge/{f.relative_to(KNOWLEDGE_DIR)}")
        # 2. 解析器 Copilot 规则
        copilot_dir = Path("config/parser_copilot")
        if copilot_dir.exists():
            for f in copilot_dir.glob("*.yaml"):
                zf.write(f, f"parser_copilot/{f.name}")
        # 3. 报告样式
        style = Path("config/report_style.yaml")
        if style.exists():
            zf.write(style, "config/report_style.yaml")
        # 4. 规则文件
        rules_dir = Path("config/rules")
        if rules_dir.exists():
            for f in rules_dir.glob("*.yaml"):
                zf.write(f, f"config/rules/{f.name}")

    return output_path


# 交接包内的顶层前缀 → 本地根目录
_HANDOFF_ROOTS: dict[str, Path] = {
    "knowledge": KNOWLEDGE_DIR,
    "parser_copilot": Path("config/parser_copilot"),
    "config/rules": Path("config/rules"),
}
_HANDOFF_MAX_BYTES = 20 * 1024 * 1024  # 单个成员上限,防解压炸弹


def _safe_member(root: Path, rel: str) -> Path | None:
    """交接包成员名 → 本地路径;越界(zip slip)、目录或非 yaml 文件一律拒绝。"""
    try:
        target = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if root.resolve() not in target.parents or target.suffix.lower() != ".yaml":
        return None
    return target


def snapshot_paths(customer: str, device: str) -> list[Path]:
    """该设备现有快照文件。"""
    d = KNOWLEDGE_DIR / _safe(customer) / _safe(device)
    return sorted(d.glob("*.yaml")) if d.is_dir() else []


def snapshot_contents(customer: str, device: str) -> dict[Path, bytes]:
    """该设备现有快照 {路径: 内容},供"替换导入"在导入前留底。"""
    return {p: p.read_bytes() for p in snapshot_paths(customer, device)}


def finish_replace(customer: str, device: str,
                   before: dict[Path, bytes]) -> bool:
    """"替换导入"的收尾:确认确有新资料后,清掉被取代的旧快照。

    返回是否确有新资料——没有则不动任何文件(调用方据此报错,旧资料保留)。
    快照文件名只精确到秒,新资料可能与旧快照同名:同名文件内容已变即说明
    它装的是新资料,必须保留,只删除内容仍是旧内容的那些。
    """
    after = {p: p.read_bytes() for p in snapshot_paths(customer, device)}
    fresh = any(after.get(p) != data for p, data in before.items()) or \
        any(p not in before for p in after)
    if not fresh:
        return False
    for path, data in before.items():
        if after.get(path) == data:
            path.unlink(missing_ok=True)
    return True


def import_all(zip_path: Path) -> dict:
    """导入交接包:解压到对应目录。

    交接包是人与人之间交换的文件,成员名不可信:逐个校验目标必须落在对应
    根目录内且为 yaml,否则拒绝(否则成员名写成 ../../ 即可覆盖任意文件)。
    """
    import zipfile

    buckets = {"knowledge": "knowledge", "parser_copilot": "copilot",
               "config/rules": "rules"}
    counts = {"knowledge": 0, "rules": 0, "copilot": 0, "style": 0, "rejected": 0}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            target: Path | None
            bucket: str
            if name == "config/report_style.yaml":
                target, bucket = Path("config/report_style.yaml"), "style"
            else:
                key = next((k for k in _HANDOFF_ROOTS
                            if name.startswith(k + "/")), None)
                target = (_safe_member(_HANDOFF_ROOTS[key], name[len(key) + 1:])
                          if key is not None else None)
                bucket = buckets.get(key or "", "")
            if target is None or info.file_size > _HANDOFF_MAX_BYTES:
                logger.warning("交接包成员被拒绝: %s", name)
                counts["rejected"] += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            counts[bucket] += 1
    return counts
