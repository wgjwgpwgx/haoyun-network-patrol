"""Excel 台账报告(模板三)测试"""
from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from patrol.models import (
    CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport,
)
from patrol.reporter.excel import ExcelReporter, generate_excel_filename


def _report() -> PatrolReport:
    asset_a = DeviceAsset(name="核心交换", customer="演示单位", host="10.0.0.1",
                          vendor="huawei", device_type="vrp_switch")
    dev_a = DeviceReport(asset=asset_a, model="S5735", software_version="V200R019")
    dev_a.check_items = [
        CheckItem(name="cpu_usage", category="CPU", command="display cpu-usage",
                  raw_output="", status=CheckStatus.PASS, message="通过"),
        CheckItem(name="fan_status", category="风扇", command="display fan",
                  raw_output="", status=CheckStatus.FAIL, message="风扇故障",
                  details={"severity": "critical", "suggestion": "更换风扇框"}),
    ]
    asset_b = DeviceAsset(name="出口防火墙", customer="演示单位", host="10.0.0.2",
                          vendor="sangfor", device_type="ngaf_firewall")
    dev_b = DeviceReport(asset=asset_b)
    dev_b.check_items = [
        CheckItem(name="cpu_usage", category="CPU", command="get cpu",
                  raw_output="", status=CheckStatus.UNKNOWN, message="解析失败"),
    ]
    return PatrolReport(title="测试台账", devices=[dev_a, dev_b])


def test_excel_three_sheets(tmp_path: Path):
    out = tmp_path / "台账.xlsx"
    ExcelReporter().generate(_report(), out)
    assert out.exists() and out.stat().st_size > 4000

    wb = load_workbook(str(out))
    assert wb.sheetnames == ["设备台账", "巡检结果矩阵", "异常跟踪"]

    # Sheet1 台账(第 7 列为健康分,通过/异常计数在 I/J)
    inv = wb["设备台账"]
    assert inv["A2"].value == "演示单位" and inv["B2"].value == "核心交换"
    # 该设备 fan FAIL(severity=critical)触发一票否决 → 40 分差级
    assert inv["G1"].value == "健康分" and str(inv["G2"].value).startswith("40(")
    assert inv["I2"].value == 1 and inv["J2"].value == 1  # 通过/异常计数

    # Sheet2 矩阵:检查项列 + 着色
    mx = wb["巡检结果矩阵"]
    assert mx["A1"].value == "设备名称"
    headers = [c.value for c in mx[1]][1:]
    assert set(headers) == {"cpu_usage", "fan_status"}
    # 设备A:cpu=通过(绿),fan=异常(红);设备B:cpu=未知(黄)
    row_a = 2
    row_b = 3
    assert mx.cell(row=row_a, column=2).value == "通过"
    assert mx.cell(row=row_a, column=3).value == "异常"
    assert mx.cell(row=row_b, column=2).value == "未知"
    assert mx.cell(row=row_a, column=3).fill.fgColor.rgb.endswith("FDECEA")

    # Sheet3 异常:1 条 FAIL,含建议
    issues = wb["异常跟踪"]
    assert issues["A2"].value == "核心交换"
    assert "更换风扇框" in issues["E2"].value


def test_no_failures_sheet(tmp_path: Path):
    """无异常时异常跟踪显示占位行,不空表。"""
    asset = DeviceAsset(name="正常设备", host="10.0.0.9", vendor="h3c")
    dev = DeviceReport(asset=asset)
    dev.check_items = [CheckItem(name="cpu_usage", category="CPU", command="c",
                                 raw_output="", status=CheckStatus.PASS,
                                 message="通过")]
    out = tmp_path / "ok.xlsx"
    ExcelReporter().generate(PatrolReport(devices=[dev]), out)
    wb = load_workbook(str(out))
    assert wb["异常跟踪"]["A2"].value == "无异常项"


def test_filename():
    name = generate_excel_filename(_report())
    assert name.startswith("巡检台账_核心交换_") and name.endswith(".xlsx")
