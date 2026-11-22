"""AI 大模型巡检结果分析器

将结构化巡检数据交给大模型,产出运维专家视角的分析汇总:
  - executive_summary  总体评估
  - health_score       健康评分(0-100)
  - overall_risk       总体风险等级(low/medium/high/critical)
  - device_assessments 逐台融合评估(结合设备原始输出)
  - key_findings       关键发现(逐条含影响与处置建议)
  - recommendations    处置建议(按优先级)
  - maintenance_suggestions  中长期优化建议

LLM 不可用或返回异常时抛出 LLMError / AINotConfigured,由调用方决定降级策略
(巡检流程不因 AI 失败而失败)。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from patrol.ai.client import LLMClient, LLMError
from patrol.ai.config import AIConfig, load_ai_config
from patrol.models import PatrolReport
from patrol.utils.redact import redact

logger = logging.getLogger(__name__)

_RISK_LEVELS = ("low", "medium", "high", "critical")
_SEVERITY_CN = {"low": "低", "medium": "中", "high": "高", "critical": "严重"}
# 控制 prompt 体积:单条原始输出截断长度 / 最多携带原始输出的检查项数
# (异常项优先占额度,余量补给通过项——模型需"结合设备输出"整体融合研判)
_SNIPPET_MAX = 400
_SNIPPET_ITEMS = 60

_SYSTEM_PROMPT = """你是一名资深的网络运维专家(网络设备巡检分析方向),拥有 15 年以上华为/H3C/锐捷/思科等厂商交换机、路由器、防火墙的运维经验,熟悉常见配置隐患、容量风险与最佳实践。

现在给你一份网络设备巡检的结构化检查结果,每个检查项附有设备原始命令输出(output_snippet)。请你把巡检结论与原始输出相互印证,以专家视角完成分析汇总,输出严格的 JSON(不要输出任何 JSON 以外的文字、注释或 Markdown 代码块),结构如下:

{
  "executive_summary": "总体评估,2-4 句话,概括整体健康状况、突出风险与趋势",
  "health_score": 0-100 的整数健康评分(100 为最佳),
  "overall_risk": "low | medium | high | critical 之一",
  "device_assessments": [
    {
      "device": "设备名",
      "assessment": "结合该设备检查结果与原始命令输出的综合评估,2-3 句,可引用关键数值/日志片段"
    }
  ],
  "key_findings": [
    {
      "device": "设备名",
      "issue": "问题简述",
      "severity": "high | medium | low 之一",
      "impact": "对业务/网络的影响",
      "recommendation": "具体处置建议,给出命令或操作要点"
    }
  ],
  "recommendations": ["按优先级排序的处置建议,每条一句话说明做什么、为什么"],
  "maintenance_suggestions": ["中长期运维优化建议,如备份策略、容量规划、版本升级"]
}

分析要求:
1. 只依据给出的巡检数据与原始输出下结论,不要臆造数据中不存在的设备或问题;
2. 结合设备原始命令输出(output_snippet)做证据研判:从实际数值、日志、配置片段中提炼风险与趋势,不要只复述通过/失败统计;
3. 结合你的专家经验解释风险成因、评估影响面、给出可执行的处置建议(可包含具体厂商命令);
4. key_findings 覆盖全部 FAIL 项及有价值的 UNKNOWN 项,severity 按影响排序;
5. device_assessments 逐台覆盖全部设备,形成"设备输出 + AI 分析"融合的最终结论;
6. 若所有检查全部通过,health_score 给 90 以上,key_findings 可为空数组,并在 maintenance_suggestions 给出预防性建议;
7. 全部内容使用简体中文。"""


class AINotConfigured(Exception):
    """AI 分析未启用或未配置密钥。"""


def _digest(report: PatrolReport) -> dict:
    """把巡检报告压缩成 LLM 易读的紧凑结构(已脱敏、截断)。

    原始命令输出分两轮携带:异常项(FAIL/UNKNOWN)优先占额度,余量补给通过项
    ——模型既能定位故障证据,又能对设备整体状态做融合研判。
    """
    devices = []
    entries: list[tuple[dict, Any]] = []
    for dev in report.devices:
        checks = []
        for item in dev.check_items:
            entry: dict[str, Any] = {
                "name": item.name,
                "category": item.category,
                "status": item.status.value,
                "message": item.message,
            }
            if item.details.get("severity"):
                entry["severity"] = item.details["severity"]
            if item.details.get("suggestion"):
                entry["rule_suggestion"] = item.details["suggestion"]
            checks.append(entry)
            entries.append((entry, item))
        devices.append({
            "name": dev.asset.name,
            "host": dev.asset.host,
            "vendor": dev.asset.vendor,
            "model": dev.model,
            "software_version": dev.software_version,
            "uptime": dev.uptime,
            "summary": dev.summary,
            "error": dev.error,
            "checks": checks,
        })
    budget = _SNIPPET_ITEMS
    for abnormal_first in (True, False):
        for entry, item in entries:
            if budget <= 0:
                break
            is_abnormal = item.status.value != "PASS"
            if is_abnormal != abnormal_first or "output_snippet" in entry:
                continue
            snippet = redact(item.raw_output or "").strip()
            if snippet:
                entry["output_snippet"] = snippet[:_SNIPPET_MAX]
                budget -= 1
    return {
        "title": report.title,
        "generated_at": report.generated_at.isoformat(),
        "devices": devices,
    }


def _extract_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON 对象(容忍代码块围栏和前后缀文本)。"""
    text = text.strip()
    # 去掉 ```json ... ``` 围栏
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("LLM 回复中未找到 JSON 对象")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM 回复 JSON 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise LLMError("LLM 回复 JSON 不是对象")
    return data


def _as_str_list(value: Any) -> list[str]:
    """容忍 LLM 把字符串列表写成对象/字符串的情况。"""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, dict):
            # [{"text": "..."}] 之类的宽容处理
            for key in ("text", "content", "suggestion", "title", "description"):
                if isinstance(v.get(key), str) and v[key].strip():
                    out.append(v[key].strip())
                    break
    return out


def _fallback_health_score(report: PatrolReport) -> int:
    """LLM 未给出有效评分时,按通过率折算。"""
    items = [i for d in report.devices for i in d.check_items]
    if not items:
        return 100
    total = len(items)
    passed = sum(1 for i in items if i.status.value == "PASS")
    unknown = sum(1 for i in items if i.status.value == "UNKNOWN")
    failed = total - passed - unknown
    # FAIL 权重 3 倍于 UNKNOWN
    penalty = (failed * 3 + unknown) / total
    return max(0, min(100, round(100 - penalty * 35)))


def _fallback_risk(report: PatrolReport) -> str:
    critical = sum(
        1 for d in report.devices for i in d.check_items
        if i.status.value == "FAIL" and i.details.get("severity") == "critical"
    )
    failed = sum(d.fail_count for d in report.devices)
    if critical > 0:
        return "critical"
    if failed >= 5:
        return "high"
    if failed >= 1:
        return "medium"
    return "low"


def _normalize(parsed: dict, report: PatrolReport) -> dict:
    """校验并规范化 LLM 输出字段,缺失/非法的用兜底值。"""
    findings = []
    for f in parsed.get("key_findings") or []:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "medium")).lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        findings.append({
            "device": str(f.get("device", "")).strip() or "未知设备",
            "issue": str(f.get("issue", "")).strip() or "未描述问题",
            "severity": sev,
            "impact": str(f.get("impact", "")).strip(),
            "recommendation": str(f.get("recommendation", "")).strip(),
        })

    # 逐台融合评估(设备输出 + AI 分析 → 最终报告的一部分)
    assessments = []
    for a in parsed.get("device_assessments") or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("device", "")).strip()
        text = str(a.get("assessment", "")).strip()
        if name and text:
            assessments.append({"device": name, "assessment": text})

    try:
        score = int(parsed.get("health_score"))
    except (TypeError, ValueError):
        score = _fallback_health_score(report)
    score = max(0, min(100, score))

    risk = str(parsed.get("overall_risk", "")).lower().strip()
    if risk not in _RISK_LEVELS:
        risk = _fallback_risk(report)

    return {
        "executive_summary": str(parsed.get("executive_summary", "")).strip(),
        "health_score": score,
        "overall_risk": risk,
        "device_assessments": assessments,
        "key_findings": findings,
        "recommendations": _as_str_list(parsed.get("recommendations")),
        "maintenance_suggestions": _as_str_list(
            parsed.get("maintenance_suggestions")
        ),
    }


def analyze_report(
    report: PatrolReport, config: AIConfig | None = None
) -> dict:
    """对巡检报告执行 AI 分析,返回规范化的分析结论(含元数据)。

    Raises:
        AINotConfigured: 未启用或未配置密钥
        LLMError: 调用失败或输出无法解析
    """
    cfg = config or load_ai_config()
    if not cfg.ready:
        raise AINotConfigured("AI 分析未启用或未配置 API Key(config/ai.yaml)")

    digest = _digest(report)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请分析以下巡检数据并输出 JSON:\n"
                + json.dumps(digest, ensure_ascii=False)
            ),
        },
    ]

    logger.info("AI 分析开始: %s (模型 %s)", report.title, cfg.model)
    raw = LLMClient(cfg).chat(messages, json_mode=True)
    parsed = _extract_json(raw)
    result = _normalize(parsed, report)
    result["meta"] = {
        "model": cfg.model,
        "analyzed_at": datetime.now().isoformat(),
        "device_count": report.total_devices,
    }
    logger.info(
        "AI 分析完成: 健康评分 %d, 风险 %s, 关键发现 %d 项",
        result["health_score"], result["overall_risk"],
        len(result["key_findings"]),
    )
    return result


def risk_label_cn(risk: str) -> str:
    """风险等级的中文标签。"""
    return _SEVERITY_CN.get(risk, risk)
