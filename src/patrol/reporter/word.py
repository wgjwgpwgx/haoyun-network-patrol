"""Word 报告生成器

生成结构化的 .docx 巡检报告，包含：
  - 封面（报告标题、巡检时间、生成时间）
  - 目录（自动生成）
  - 报告摘要
  - 风险汇总表格
  - 设备清单表格
  - 单设备详情（每个设备一个章节）

文件命名：巡检报告_{设备名称}_{日期时间}.docx
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

from patrol.models import CheckStatus, PatrolReport, DeviceReport
from patrol.reporter.base import BaseReporter
from patrol.utils.filename import safe_component
from patrol.utils.redact import redact

logger = logging.getLogger(__name__)

# 状态颜色
_STATUS_COLORS = {
    "PASS": RGBColor(0x52, 0xC4, 0x1A),
    "FAIL": RGBColor(0xFF, 0x4D, 0x4F),
    "UNKNOWN": RGBColor(0xFA, 0xAD, 0x14),
}

_SEVERITY_COLORS = {
    "critical": RGBColor(0xFF, 0x4D, 0x4F),
    "warning": RGBColor(0xFA, 0xAD, 0x14),
    "info": RGBColor(0x18, 0x90, 0xFF),
}

# severity 英文枚举 → 报告中文级别
_SEVERITY_CN = {"critical": "严重", "warning": "警告", "info": "提示"}

_SEVERITY_BG = {
    "critical": "FF4D4F",
    "warning": "FAAD14",
    "info": "1890FF",
}


def load_report_style() -> dict:
    """读取 config/report_style.yaml(缺省空)。"""
    import yaml

    path = Path("config/report_style.yaml")
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 样式坏配置不阻断报告
        return {}


def _style_color(key: str, default: RGBColor) -> RGBColor:
    """从样式配置取颜色,非法值回退默认。"""
    raw = str(load_report_style().get(key, "") or "").strip()
    if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return RGBColor(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    return default


def _set_cell_bg(cell, color_hex: str) -> None:
    """设置单元格背景色。"""
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def _set_cell_text(cell, text: str, bold: bool = False, color: RGBColor = None, align=None, size: int = 10) -> None:
    """设置单元格文本样式。"""
    cell.text = ""
    p = cell.paragraphs[0]
    if align:
        p.alignment = align
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if bold:
        run.bold = True
    if color:
        run.font.color.rgb = color


class WordReporter(BaseReporter):
    """生成 Word (.docx) 格式的巡检报告"""

    def generate(self, report: PatrolReport, output_path: Path,
                 meta: dict | None = None,
                 history=None) -> Path:
        """生成 Word 报告。

        meta 为商务交付信息(可选):customer 甲方 / vendor_company 乙方 /
        contract_no 合同号 / report_no 报告编号 / inspector 巡检人 /
        reviewer 审核人 / formal=True 时为正式汇报版(跳过逐设备原始回显)。
        """
        doc = Document()
        formal = bool(meta and meta.get("formal"))

        # 设置默认字体
        style = doc.styles["Normal"]
        font = style.font
        font.name = "Microsoft YaHei"
        font.size = Pt(10)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

        # ── 封面 ──────────────────────────────────────────────
        self._add_cover(doc, report, meta)

        # ── 目录 ──────────────────────────────────────────────
        self._add_toc(doc)

        # ── 报告摘要 ──────────────────────────────────────────
        self._add_summary(doc, report)

        # ── AI 智能分析(如有) ────────────────────────────────
        if report.ai_analysis:
            self._add_ai_summary(doc, report)

        # ── 风险汇总 ──────────────────────────────────────────
        self._add_risk_summary(doc, report)

        # ── 上期问题复查(有历史库时) ─────────────────────────
        self._add_review_section(doc, report, history)

        # ── 配置变更对比(有上期快照时) ────────────────────────
        self._add_config_diff_section(doc, report)

        # ── 设备清单 ──────────────────────────────────────────
        self._add_device_list(doc, report)

        # ── 单设备详情(正式汇报版跳过,保持精简篇幅) ──────────
        if not formal:
            for device in report.devices:
                self._add_device_detail(doc, device)

        # ── 签字盖章页(正式交付) ──────────────────────────────
        if meta:
            self._add_signature_page(doc, meta)

        # ── 页脚 ──────────────────────────────────────────────
        self._add_footer(doc, report)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path))
        logger.info("Word 报告已生成: %s", output_path)
        return output_path

    # ── 封面 ──────────────────────────────────────────────────

    def _add_cover(self, doc: Document, report: PatrolReport,
                   meta: dict | None = None) -> None:
        """封面：标题、巡检时间、生成时间;meta 存在时输出商务交付信息表。"""
        # 空行
        for _ in range(4):
            doc.add_paragraph("")

        # 标题
        title_p = doc.add_paragraph()
        title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title_p.add_run(report.title)
        run.font.size = Pt(28)
        run.bold = True
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        run.font.color.rgb = _style_color(
            "title_color", RGBColor(0x1A, 0x1A, 0x2E))

        # 分隔线
        doc.add_paragraph("")

        # 信息表
        info_p = doc.add_paragraph()
        info_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = info_p.add_run(f"设备数量: {report.total_devices} 台")
        run.font.size = Pt(14)
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

        doc.add_paragraph("")

        time_p = doc.add_paragraph()
        time_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = time_p.add_run(f"生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        run.font.size = Pt(12)
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        # 商务交付信息表(有 meta 才渲染;空值行不出现)
        if meta:
            rows = [(k, v) for k, v in (
                ("甲方单位", meta.get("customer", "")),
                ("乙方单位", meta.get("vendor_company", "")),
                ("合同编号", meta.get("contract_no", "")),
                ("报告编号", meta.get("report_no", "")),
                ("巡检人", meta.get("inspector", "")),
                ("审核人", meta.get("reviewer", "")),
                ("报告版本", "正式汇报版" if meta.get("formal") else "工程明细版"),
            ) if v]
            if rows:
                for _ in range(3):
                    doc.add_paragraph("")
                table = doc.add_table(rows=len(rows), cols=2, style="Table Grid")
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for i, (label, value) in enumerate(rows):
                    _set_cell_text(table.rows[i].cells[0], label, bold=True,
                                   align=WD_ALIGN_PARAGRAPH.CENTER)
                    _set_cell_bg(table.rows[i].cells[0], "F8F8F8")
                    _set_cell_text(table.rows[i].cells[1], str(value))

        # 分页
        doc.add_page_break()

    # ── 目录 ──────────────────────────────────────────────────

    def _add_toc(self, doc: Document) -> None:
        """插入自动目录（Word 打开后右键更新域即可生成）。"""
        doc.add_heading("目录", level=1)
        p = doc.add_paragraph()
        run = p.add_run()
        fld_char_begin = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
        run._element.append(fld_char_begin)
        run2 = p.add_run()
        instr = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText>')
        run2._element.append(instr)
        run3 = p.add_run()
        fld_char_end = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
        run3._element.append(fld_char_end)
        doc.add_page_break()

    # ── 报告摘要 ──────────────────────────────────────────────

    def _add_summary(self, doc: Document, report: PatrolReport) -> None:
        """报告摘要：设备数、PASS/FAIL/UNKNOWN 统计。"""
        doc.add_heading("报告摘要", level=1)

        total_pass = sum(d.pass_count for d in report.devices)
        total_fail = sum(d.fail_count for d in report.devices)
        total_unknown = sum(d.unknown_count for d in report.devices)

        table = doc.add_table(rows=2, cols=4, style="Table Grid")
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        headers = ["设备总数", "PASS", "FAIL", "UNKNOWN"]
        values = [str(report.total_devices), str(total_pass), str(total_fail), str(total_unknown)]
        colors = [None, _STATUS_COLORS["PASS"], _STATUS_COLORS["FAIL"], _STATUS_COLORS["UNKNOWN"]]

        for i, (header, value, color) in enumerate(zip(headers, values, colors)):
            _set_cell_text(table.rows[0].cells[i], header, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_text(table.rows[1].cells[i], value, bold=True, color=color, align=WD_ALIGN_PARAGRAPH.CENTER, size=14)

        # 全网健康评分(本地模型,五类加权+critical 否决)
        from patrol.scoring import score_report
        overall = score_report(report)
        # 安全合规(等保基线项)达标率
        sec_pass = sum(v["groups"].get("security", {}).get("pass", 0)
                       for v in overall["devices"].values())
        sec_fail = sum(v["groups"].get("security", {}).get("fail", 0)
                       for v in overall["devices"].values())
        sec_total = sec_pass + sec_fail
        if overall["overall"] is not None:
            p_ = doc.add_paragraph()
            p_.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p_.add_run(
                f"全网健康评分:{overall['overall']}({overall['overall_grade']})")
            run.bold = True
            run.font.size = Pt(14)
            run.font.name = "Microsoft YaHei"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
            run.font.color.rgb = _style_color(
                "primary_color", RGBColor(0x1B, 0x5F, 0xA8))
        if sec_total:
            rate = round(sec_pass / sec_total * 100)
            p2 = doc.add_paragraph()
            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run2 = p2.add_run(
                f"安全基线达标率:{rate}%({sec_pass}/{sec_total} 项达标)")
            run2.bold = True
            run2.font.size = Pt(12)
            run2.font.name = "Microsoft YaHei"
            run2._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
            run2.font.color.rgb = RGBColor(
                0x52, 0xC4, 0x1A) if rate >= 80 else RGBColor(0xFA, 0xAD, 0x14)

        doc.add_paragraph("")

    # ── AI 智能分析汇总 ───────────────────────────────────────

    _RISK_CN = {"low": "低", "medium": "中", "high": "高", "critical": "严重"}
    _SEV_CN = {"high": "高", "medium": "中", "low": "低"}

    def _add_ai_summary(self, doc: Document, report: PatrolReport) -> None:
        """AI 大模型分析汇总章节。"""
        ai = report.ai_analysis or {}

        doc.add_heading("AI 综合分析汇总", level=1)

        meta = ai.get("meta") or {}
        if meta.get("model"):
            p = doc.add_paragraph()
            run = p.add_run(
                f"由大模型({meta['model']})结合设备原始输出整体融合分析生成"
            )
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        # 评分与风险等级
        risk = ai.get("overall_risk", "medium")
        risk_cn = self._RISK_CN.get(risk, risk)
        table = doc.add_table(rows=2, cols=2, style="Table Grid")
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_cell_text(table.rows[0].cells[0], "健康评分", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_cell_text(table.rows[0].cells[1], "总体风险等级", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_cell_text(
            table.rows[1].cells[0], str(ai.get("health_score", "-")),
            bold=True, color=RGBColor(0x2B, 0x4A, 0xA8),
            align=WD_ALIGN_PARAGRAPH.CENTER, size=14,
        )
        _set_cell_text(
            table.rows[1].cells[1], risk_cn, bold=True,
            align=WD_ALIGN_PARAGRAPH.CENTER, size=12,
        )
        doc.add_paragraph("")

        # 总体评估
        if ai.get("executive_summary"):
            doc.add_heading("总体评估", level=2)
            p = doc.add_paragraph(ai["executive_summary"])
            p.paragraph_format.line_spacing = 1.5

        # 分设备综合评估(设备输出 + AI 分析融合)
        assessments = ai.get("device_assessments") or []
        if assessments:
            doc.add_heading("分设备综合评估", level=2)
            atable = doc.add_table(rows=1, cols=2, style="Table Grid")
            for i, h in enumerate(("设备", "AI 综合评估(结合原始输出)")):
                _set_cell_text(atable.rows[0].cells[i], h, bold=True,
                               align=WD_ALIGN_PARAGRAPH.CENTER)
                _set_cell_bg(atable.rows[0].cells[i], "F2F6FF")
            for a in assessments:
                row = atable.add_row()
                _set_cell_text(row.cells[0], str(a.get("device", "")), bold=True)
                _set_cell_text(row.cells[1], str(a.get("assessment", "")))
            doc.add_paragraph("")

        # 关键发现
        findings = ai.get("key_findings") or []
        if findings:
            doc.add_heading("关键发现", level=2)
            ftable = doc.add_table(rows=1, cols=4, style="Table Grid")
            headers = ["设备", "问题", "级别", "处置建议"]
            for i, h in enumerate(headers):
                _set_cell_text(ftable.rows[0].cells[i], h, bold=True,
                               align=WD_ALIGN_PARAGRAPH.CENTER)
                _set_cell_bg(ftable.rows[0].cells[i], "F2F6FF")
            for f in findings:
                row = ftable.add_row()
                sev = str(f.get("severity", "medium"))
                _set_cell_text(row.cells[0], str(f.get("device", "")), bold=True)
                issue = str(f.get("issue", ""))
                if f.get("impact"):
                    issue += f"\n影响: {f['impact']}"
                _set_cell_text(row.cells[1], issue)
                _set_cell_text(row.cells[2], self._SEV_CN.get(sev, sev),
                               align=WD_ALIGN_PARAGRAPH.CENTER)
                _set_cell_text(row.cells[3], str(f.get("recommendation", "")))
            doc.add_paragraph("")

        # 处置建议
        recs = ai.get("recommendations") or []
        if recs:
            doc.add_heading("处置建议(按优先级)", level=2)
            for i, r in enumerate(recs, 1):
                doc.add_paragraph(f"{i}. {r}")

        # 中长期建议
        maint = ai.get("maintenance_suggestions") or []
        if maint:
            doc.add_heading("中长期优化建议", level=2)
            for s in maint:
                doc.add_paragraph(f"• {s}")

        doc.add_page_break()

    # ── 风险汇总 ──────────────────────────────────────────────

    def _add_review_section(self, doc: Document, report: PatrolReport,
                            history=None) -> None:
        """上期问题复查(销号清单 #8):上期 FAIL 项的本期闭环状态。"""
        store = history
        if store is None:
            try:
                from patrol.storage.history import HistoryStore
                store = HistoryStore()
            except Exception:  # noqa: BLE001 - 无库则跳过
                return
        try:
            prev = store.prev_fail_items(
                before_time=report.generated_at.isoformat(),
                device_names=[d.asset.name for d in report.devices])
        except Exception:  # noqa: BLE001
            return
        if not prev:
            return

        current = {(d.asset.name, it.name): it.status.value
                   for d in report.devices for it in d.check_items}
        doc.add_heading("上期问题复查", level=1)
        table = doc.add_table(rows=len(prev) + 1, cols=4, style="Table Grid")
        for i, h in enumerate(("设备", "检查项", "上期问题", "本期状态")):
            _set_cell_text(table.rows[0].cells[i], h, bold=True,
                           align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_bg(table.rows[0].cells[i], "F0F0F0")
        for r, ((dev, check), info) in enumerate(prev.items(), start=1):
            status = current.get((dev, check), "未采集")
            cn = {"PASS": "已解决", "FAIL": "仍存在",
                  "UNKNOWN": "无法判断"}.get(status, status)
            _set_cell_text(table.rows[r].cells[0], dev)
            _set_cell_text(table.rows[r].cells[1], check)
            _set_cell_text(table.rows[r].cells[2],
                           info.get("message", "")[:60])
            cell = table.rows[r].cells[3]
            _set_cell_text(cell, cn, bold=(status == "FAIL"),
                           align=WD_ALIGN_PARAGRAPH.CENTER)
            if status == "PASS":
                _set_cell_bg(cell, "E8F5E9")
            elif status == "FAIL":
                _set_cell_bg(cell, "FDECEA")
        doc.add_paragraph("")

    def _add_config_diff_section(self, doc: Document,
                                 report: PatrolReport) -> None:
        """配置变更对比(销号清单 #9):本期 running 与上期快照 unified diff。"""
        import difflib

        from patrol.utils.config_snapshot import previous_snapshot

        sections = 0
        for d in report.devices:
            item = next((it for it in d.check_items
                         if it.name == "config_cur" and it.raw_output), None)
            if item is None:
                continue
            prev = previous_snapshot(d.asset.name, item.raw_output)
            if prev is None:
                continue
            prev_text, prev_ts = prev
            if sections == 0:
                doc.add_heading("配置变更对比", level=1)
            sections += 1
            doc.add_heading(
                f"{d.asset.name}(对比快照 {prev_ts})", level=2)
            diff = list(difflib.unified_diff(
                prev_text.splitlines(), item.raw_output.splitlines(),
                fromfile="上期配置", tofile="本期配置", lineterm="", n=1))
            shown = [ln for ln in diff[2:]][:80]  # 跳过文件头两行,限 80 行
            if not shown:
                doc.add_paragraph("配置无实质差异。")
                continue
            for ln in shown:
                p_ = doc.add_paragraph()
                p_.paragraph_format.space_after = Pt(0)
                run = p_.add_run(ln if ln.strip() else " ")
                run.font.name = "Consolas"
                run.font.size = Pt(8.5)
                run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
                if ln.startswith("+"):
                    run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)
                elif ln.startswith("-"):
                    run.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
                elif ln.startswith("@@"):
                    run.font.color.rgb = RGBColor(0x75, 0x75, 0x75)
            doc.add_paragraph("")

    def _add_risk_summary(self, doc: Document, report: PatrolReport) -> None:
        """风险汇总：所有 FAIL 项按严重级别列出。"""
        fail_items = []
        for device in report.devices:
            for item in device.check_items:
                if item.status == CheckStatus.FAIL:
                    severity = item.details.get("severity", "warning")
                    fail_items.append({
                        "device": device.asset.name,
                        "category": item.category,
                        "message": item.message,
                        "severity": severity,
                        "suggestion": item.details.get("suggestion", ""),
                    })

        if not fail_items:
            doc.add_heading("风险汇总", level=1)
            doc.add_paragraph("未发现风险项，所有检查通过。", style="Intense Quote")
            doc.add_paragraph("")
            return

        # 严重级优先(critical → warning → info),同级保持出现顺序
        _sev_order = {"critical": 0, "warning": 1, "info": 2}
        fail_items.sort(key=lambda x: _sev_order.get(x["severity"], 3))

        doc.add_heading(f"风险汇总（{len(fail_items)} 项）", level=1)

        table = doc.add_table(rows=len(fail_items) + 1, cols=5, style="Table Grid")

        # 表头
        headers = ["设备", "检查项", "级别", "问题描述", "整改建议"]
        for i, header in enumerate(headers):
            _set_cell_text(table.rows[0].cells[i], header, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_bg(table.rows[0].cells[i], "F0F0F0")

        # 数据行
        for row_idx, item in enumerate(fail_items, start=1):
            _set_cell_text(table.rows[row_idx].cells[0], item["device"])
            _set_cell_text(table.rows[row_idx].cells[1], item["category"])

            # 级别带颜色(色块内白字,同色文字会看不见)
            sev = item["severity"]
            if sev in _SEVERITY_BG:
                _set_cell_bg(table.rows[row_idx].cells[2], _SEVERITY_BG[sev])
                _set_cell_text(table.rows[row_idx].cells[2], _SEVERITY_CN.get(sev, sev),
                               bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
            else:
                _set_cell_text(table.rows[row_idx].cells[2], _SEVERITY_CN.get(sev, sev),
                               bold=True,
                               color=_SEVERITY_COLORS.get(sev, RGBColor(0x99, 0x99, 0x99)))

            _set_cell_text(table.rows[row_idx].cells[3], item["message"])
            _set_cell_text(table.rows[row_idx].cells[4], item["suggestion"])

        doc.add_paragraph("")

    # ── 设备清单 ──────────────────────────────────────────────

    def _add_device_list(self, doc: Document, report: PatrolReport) -> None:
        """设备清单表格。"""
        doc.add_heading("设备清单", level=1)

        table = doc.add_table(rows=len(report.devices) + 1, cols=7, style="Table Grid")

        headers = ["设备名称", "管理 IP", "型号", "版本", "PASS", "FAIL", "UNKNOWN"]
        for i, header in enumerate(headers):
            _set_cell_text(table.rows[0].cells[i], header, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_bg(table.rows[0].cells[i], "F0F0F0")

        for row_idx, device in enumerate(report.devices, start=1):
            _set_cell_text(table.rows[row_idx].cells[0], device.asset.name)
            _set_cell_text(table.rows[row_idx].cells[1], device.asset.host)
            _set_cell_text(table.rows[row_idx].cells[2], device.model or "-")
            _set_cell_text(table.rows[row_idx].cells[3], device.software_version or "-")
            _set_cell_text(table.rows[row_idx].cells[4], str(device.pass_count), color=_STATUS_COLORS["PASS"], align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_text(table.rows[row_idx].cells[5], str(device.fail_count), color=_STATUS_COLORS["FAIL"], align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_text(table.rows[row_idx].cells[6], str(device.unknown_count), color=_STATUS_COLORS["UNKNOWN"], align=WD_ALIGN_PARAGRAPH.CENTER)

        doc.add_page_break()

    # ── 单设备详情 ────────────────────────────────────────────

    def _add_device_detail(self, doc: Document, device: DeviceReport) -> None:
        """单设备详情章节。"""
        doc.add_heading(device.asset.name, level=1)

        # 设备信息表
        doc.add_heading("设备信息", level=2)
        from patrol.scoring import score_device
        health = score_device(device)
        info_table = doc.add_table(rows=8, cols=2, style="Table Grid")
        info_data = [
            ("健康评分", f"{health['score']}({health['grade']})"
             + (" [存在严重告警,已降档]" if health["veto"] else "")),
            ("归属客户", device.asset.customer or "未指定"),
            ("管理 IP", device.asset.host),
            ("设备型号", device.model or "未知"),
            ("软件版本", device.software_version or "未知"),
            ("运行时间", device.uptime or "未知"),
            ("巡检时间", device.collected_at.strftime("%Y-%m-%d %H:%M:%S")),
            ("巡检结果", device.summary),
        ]
        for i, (label, value) in enumerate(info_data):
            _set_cell_text(info_table.rows[i].cells[0], label, bold=True)
            _set_cell_text(info_table.rows[i].cells[1], str(value))
            _set_cell_bg(info_table.rows[i].cells[0], "F8F8F8")

        doc.add_paragraph("")

        if device.error:
            doc.add_heading("巡检异常", level=2)
            p = doc.add_paragraph()
            run = p.add_run(device.error)
            run.font.color.rgb = _STATUS_COLORS["FAIL"]
            doc.add_page_break()
            return

        # 检查结果表:每个检查项占一行;有原始输出的项下方跟一整行平滑对齐的原始输出
        doc.add_heading("检查结果", level=2)
        rows_plan: list[tuple[str, CheckItem]] = []
        for item in device.check_items:
            rows_plan.append(("item", item))
            if item.raw_output:
                rows_plan.append(("raw", item))
        table = doc.add_table(rows=len(rows_plan) + 1, cols=4, style="Table Grid")

        headers = ["检查项", "状态", "级别", "结果"]
        for i, header in enumerate(headers):
            _set_cell_text(table.rows[0].cells[i], header, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_bg(table.rows[0].cells[i], "F0F0F0")

        for row_idx, (kind, item) in enumerate(rows_plan, start=1):
            if kind == "raw":
                # 原始输出子行:四列合并为一整行,命令+设备回显等宽对齐展示
                cell = table.rows[row_idx].cells[0].merge(table.rows[row_idx].cells[3])
                cell.text = ""
                p = cell.paragraphs[0]
                head = p.add_run(f"原始输出(执行命令: {item.command or '—'})")
                head.font.size = Pt(8)
                head.font.color.rgb = RGBColor(0x66, 0x78, 0x8C)
                head.font.name = "Microsoft YaHei"
                head._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
                raw_p = cell.add_paragraph()
                raw_run = raw_p.add_run(redact(item.raw_output) or "(无原始输出)")
                raw_run.font.size = Pt(8)
                raw_run.font.name = "Consolas"
                _set_cell_bg(cell, "F6F8FB")
                continue

            _set_cell_text(table.rows[row_idx].cells[0], item.category)

            # 状态带颜色
            status_color = _STATUS_COLORS.get(item.status.value, RGBColor(0, 0, 0))
            _set_cell_text(table.rows[row_idx].cells[1], item.status.value, bold=True, color=status_color, align=WD_ALIGN_PARAGRAPH.CENTER)

            # 级别(中文展示)
            severity = item.details.get("severity", "-")
            sev_color = _SEVERITY_COLORS.get(severity, RGBColor(0x99, 0x99, 0x99))
            _set_cell_text(table.rows[row_idx].cells[2], _SEVERITY_CN.get(severity, severity),
                           color=sev_color, align=WD_ALIGN_PARAGRAPH.CENTER)

            # 结果
            msg = redact(item.message)
            suggestion = item.details.get("suggestion", "")
            if item.status == CheckStatus.FAIL and suggestion:
                msg += f"\n建议: {suggestion}"
            _set_cell_text(table.rows[row_idx].cells[3], msg)

        doc.add_page_break()

    # ── 页脚 ──────────────────────────────────────────────────

    def _add_signature_page(self, doc: Document, meta: dict) -> None:
        """签字盖章页:三方签字栏 + 甲乙双方盖章区(甲乙双方留存的交付要素)。"""
        doc.add_page_break()
        doc.add_heading("签字确认", level=1)
        doc.add_paragraph("")

        table = doc.add_table(rows=4, cols=3, style="Table Grid")
        headers = ("角色", "签名", "日期")
        for i, h in enumerate(headers):
            _set_cell_text(table.rows[0].cells[i], h, bold=True,
                           align=WD_ALIGN_PARAGRAPH.CENTER)
            _set_cell_bg(table.rows[0].cells[i], "F0F0F0")
        roles = ("巡检人" + (f"({meta['inspector']})" if meta.get("inspector") else ""),
                 "审核人" + (f"({meta['reviewer']})" if meta.get("reviewer") else ""),
                 "甲方接收人")
        for r, role in enumerate(roles, start=1):
            _set_cell_text(table.rows[r].cells[0], role)
            # 签名/日期留空供手写
            _set_cell_text(table.rows[r].cells[1], "")
            _set_cell_text(table.rows[r].cells[2], "    年   月   日")
            # 行高留出手写空间
            tr = table.rows[r]._tr
            trPr = tr.get_or_add_trPr()
            trPr.append(parse_xml(
                f'<w:trHeight {nsdecls("w")} w:val="680" w:hRule="atLeast"/>'))

        doc.add_paragraph("")
        doc.add_paragraph("")

        # 双方盖章区:两个并排大框
        stamp = doc.add_table(rows=1, cols=2)
        for cell, label in ((stamp.rows[0].cells[0], "乙方(盖章):"),
                            (stamp.rows[0].cells[1], "甲方(盖章):")):
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.append(parse_xml(
                f'<w:tcBorders {nsdecls("w")} '
                f'w:top="single" w:bottom="single" w:left="single" w:right="single" '
                f'w:topColor="999999" w:bottomColor="999999" '
                f'w:leftColor="999999" w:rightColor="999999"/>'))
            tcPr.append(parse_xml(
                f'<w:tcMar {nsdecls("w")} '
                f'w:top="2400" w:left="200" w:bottom="200" w:right="200" '
                f'w:type="dxa"/>'))
            cell.add_paragraph("")
            cell.add_paragraph("")
            cell.add_paragraph("")
            run = cell.paragraphs[-1].add_run(label)
            run.font.size = Pt(11)
            run.font.name = "Microsoft YaHei"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    def _add_footer(self, doc: Document, report: PatrolReport) -> None:
        """页脚信息。"""
        doc.add_paragraph("")
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("昊云网络巡检助手 v0.1.0 · 报告中的敏感信息已自动脱敏")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def generate_word_filename(report: PatrolReport) -> str:
    """生成 Word 报告文件名：巡检报告_{设备名称}_{日期时间}.docx"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if report.devices:
        device_name = safe_component(report.devices[0].asset.name)
        return f"巡检报告_{device_name}_{ts}.docx"
    return f"巡检报告_{ts}.docx"


def build_report_meta(report: PatrolReport, formal: bool = False,
                      **extra) -> dict:
    """组装报告商务交付信息(封面/签字页用)。

    甲方取首台设备归属客户;乙方为产品作者;报告编号按日期自动生成;
    其余字段(contract_no/inspector/reviewer)可由调用方经 extra 覆盖。
    """
    from patrol.product import AUTHOR

    customer = ""
    for d in report.devices:
        if d.asset.customer:
            customer = d.asset.customer
            break
    vendor_default = str(AUTHOR)
    try:
        styled = load_report_style().get("vendor_company")
        if styled:
            vendor_default = str(styled)
    except Exception:  # noqa: BLE001
        pass
    meta: dict = {
        "customer": customer,
        "vendor_company": vendor_default,
        "report_no": report.generated_at.strftime("XJ-%Y%m%d-001"),
        "formal": formal,
    }
    meta.update({k: v for k, v in extra.items() if v})
    return meta
