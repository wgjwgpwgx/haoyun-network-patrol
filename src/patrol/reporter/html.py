"""HTML 报告生成器"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from patrol import __version__
from patrol.models import CheckStatus, PatrolReport
from patrol.reporter.base import BaseReporter
from patrol.utils.redact import redact

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class HTMLReporter(BaseReporter):
    """生成 HTML 格式的巡检报告"""

    def generate(self, report: PatrolReport, output_path: Path) -> Path:
        """生成 HTML 报告，同时保存结构化 JSON 数据。

        对原始命令输出进行脱敏后渲染，确保报告中不泄露密码、密钥、SNMP Community。
        JSON 数据用于在线预览，不重新生成报告。
        """
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("report.html.j2")

        # 对原始输出脱敏
        sanitized_devices = []
        for device in report.devices:
            sanitized_items = []
            for item in device.check_items:
                sanitized_items.append(
                    item.model_copy(update={"raw_output": redact(item.raw_output)})
                )
            sanitized_devices.append(
                device.model_copy(update={"check_items": sanitized_items})
            )

        from patrol.scoring import score_device, score_report

        # 异常预测(P1 第二批 ①)
        from patrol.prediction import predict_device
        predictions = {}
        for d in sanitized_devices:
            preds = predict_device(d.asset.name)
            if preds:
                predictions[d.asset.name] = preds

        html = template.render(
            report=report,
            devices=sanitized_devices,
            scoring={d.asset.name: score_device(d) for d in sanitized_devices},
            overall=score_report(report),
            topology_svg=_topology_svg(sanitized_devices),
            pie_svg=_summary_pie(sanitized_devices),
            device_charts=_device_charts(sanitized_devices),
            predictions=predictions,
            app_version=__version__,
            CheckStatus=CheckStatus,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        logger.info("HTML 报告已生成: %s", output_path)

        # 保存结构化 JSON 数据（用于在线预览）
        json_path = output_path.with_suffix(".json")
        self._save_json(report, sanitized_devices, json_path)

        return output_path

    def _save_json(
        self, report: PatrolReport, sanitized_devices: list, json_path: Path
    ) -> None:
        """将报告数据序列化为 JSON。"""
        from patrol.scoring import score_report

        overall_scoring = score_report(report)
        sec_pass = sum(v["groups"].get("security", {}).get("pass", 0)
                       for v in overall_scoring["devices"].values())
        sec_fail = sum(v["groups"].get("security", {}).get("fail", 0)
                       for v in overall_scoring["devices"].values())
        sec_total = sec_pass + sec_fail
        # AI 执行摘要(P1 第一批 ④:管理层 100 字)
        exec_summary = _generate_exec_summary(sanitized_devices, overall_scoring)

        data = {
            "title": report.title,
            "generated_at": report.generated_at.isoformat(),
            "total_devices": report.total_devices,
            "has_failures": report.has_failures,
            "exec_summary": exec_summary,
            "health": {"overall": overall_scoring["overall"],
                       "grade": overall_scoring["overall_grade"]},
            "baseline": {
                "pass": sec_pass, "fail": sec_fail,
                "rate": round(sec_pass / sec_total * 100) if sec_total else None,
            },
            "devices": [],
        }
        if report.ai_analysis:
            data["ai_analysis"] = report.ai_analysis

        for device in sanitized_devices:
            from patrol.scoring import score_device
            health = score_device(device)
            dev = {
                "name": device.asset.name,
                "customer": device.asset.customer,
                "host": device.asset.host,
                "health": {"score": health["score"], "grade": health["grade"],
                           "veto": health["veto"]},
                "vendor": device.asset.vendor,
                "device_type": device.asset.device_type,
                "model": device.model,
                "software_version": device.software_version,
                "uptime": device.uptime,
                "serial_number": device.serial_number,
                "collected_at": device.collected_at.isoformat(),
                "error": device.error,
                "pass_count": device.pass_count,
                "fail_count": device.fail_count,
                "unknown_count": device.unknown_count,
                "summary": device.summary,
                "check_items": [],
            }
            for item in device.check_items:
                dev["check_items"].append({
                    "name": item.name,
                    "category": item.category,
                    "command": item.command,
                    "raw_output": item.raw_output,
                    "status": item.status.value,
                    "message": item.message,
                    "details": item.details,
                })
            data["devices"].append(dev)

        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("JSON 数据已保存: %s", json_path)


def _topology_svg(devices: list, width: int = 860, height: int = 640) -> str:
    """从各设备 lldp_neighbor 检查项聚合边,生成环形布局 SVG(无 JS 依赖)。"""
    import math

    from xml.sax.saxutils import escape as _esc

    edges: list[tuple[str, str, str, str]] = []  # 本端, 本端口, 对端, 对端口
    local_names = {d.asset.name for d in devices}
    for d in devices:
        for it in d.check_items:
            if it.name != "lldp_neighbor":
                continue
            for n in it.details.get("neighbors", []):
                edges.append((d.asset.name, n.get("local_intf", ""),
                              n.get("peer_device", ""), n.get("peer_port", "")))
    if not edges:
        return ""

    nodes = sorted(local_names | {e[2] for e in edges})
    cx, cy, r = width / 2, height / 2, min(width, height) / 2 - 90
    pos = {name: (cx + r * math.cos(2 * math.pi * i / len(nodes) - math.pi / 2),
                  cy + r * math.sin(2 * math.pi * i / len(nodes) - math.pi / 2))
           for i, name in enumerate(nodes)}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'style="max-width:100%;background:#fafbfd" '
        f'font-family="Microsoft YaHei">']
    seen_pairs = set()
    for a, a_port, b, b_port in edges:
        pair = tuple(sorted((a, b)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        x1, y1 = pos[a]; x2, y2 = pos[b]
        parts.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            f'stroke="#9db3d1" stroke-width="1.4"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        label = f"{_esc(a_port)} ↔ {_esc(b_port)}"
        if label.strip("↔ "):
            parts.append(
                f'<text x="{mx:.0f}" y="{my:.0f}" font-size="9" fill="#7a8aa0" '
                f'text-anchor="middle">{label}</text>')
    fail_names = {d.asset.name for d in devices
                  if any(i.status.value == "FAIL" for i in d.check_items)}
    for name, (x, y) in pos.items():
        in_report = name in local_names
        color = "#ff4d4f" if name in fail_names else (
            "#1B5FA8" if in_report else "#9e9e9e")
        fill = "#e8f1fb" if in_report else "#f2f2f2"
        parts.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="24" fill="{fill}" '
            f'stroke="{color}" stroke-width="2"/>')
        parts.append(
            f'<text x="{x:.0f}" y="{y + 4:.0f}" font-size="11" fill="#243b55" '
            f'text-anchor="middle">{_esc(name[:10])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _summary_pie(devices: list) -> str:
    """报告头状态分布饼图。"""
    from patrol.reporter.charts import pie_svg

    p = sum(1 for d in devices for i in d.check_items
            if i.status.value == "PASS")
    f = sum(1 for d in devices for i in d.check_items
            if i.status.value == "FAIL")
    u = sum(1 for d in devices for i in d.check_items
            if i.status.value == "UNKNOWN")
    return pie_svg([("通过", p, "#52c41a"), ("异常", f, "#ff4d4f"),
                    ("未知", u, "#faad14")])


def _device_charts(devices: list) -> dict:
    """每设备:CPU/内存条形图 + 历史趋势(有数据时)。返回 {设备名: {"bars","trend_cpu","trend_mem"}}"""
    from patrol.reporter.charts import bars_svg, trend_svg

    charts = {}
    history = None
    for d in devices:
        cpu = next((i for i in d.check_items if i.name == "cpu_usage"), None)
        mem = next((i for i in d.check_items if i.name == "memory_usage"), None)
        items = []
        if cpu and isinstance(cpu.details.get("usage_percent"), (int, float)):
            items.append(("CPU", cpu.details["usage_percent"]))
        if mem and isinstance(mem.details.get("usage_percent"), (int, float)):
            items.append(("内存", mem.details["usage_percent"]))
        if not items:
            continue
        entry = {"bars": bars_svg(items), "trend_cpu": "", "trend_mem": ""}
        try:
            if history is None:
                from patrol.storage.history import HistoryStore
                history = HistoryStore()
            entry["trend_cpu"] = trend_svg(
                history.metric_series(d.asset.name, "cpu_usage"))
            entry["trend_mem"] = trend_svg(
                history.metric_series(d.asset.name, "memory_usage"),
                color="#722ed1")
        except Exception:  # noqa: BLE001 - 历史不可用不影响报告
            pass
        charts[d.asset.name] = entry
    return charts


def _generate_exec_summary(devices: list, overall: dict) -> str:
    """AI 生成 100 字管理层执行摘要(无 AI 配置时用模板生成)。"""
    total = len(devices)
    fail_devs = [d.asset.name for d in devices
                 if any(i.status.value == "FAIL" for i in d.check_items)]
    unknown_count = sum(sum(1 for i in d.check_items
                          if i.status.value == "UNKNOWN") for d in devices)

    # 先尝试 AI 生成
    try:
        from patrol.ai.client import LLMClient
        from patrol.ai.config import load_ai_config
        cfg = load_ai_config()
        if cfg.enabled:
            health = overall.get("overall", "—")
            prompt = (
                f"巡检了 {total} 台网络设备,健康评分 {health},"
                f"其中 {len(fail_devs)} 台有异常"
                + (f"(异常设备:{','.join(fail_devs[:5])})" if fail_devs else "")
                + f",{unknown_count} 项无法判定。"
                + "请用不超过 100 字向甲方管理层汇报网络总体状况,"
                + "重点突出最需要关注的问题和建议行动。直接输出摘要文字。")
            reply = LLMClient(cfg).chat(
                [{"role": "user", "content": prompt}])
            return reply.strip()[:200]
    except Exception:  # noqa: BLE001 - AI 不可用回退模板
        pass

    # 模板生成(AI 未配置时的降级)
    if not fail_devs and unknown_count == 0:
        return f"本次巡检覆盖 {total} 台设备,各项检查全部通过,网络运行平稳。"
    parts = [f"本次巡检覆盖 {total} 台设备。"]
    if fail_devs:
        parts.append(f"其中 {len(fail_devs)} 台存在异常"
                     f"({','.join(fail_devs[:3])}"
                     + ("等" if len(fail_devs) > 3 else "") + "),")
        parts.append("建议重点关注并安排整改。")
    if unknown_count:
        parts.append(f"另有 {unknown_count} 项待确认。")
    return "".join(parts)
