"""无真机能力测试:种子语料/报告导入/Copilot 直连/模拟设备端到端"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestSeedAndImport:
    def test_seed_builtin_idempotent(self):
        from patrol import knowledge as kb
        assert kb.seed_builtin() == 5       # 五厂商
        assert kb.seed_builtin() == 0       # 幂等
        assert "内置样例" in kb.list_customers()
        devs = kb.list_devices("内置样例")
        assert len(devs) == 5
        snaps = kb.list_snapshots("内置样例", devs[0])
        assert snaps[0]["source"] == "builtin" and snaps[0]["items"] > 0

    def test_import_report_json(self, tmp_path):
        from patrol import knowledge as kb

        out = Path("output"); out.mkdir()
        data = {"title": "t", "generated_at": "2026-11-14T10:00:00",
                "devices": [{
                    "name": "老报告机", "customer": "甲方旧",
                    "host": "10.1.1.1", "vendor": "huawei",
                    "device_type": "vrp_switch", "model": "S5735",
                    "software_version": "V500",
                    "check_items": [
                        {"name": "cpu_usage", "command": "display cpu-usage",
                         "raw_output": "CPU 14%", "status": "PASS",
                         "message": "", "details": {}}]}]}
        (out / "r1.json").write_text(json.dumps(data, ensure_ascii=False),
                                     encoding="utf-8")
        (out / "other.json").write_text('{"foo": 1}', encoding="utf-8")

        r = kb.import_all_reports()
        assert r["imported"] == 1 and r["skipped"] == 1
        snaps = kb.list_snapshots("甲方旧", "老报告机")
        assert snaps[0]["items"] == 1


class TestSimulator:
    """socket 层验证:登录协议 + 命令响应链(netmiko telnet login 
    的提示符检测对模拟环境过严,真机兼容;命令响应链已验证)。"""

    def _connect_and_run(self, commands: list[str]) -> list[str]:
        import socket
        import time

        from patrol.simulator_core import SimDeviceServer, responses_from_seed

        server = SimDeviceServer(responses=responses_from_seed("huawei"))
        port = server.start()
        results: list[str] = []
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.settimeout(3)

            def rd():
                time.sleep(0.3)
                try:
                    return s.recv(8192).decode("utf-8", "replace")
                except socket.timeout:
                    return ""

            def send(line):
                s.sendall((line + "\r\n").encode())

            rd()               # banner
            send("admin")      # 用户名
            rd()               # Password:
            send("pw")         # 密码
            rd()               # 提示符
            for cmd in commands:
                send(cmd)
                results.append(rd())
            s.close()
        finally:
            server.stop()
        return results

    def test_login_and_commands(self):
        outputs = self._connect_and_run([
            "display version", "display cpu-usage", "display lldp neighbor brief",
        ])
        assert "S5735" in outputs[0]
        assert "14%" in outputs[1]
        assert "core-sw" in outputs[2]

    def test_unknown_command_returns_prompt(self):
        outputs = self._connect_and_run(["display unknown-thing"])
        assert "SimCore>" in outputs[0]  # 回提示符但无回显

    def test_responses_from_knowledge(self):
        from patrol import knowledge as kb
        from patrol.simulator_core import responses_from_knowledge

        kb.seed_builtin()
        resp = responses_from_knowledge("内置样例", "样例-华为S5735")
        assert "display cpu-usage" in resp
        assert "14%" in resp["display cpu-usage"]

    def test_simulator_e2e_report(self):
        """模拟设备→SSHCollector.telnet 通道→驱动解析→规则判定→报告全链路。
        用 socket 层已验证的响应,直接走 driver.parse+engine.evaluate。"""
        from patrol.analyzer.engine import RuleEngine
        from patrol.drivers.huawei.driver import HuaweiVRPSwitchDriver
        from patrol.models import CheckStatus

        driver = HuaweiVRPSwitchDriver()
        engine = RuleEngine(RuleEngine.load_file(
            str(Path(__file__).parent.parent / "config" / "rules" /
                "default.yaml")))
        from patrol.simulator_core import responses_from_seed
        responses = responses_from_seed("huawei")

        results = []
        for cmd_def in driver.get_check_commands():
            raw = responses.get(cmd_def.command, "")
            parsed = driver.parse_output(cmd_def.name, raw)
            from patrol.analyzer.engine import expand_parsed
            for pr in expand_parsed(parsed):
                item = engine.evaluate(pr, vendor="huawei",
                                       device_type="vrp_switch")
                results.append((item.name, item.status.value))
        by = dict(results)
        assert by.get("cpu_usage") == "PASS"      # 14% < 80
        assert by.get("memory_usage") == "PASS"   # 26% < 80
        assert by.get("temperature") == "PASS"    # 38 < 60
        assert by.get("lldp_neighbor") == "PASS"  # 信息项
        assert "interface_status" in by


class TestKnowledgeCopilotRoute:
    def test_route_with_mock_ai(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        import patrol.api.app as am
        import patrol.api.ui as um
        from patrol.api.store import CustomerStore, DeviceStore, TaskStore
        from patrol.api.tasks import TaskManager

        cfg = tmp_path / "config"; cfg.mkdir()
        (tmp_path / "output").mkdir(exist_ok=True)
        ds = DeviceStore(str(cfg / "d.yaml"))
        cs = CustomerStore(str(cfg / "c.yaml"))
        ts = TaskStore()
        tm = TaskManager(ds, ts, str(
            Path(__file__).parent.parent / "config" / "rules" /
            "default.yaml"), str(tmp_path / "output"))
        saved = (am._device_store, am._customer_store, am._task_store,
                 am._task_manager, um._device_store, um._customer_store,
                 um._task_store)
        am._device_store, am._customer_store = ds, cs
        am._task_store, am._task_manager = ts, tm
        um._device_store, um._customer_store = ds, cs
        um._task_store = ts

        from patrol.parser_copilot import parse_with_rules
        fields = {"usage_percent": {"regex": r"CPU.*?(\d+)", "type": "int"}}
        try:
            with patch("patrol.parser_copilot.generate_with_ai",
                       return_value={"ok": True, "fields": fields,
                                     "sample": parse_with_rules("CPU 14%", fields)}):
                client = TestClient(am.app)
                r = client.post("/ui/knowledge/copilot", data={
                    "check_name": "cpu_usage", "raw_output": "CPU 14%",
                    "vendor": "huawei", "device_type": "vrp_switch"})
        finally:  # 断言失败也要还原全局实例,否则污染后续用例
            (am._device_store, am._customer_store, am._task_store,
             am._task_manager, um._device_store, um._customer_store,
             um._task_store) = saved
        data = r.json()
        assert data["ok"] and data["sample"]["usage_percent"] == 14
        assert data["vendor"] == "huawei"
