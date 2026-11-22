"""资源清理回归测试(H6)

背景缺陷:run_inspection 中 disconnect() 不在 try/finally,规则引擎
中途抛异常会跳过断开,导致 SSH 会话泄漏;Web 采集器的 Playwright
进程异常路径不清理。
"""
from __future__ import annotations

from patrol.analyzer.engine import Rule, RuleEngine
from patrol.cli import run_inspection
from patrol.collector.web import WebCollector
from patrol.drivers.base import ParsedResult
from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
from patrol.models import DeviceAsset


class RecordingCollector:
    """记录 disconnect 调用的假采集器。"""

    def __init__(self, fail_command: str | None = None) -> None:
        self.disconnected = False
        self.commands: list[str] = []
        self.fail_command = fail_command

    def connect(self, asset) -> None:
        pass

    def execute(self, command: str, timeout: int = 60) -> str:
        self.commands.append(command)
        return "fake output"

    def disconnect(self) -> None:
        self.disconnected = True


class PoisonedDriver(HuaweiVRPSwitchDriver):
    """解析结果携带非数值指标的数据源驱动。

    注:问题 010 修复后引擎对非数值指标返回 UNKNOWN 不再崩溃,
    "引擎抛异常"场景由测试显式注入,不再依赖该崩溃。
    """

    def parse_output(self, name: str, raw_output: str) -> ParsedResult:
        return ParsedResult(
            name=name, category="测试", command=raw_output,
            raw_output=raw_output,
            parsed={"usage_percent": "not-a-number"},
            success=True,
        )


class TestDisconnectGuarantee:
    def test_disconnect_called_when_engine_raises(self, monkeypatch):
        """H6 回归:引擎中途抛异常时仍必须断开连接。"""
        asset = DeviceAsset(
            name="泄漏测试", host="192.0.2.1", vendor="huawei",
            device_type="vrp_switch", username="u", password="p",
        )
        engine = RuleEngine([Rule(
            id="T001", name="CPU 过高", description="测试规则",
            severity="warning", vendors=["*"], device_types=["*"],
            check_name="cpu_usage", metric="usage_percent",
            operator="gt", value=80, suggestion="",
        )])
        collector = RecordingCollector()

        monkeypatch.setattr(
            "patrol.cli._create_collector", lambda asset: collector
        )

        # 问题 010 修复后引擎不再因非数值崩溃;显式注入异常验证 H6 断连保证
        def _boom(rule, parsed):
            raise ValueError("引擎内部异常(测试注入)")

        monkeypatch.setattr(engine, "_evaluate_rule", _boom)

        import pytest
        with pytest.raises(ValueError):
            run_inspection(asset, PoisonedDriver(), engine)

        assert collector.disconnected is True, "异常路径未断开连接(资源泄漏)"

    def test_disconnect_called_on_happy_path(self, monkeypatch):
        asset = DeviceAsset(
            name="正常测试", host="192.0.2.1", vendor="huawei",
            device_type="vrp_switch", username="u", password="p",
        )
        engine = RuleEngine([])
        collector = RecordingCollector()
        monkeypatch.setattr(
            "patrol.cli._create_collector", lambda asset: collector
        )
        run_inspection(asset, HuaweiVRPSwitchDriver(), engine)
        assert collector.disconnected is True


class TestWebCollectorCleanup:
    def test_cleanup_closes_everything(self):
        """_cleanup 应关闭 context/browser 并 stop Playwright,且幂等。"""
        wc = WebCollector()
        closed = []

        class FakeHandle:
            def __init__(self, tag): self.tag = tag
            def close(self): closed.append(self.tag)
            def stop(self): closed.append(self.tag + ":stop")

        wc._context = FakeHandle("context")
        wc._browser = FakeHandle("browser")
        wc._pw = FakeHandle("pw")

        wc._cleanup()
        assert closed == ["context", "browser", "pw:stop"]
        assert wc._page is None and wc._context is None
        assert wc._browser is None and wc._pw is None

        wc._cleanup()  # 幂等:二次调用不抛异常
        assert closed == ["context", "browser", "pw:stop"]

    def test_disconnect_uses_cleanup(self):
        wc = WebCollector()
        closed = []

        class FakeHandle:
            def close(self): closed.append("x")
            def stop(self): closed.append("s")

        wc._context = FakeHandle()
        wc._browser = FakeHandle()
        wc._pw = FakeHandle()
        from patrol.models import DeviceAsset
        wc._asset = DeviceAsset(name="t", host="192.0.2.1")

        wc.disconnect()
        assert "s" in closed, "disconnect 未停止 Playwright 进程"
        assert wc._pw is None
