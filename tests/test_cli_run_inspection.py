"""命令行巡检核心流程测试:软成功判定、采集通道选择、入口参数与退出码"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import patrol.cli as cli
from patrol.analyzer.engine import RuleEngine
from patrol.cli import _create_collector, run_inspection
from patrol.collector.ssh import SSHCollector
from patrol.drivers.ruijie.driver import RuijieRGOSSwitchDriver
from patrol.models import (
    CheckItem, CheckStatus, DeviceAsset, DeviceReport,
)
from patrol.utils.config_snapshot import list_snapshots

RULES = Path(__file__).parent.parent / "config" / "rules" / "default.yaml"
FIXTURES = Path(__file__).parent / "fixtures" / "ruijie" / "rgos_switch"


def _asset(**kw) -> DeviceAsset:
    return DeviceAsset(name="t", host="192.0.2.1", vendor="ruijie",
                       device_type="rgos_switch", username="u", password="p", **kw)


def _run(asset: DeviceAsset, outputs: dict[str, str]) -> DeviceReport:
    """采集器替身:按命令返回给定回显,不连任何设备。"""

    def fake_execute(self, command, timeout=60):
        return outputs.get(command, "")

    with patch.object(SSHCollector, "connect"), \
            patch.object(SSHCollector, "disconnect"), \
            patch.object(SSHCollector, "execute", fake_execute):
        return run_inspection(asset, RuijieRGOSSwitchDriver(),
                              RuleEngine(RuleEngine.load_file(RULES)))


def _item(report: DeviceReport, name: str) -> CheckItem:
    return next(it for it in report.check_items if it.name == name)


class TestUnrecognizedOutputIsUnknown:
    """空回显 / 设备报错不能被判成"检查通过"。"""

    def test_empty_output_counts_as_unknown(self):
        report = _run(_asset(), {})
        for name in ("interface_status", "logbuffer", "routing_table"):
            item = _item(report, name)
            assert item.status == CheckStatus.UNKNOWN, f"{name} 不应判通过"

    def test_device_error_text_is_unknown_not_data(self):
        """设备对不支持的命令回一行报错:接口解析器会把这行当成一个"接口",
        计数为 0 而判通过——必须在进解析器之前拦下。"""
        report = _run(_asset(), {"show ip interface brief":
                                 "Error: Unrecognized command found at '^' position."})
        item = _item(report, "interface_status")
        assert item.status == CheckStatus.UNKNOWN
        assert "设备不支持该命令" in item.message

    @pytest.mark.parametrize("reply", [
        "% Invalid input detected at '^' marker.",
        "% Authorization failed.",
        "Error: Wrong parameter found at '^' position.",
        "Permission denied",
    ])
    def test_common_vendor_error_replies(self, reply):
        report = _run(_asset(), {"show ip interface brief": reply})
        assert _item(report, "interface_status").status == CheckStatus.UNKNOWN

    def test_error_reply_is_not_saved_as_config_snapshot(self):
        report = _run(_asset(), {"show running-config": "Error: Permission denied"})
        assert _item(report, "config_cur").status == CheckStatus.UNKNOWN
        assert list_snapshots("t") == []

    def test_long_output_with_error_words_is_not_mistaken_for_failure(self):
        """日志类检查项的回显可以很长,其中出现报错字样不算命令执行失败。"""
        from patrol.cli import _is_command_error

        log = "\n".join(f"%SYS-5-CONFIG_I: line {i} Permission denied check"
                        for i in range(20))
        assert _is_command_error(log) is False
        assert _is_command_error("Error: Unrecognized command") is True
        assert _is_command_error("  \n") is False

    def test_real_output_is_still_judged(self):
        brief = (FIXTURES / "show_ip_interface_brief.txt").read_text(encoding="utf-8")
        report = _run(_asset(), {"show ip interface brief": brief})
        item = _item(report, "interface_status")
        assert item.status == CheckStatus.FAIL  # 样本 5 个接口里有 1 个 down
        assert item.details["abnormal_count"] == 1
        assert item.details["total"] == 5

    def test_collected_metric_is_judged(self):
        cpu = (FIXTURES / "show_cpu.txt").read_text(encoding="utf-8")
        report = _run(_asset(), {"show cpu": cpu})
        assert _item(report, "cpu_usage").status == CheckStatus.PASS


class TestCollectorSelection:
    @pytest.mark.parametrize("method", ["ssh", "telnet", "console"])
    def test_ssh_family_methods_use_netmiko_collector(self, method):
        assert isinstance(_create_collector(_asset(login_method=method)), SSHCollector)

    def test_unknown_method_rejected(self):
        with pytest.raises(ValueError):
            _create_collector(_asset(login_method="carrier-pigeon"))

    @pytest.mark.parametrize("method,port", [("telnet", 23), ("console", 9600)])
    def test_telnet_and_console_devices_reach_connection(self, method, port):
        """此前这两种登录方式在入口即报"不支持的采集方式",根本到不了连接。"""
        seen = []

        def fake_connect(self, asset):
            seen.append(asset.login_method)
            raise RuntimeError("stop-before-network")

        with patch.object(SSHCollector, "connect", fake_connect), \
                patch.object(SSHCollector, "disconnect"):
            report = run_inspection(
                _asset(login_method=method, port=port),
                RuijieRGOSSwitchDriver(), RuleEngine([]))
        assert seen == [method]
        assert report.error == "stop-before-network"


def _ok(asset: DeviceAsset) -> DeviceReport:
    return DeviceReport(asset=asset, check_items=[CheckItem(
        name="cpu_usage", category="CPU", command="c", raw_output="",
        status=CheckStatus.PASS, message="ok", details={"usage_percent": 10})])


def _fail(asset: DeviceAsset) -> DeviceReport:
    return DeviceReport(asset=asset, check_items=[CheckItem(
        name="cpu_usage", category="CPU", command="c", raw_output="",
        status=CheckStatus.FAIL, message="high",
        details={"usage_percent": 95, "severity": "critical"})])


def _err(asset: DeviceAsset) -> DeviceReport:
    return DeviceReport(asset=asset, error="连接超时")


class TestCliMain:
    """命令行入口:与界面共用设备库、接受 run 写法、退出码如实反映结果。"""

    @pytest.fixture
    def device_store(self):
        from patrol.storage.sqlstore import bootstrap
        dev, _, _, _ = bootstrap()
        for d in dev.list():  # 默认库在测试会话内共享,先清场
            dev.delete(d["name"])
        yield dev
        for d in dev.list():
            dev.delete(d["name"])

    def _device(self, name="命令行设备", enabled=True) -> dict:
        return {"name": name, "host": "192.0.2.10", "vendor": "h3c",
                "device_type": "comware_switch", "username": "u", "password": "p",
                "enabled": enabled}

    def _main(self, monkeypatch, argv, make_report, seen=None):
        def fake_inspection(asset, driver, engine, incremental=False):
            if seen is not None:
                seen.append(asset.name)
            return make_report(asset)

        def no_pdf(self, report, path):
            raise RuntimeError("测试环境不生成 PDF")

        monkeypatch.setattr("sys.argv", ["patrol", *argv])
        monkeypatch.setattr("patrol.cli.setup_logging", lambda *a, **k: None)
        monkeypatch.setattr("patrol.cli.run_inspection", fake_inspection)
        monkeypatch.setattr("patrol.reporter.pdf.PDFReporter.generate", no_pdf)
        try:
            cli.main()  # 正常结束时不调用 sys.exit,返回 None(进程退出码 0)
        except SystemExit as exc:
            return exc.code
        return None

    def test_reads_devices_from_shared_store_and_accepts_run(
            self, monkeypatch, device_store):
        device_store.create(self._device("命令行设备A"))
        device_store.create(self._device("停用设备", enabled=False))
        seen: list[str] = []
        assert self._main(monkeypatch, ["run"], _ok, seen) is None
        assert seen == ["命令行设备A"]  # 只巡检启用的设备

    @pytest.mark.parametrize("make_report,expected", [(_ok, None), (_fail, 2), (_err, 3)])
    def test_exit_codes(self, monkeypatch, device_store, make_report, expected):
        device_store.create(self._device())
        assert self._main(monkeypatch, [], make_report) == expected

    def test_unknown_positional_is_rejected(self, monkeypatch, capsys):
        assert self._main(monkeypatch, ["fly"], _ok) == 2
        assert "invalid choice" in capsys.readouterr().err
