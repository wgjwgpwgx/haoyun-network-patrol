"""Excel 台账报告生成器(报告模板三:设备台账 / 巡检结果矩阵 / 异常跟踪)

面向甲方归档习惯:三个 Sheet,状态着色,可多设备合一份。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from patrol.models import CheckStatus, PatrolReport
from patrol.reporter.base import BaseReporter

logger = logging.getLogger(__name__)

# 配色(与 Web 报告三色一致)
_HEADER_FILL = PatternFill("solid", fgColor="1B5FA8")
_PASS_FILL = PatternFill("solid", fgColor="E8F5E9")
_FAIL_FILL = PatternFill("solid", fgColor="FDECEA")
_UNKNOWN_FILL = PatternFill("solid", fgColor="FFF8E1")
_THIN = Side(style="thin", color="D0D0D0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

_STATUS_CN = {"PASS": "通过", "FAIL": "异常", "UNKNOWN": "未知"}


def _text_cell(value):
    """设备名/客户名等用户可控文本写入单元格前中和公式前缀:
    以 = + - @ 开头的字符串会被 Excel 当作公式执行。"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _style_header(ws, row: int = 1) -> None:
    for cell in ws[row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER
    # 用字符串坐标设冻结,避免 ws.cell() 实例化出空行
    ws.freeze_panes = f"A{row + 1}"


def _autowidth(ws, max_width: int = 46) -> None:
    for col in ws.columns:
        width = max((len(str(c.value or "")) + sum(
            1 for ch in str(c.value or "") if ord(ch) > 127)  # 中文按 2 宽计
            for c in col), default=8)
        ws.column_dimensions[get_column_letter(col[0].column)].width = \
            min(max(width + 2, 8), max_width)


class ExcelReporter(BaseReporter):
    """生成 Excel 台账报告(模板三)"""

    def generate(self, report: PatrolReport, output_path: Path) -> Path:
        wb = Workbook()

        self._sheet_inventory(wb.active, report)
        self._sheet_matrix(wb.create_sheet(), report)
        self._sheet_issues(wb.create_sheet(), report)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(output_path))
        logger.info("Excel 台账报告已生成: %s", output_path)
        return output_path

    # ── Sheet1 设备台账 ────────────────────────────────────────

    def _sheet_inventory(self, ws, report: PatrolReport) -> None:
        from patrol.scoring import score_device

        ws.title = "设备台账"
        headers = ["归属客户", "设备名称", "管理IP", "厂商", "设备型号",
                   "软件版本", "健康分", "运行时长", "通过", "异常", "未知", "备注"]
        ws.append(headers)
        _style_header(ws)

        for d in report.devices:
            health = score_device(d)
            cell_row = ws.max_row + 1
            ws.append([_text_cell(v) for v in [
                d.asset.customer or "未指定", d.asset.name, d.asset.host,
                d.asset.vendor, d.model or "未知", d.software_version or "未知",
                ("数据不足" if health["score"] is None
                 else f"{health['score']}({health['grade']})"),
                d.uptime or "未知",
                d.pass_count, d.fail_count, d.unknown_count,
                d.error or "",
            ]])
            # 分级着色:≥90 绿 / 60-89 黄 / <60 红 / 无法判定 灰
            hs = health["score"]
            fill = (_UNKNOWN_FILL if hs is None else
                    _PASS_FILL if hs >= 90 else
                    _UNKNOWN_FILL if hs >= 60 else _FAIL_FILL)
            ws.cell(row=cell_row, column=7).fill = fill
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = _BORDER
                cell.alignment = _LEFT
        _autowidth(ws)

    # ── Sheet2 巡检结果矩阵(设备 × 检查项,着色) ─────────────

    def _sheet_matrix(self, ws, report: PatrolReport) -> None:
        ws.title = "巡检结果矩阵"
        # 收集全部检查项名(保持出现顺序,device_info 类展示项也纳入)
        items: list[str] = []
        for d in report.devices:
            for it in d.check_items:
                if it.name not in items:
                    items.append(it.name)
        ws.append(["设备名称"] + items)
        _style_header(ws)

        for d in report.devices:
            ws.append([_text_cell(d.asset.name)] + [""] * len(items))
            by_name = {it.name: it for it in d.check_items}
            r = ws.max_row
            for idx, name in enumerate(items, start=1):
                it = by_name.get(name)
                if it is None:
                    continue
                cell = ws.cell(row=r, column=idx + 1,
                               value=_STATUS_CN[it.status.value])
                fill = {"PASS": _PASS_FILL, "FAIL": _FAIL_FILL,
                        "UNKNOWN": _UNKNOWN_FILL}[it.status.value]
                cell.fill = fill
                cell.alignment = _CENTER
                cell.border = _BORDER
            ws.cell(row=r, column=1).border = _BORDER
            ws.cell(row=r, column=1).alignment = _LEFT
        _autowidth(ws, max_width=18)

    # ── Sheet3 异常跟踪 ────────────────────────────────────────

    def _sheet_issues(self, ws, report: PatrolReport) -> None:
        ws.title = "异常跟踪"
        headers = ["设备名称", "检查项", "级别", "问题描述", "整改建议",
                   "连续期次", "巡检时间"]
        ws.append(headers)
        _style_header(ws)

        # 连续 FAIL 期次(销号清单 #8;无历史库时为空)
        streaks: dict = {}
        try:
            from patrol.storage.history import HistoryStore
            streaks = HistoryStore().fail_streaks()
        except Exception:  # noqa: BLE001 - 历史库不可用不影响导出
            pass

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = 0
        for d in report.devices:
            for it in d.check_items:
                if it.status != CheckStatus.FAIL:
                    continue
                streak = streaks.get((d.asset.name, it.name))
                ws.append([_text_cell(v) for v in [
                    d.asset.name, it.name,
                    str(it.details.get("severity", "warning")),
                    it.message,
                    str(it.details.get("suggestion", "") or ""),
                    streak if streak and streak >= 2 else "",
                    ts,
                ]])
                if streak and streak >= 3:  # 连续3期以上标红提醒
                    ws.cell(row=ws.max_row, column=6).font = Font(
                        bold=True, color="C0392B")
                rows += 1
        if rows == 0:
            ws.append(["无异常项", "", "", "", "", "", ""])
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = _BORDER
                cell.alignment = _LEFT
                if cell.column == 3 and cell.value in ("critical",):
                    cell.font = Font(bold=True, color="C0392B")
        _autowidth(ws)


def generate_excel_filename(report: PatrolReport) -> str:
    """生成 Excel 报告文件名:巡检台账_{设备名称}_{时间}.xlsx(与 Word 命名一致)。"""
    from patrol.utils.filename import safe_component

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if report.devices:
        return f"巡检台账_{safe_component(report.devices[0].asset.name)}_{ts}.xlsx"
    return f"巡检台账_{ts}.xlsx"
