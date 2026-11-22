"""解析器 Copilot(P2):UNKNOWN 项 → AI 生成声明式解析规则 → 试跑 → 入库

- 声明式规则:每个字段一条正则+类型(纯数据,无代码执行,安全)
- 规则库:config/parser_copilot/{vendor}_{device_type}.yaml
- 生效:run_inspection 在驱动解析失败时自动回退到已入库规则
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RULES_DIR = Path("config/parser_copilot")

# 常用检查项的标准字段(规则引擎 R 系列 metric 依赖;AI 提示词携带)
CANONICAL_FIELDS: dict[str, list[str]] = {
    "cpu_usage": ["usage_percent"],
    "memory_usage": ["usage_percent", "total_bytes", "used_bytes"],
    "temperature": ["value", "status", "abnormal_count"],
    "storage": ["used_percent", "total_kb", "free_kb"],
    "fan_status": ["total", "abnormal_count"],
    "power_status": ["total", "abnormal_count"],
    "ospf_neighbor": ["total", "full_count", "abnormal_count"],
    "arp_count": ["arp_count"],
    "lldp_neighbor": ["neighbor_count"],
}


# ── 声明式解析器 ─────────────────────────────────────────────


def parse_with_rules(raw: str, fields: dict[str, dict]) -> dict[str, Any]:
    """按 {字段: {regex, type}} 提取;匹配失败字段不出现。"""
    out: dict[str, Any] = {}
    for name, spec in fields.items():
        try:
            m = re.search(spec["regex"], raw, re.IGNORECASE | re.MULTILINE)
        except re.error:
            continue
        if not m:
            continue
        value: Any = m.group(1) if m.groups() else m.group(0)
        typ = spec.get("type", "str")
        try:
            if typ == "float":
                value = float(value)
            elif typ == "int":
                value = int(float(value))
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            continue
        out[name] = value
    return out


# ── 规则库 ───────────────────────────────────────────────────


def _rules_path(vendor: str, device_type: str) -> Path:
    from patrol.utils.filename import safe_component

    return RULES_DIR / f"{safe_component(vendor)}_{safe_component(device_type)}.yaml"


def load_rule(vendor: str, device_type: str, check_name: str) -> dict | None:
    """取已入库的某检查项规则。"""
    import yaml

    p = _rules_path(vendor, device_type)
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    entry = (data.get("parsers") or {}).get(check_name)
    if not entry or not entry.get("fields"):
        return None
    return entry


def save_rule(vendor: str, device_type: str, check_name: str,
              fields: dict, note: str = "") -> Path:
    """确认入库(同 check_name 覆盖,保留其他)。"""
    import yaml

    p = _rules_path(vendor, device_type)
    data: dict[str, Any] = {}
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            data = {}
    parsers = data.setdefault("parsers", {})
    parsers[check_name] = {
        "note": note or "AI 生成,经人工确认",
        "fields": fields,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8")
    return p


def apply_saved_rule(vendor: str, device_type: str, check_name: str,
                     raw: str, category: str = "", command: str = ""):
    """已入库规则试解析;成功返回 ParsedResult,否则 None。"""
    from patrol.drivers.base import ParsedResult

    entry = load_rule(vendor, device_type, check_name)
    if not entry:
        return None
    parsed = parse_with_rules(raw, entry["fields"])
    if not parsed:
        return None
    return ParsedResult(name=check_name, category=category or "AI 解析",
                        command=command, raw_output=raw,
                        parsed=parsed, success=True)


# ── AI 生成 ──────────────────────────────────────────────────


def build_prompt(check_name: str, raw_output: str, extra_hint: str = "") -> str:
    fields = CANONICAL_FIELDS.get(check_name, [])
    return (
        "你是网络设备命令回显解析专家。请阅读下面的设备命令原始回显,"
        "为一个名为「%s」的检查项编写声明式解析规则。\n\n"
        "要求:\n"
        "1. 仅输出 JSON,不要任何解释文字,格式:\n"
        '{"fields": {"字段名": {"regex": "正则(必须含一个捕获组)", '
        '"type": "int|float|str"}, ...}}\n'
        "2. 正则使用 Python re 语法,需能对下方回显匹配出数值/状态;\n"
        "3. 优先产出这些标准字段:%s%s\n"
        "4. 若可判定异常,补充 abnormal_count(int)字段。\n\n"
        "=== 原始回显 ===\n%s\n=== 回显结束 ==="
        % (check_name,
           ", ".join(fields) if fields else "(此检查项无标准字段,按回显合理命名)",
           f"\n5. 附加要求:{extra_hint}" if extra_hint else "",
           raw_output[:3000]))


def parse_ai_rules(reply: str) -> dict[str, dict]:
    """从 AI 回复提取规则 dict;解析失败抛 ValueError。"""
    text = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI 返回非合法 JSON: {e}") from e
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict) or not fields:
        raise ValueError("AI 返回缺少 fields")
    cleaned = {}
    for name, spec in fields.items():
        if not isinstance(spec, dict) or "regex" not in spec:
            continue
        # 编译校验
        try:
            re.compile(spec["regex"], re.IGNORECASE)
        except re.error:
            continue
        cleaned[str(name)] = {"regex": spec["regex"],
                              "type": spec.get("type", "str")}
    if not cleaned:
        raise ValueError("AI 返回的规则全部无效(正则编译失败)")
    return cleaned


def generate_with_ai(check_name: str, raw_output: str) -> dict:
    """AI 生成 + 对样本当场试跑。返回 {ok, fields, sample, error}。"""
    from patrol.ai.client import LLMClient
    from patrol.ai.config import load_ai_config

    cfg = load_ai_config()
    if not cfg.enabled:
        return {"ok": False, "error":
                "AI 分析未启用:请先在「系统设置 → AI 大模型分析」配置"}
    try:
        reply = LLMClient(cfg).chat(
            [{"role": "user", "content": build_prompt(check_name, raw_output)}],
            json_mode=True)
        fields = parse_ai_rules(reply)
    except Exception as e:  # noqa: BLE001 - 用户可见
        return {"ok": False, "error": str(e)}
    sample = parse_with_rules(raw_output, fields)
    return {"ok": True, "fields": fields, "sample": sample}
