"""模拟器端到端:真实 netmiko(Telnet) → 内置模拟设备 → 驱动解析 → 规则判定。

不替换采集器、不替换驱动——这是此前完全缺失的一层:此前只有 socket 层与
解析层的单测,采集入口"不支持 Telnet"这类断点没有任何用例能发现。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.analyzer.engine import RuleEngine
from patrol.cli import run_inspection
from patrol.drivers.registry import get_driver
from patrol.models import CheckStatus, DeviceAsset
from patrol.simulator_core import SimDeviceServer, responses_from_seed

RULES_DIR = Path(__file__).parent.parent.parent / "config" / "rules"

# (seed, vendor, device_type):五家内置样例都必须能登录并产出判定
SEEDS = [
    ("huawei", "huawei", "vrp_switch"),
    ("h3c", "h3c", "s7506e"),
    ("ruijie", "ruijie", "rgos_switch"),
    ("zte", "zte", "zxr10_switch"),
    ("maipu", "maipu", "mypower_switch"),
]


def _inspect(seed: str, vendor: str, device_type: str, port: int):
    asset = DeviceAsset(
        name=f"模拟-{seed}", host="127.0.0.1", port=port, vendor=vendor,
        device_type=device_type, login_method="telnet",
        username="any", password="any", timeout=10, command_timeout=15)
    engine = RuleEngine(RuleEngine.load_dir(RULES_DIR))
    return run_inspection(asset, get_driver(vendor, device_type), engine)


@pytest.mark.parametrize("seed,vendor,device_type", SEEDS)
def test_telnet_login_and_full_inspection(seed, vendor, device_type, tmp_path,
                                           monkeypatch):
    monkeypatch.chdir(tmp_path)  # 配置快照/知识库沉淀落到临时目录
    server = SimDeviceServer(responses=responses_from_seed(seed))
    port = server.start()
    try:
        report = _inspect(seed, vendor, device_type, port)
    finally:
        server.stop()

    assert report.error is None, f"{seed} 未能登录模拟设备: {report.error}"
    judged = [it for it in report.check_items
              if it.status in (CheckStatus.PASS, CheckStatus.FAIL)]
    assert judged, f"{seed} 没有任何一项得到判定"
    assert report.summary.startswith("PASS")

    # 拓扑是报告里的重点展示项:样例预置了 LLDP 回显,必须能解析出邻居
    lldp = next(it for it in report.check_items if it.name == "lldp_neighbor")
    assert lldp.details.get("neighbor_count", 0) >= 1


def test_vendor_rules_take_effect_on_real_pipeline(tmp_path, monkeypatch):
    """厂商专项规则必须真正参与判定(此前规则文件只加载了 default.yaml)。"""
    monkeypatch.chdir(tmp_path)
    server = SimDeviceServer(responses=responses_from_seed("maipu"))
    port = server.start()
    try:
        report = _inspect("maipu", "maipu", "mypower_switch", port)
    finally:
        server.stop()

    by_name = {it.name: it for it in report.check_items}
    assert by_name["cpu_usage"].details["rule_id"] == "MP001"
    # 迈普样例的 running-config 用的是默认团体字 public,必须判为异常
    assert by_name["snmp_community"].status == CheckStatus.FAIL
    assert by_name["snmp_community"].details["rule_id"] == "MP006"
    # 等保基线包默认关闭:不参与判定
    assert "login_lock" not in by_name


def test_unanswered_command_is_unknown_not_pass(tmp_path, monkeypatch):
    """模拟器对未预置的命令不回任何内容:这些检查项必须如实显示"无法判定"。"""
    monkeypatch.chdir(tmp_path)
    server = SimDeviceServer(responses=responses_from_seed("zte"))
    port = server.start()
    try:
        report = _inspect("zte", "zte", "zxr10_switch", port)
    finally:
        server.stop()

    routing = next(it for it in report.check_items if it.name == "routing_table")
    assert routing.status == CheckStatus.UNKNOWN
    # 没有任何一项是因为"没采集到数据"而被判通过的
    assert all(it.raw_output.strip() for it in report.check_items
               if it.status == CheckStatus.PASS and it.name != "device_info")


def test_enable_mode_is_simulated(tmp_path, monkeypatch):
    """类 IOS 设备(锐捷等)登录后落在用户模式(>),netmiko 会先 enable 再干活。"""
    monkeypatch.chdir(tmp_path)
    server = SimDeviceServer(responses=responses_from_seed("ruijie"))
    port = server.start()
    try:
        report = _inspect("ruijie", "ruijie", "rgos_switch", port)
    finally:
        server.stop()
    assert report.error is None
    assert "enable mode" not in (report.error or "")
