"""深信服 NGAF Driver 测试 - 基于真实 API 响应和 Web DOM"""
from __future__ import annotations

from pathlib import Path

import pytest

from patrol.drivers.sangfor.driver import SangforNGAFDriver

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sangfor" / "ngaf_firewall"


@pytest.fixture
def driver() -> SangforNGAFDriver:
    return SangforNGAFDriver()


@pytest.fixture
def load():
    def _load(filename: str) -> str:
        return (FIXTURES / filename).read_text(encoding="utf-8")
    return _load


class TestDriverMetadata:
    def test_vendor(self, driver):
        assert driver.vendor == "sangfor"
    def test_device_type(self, driver):
        assert driver.device_type == "ngaf_firewall"
    def test_api_commands(self, driver):
        assert len(driver.get_check_commands()) == 6
    def test_web_commands(self, driver):
        assert len(driver.get_web_commands()) == 4
    def test_unknown_check(self, driver):
        r = driver.parse_output("nonexistent", "{}")
        assert r.success is False


# ── API 解析：正常 ──────────────────────────────────────────────


class TestAPIDeviceInfo:
    def test_normal(self, driver, load):
        r = driver.parse_output("device_info", load("api_device_info.json"))
        assert r.success is True
        d = r.parsed
        assert d["model"] == "NGAF-2020"
        assert d["software_version"] == "8.0.45"
        assert d["serial_number"] == "SF2020ABC12345"
        assert d["uptime"] == "120 days 5 hours"
        assert d["ha_status"] == "active"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", '{"code":0,"data":{}}')
        assert r.parsed["model"] == ""


class TestAPICpuUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("cpu_usage", load("api_cpu.json"))
        assert r.parsed["usage_percent"] == 26
        assert r.parsed["usage_10s"] == 25.6
        assert r.parsed["max_usage"] == 72.3

    def test_high(self, driver):
        r = driver.parse_output("cpu_usage", '{"code":0,"data":{"cpu_10s":92.1,"cpu_1min":88,"cpu_5min":85,"cpu_max":95}}')
        assert r.parsed["usage_percent"] == 92


class TestAPIMemoryUsage:
    def test_normal(self, driver, load):
        r = driver.parse_output("memory_usage", load("api_memory.json"))
        assert r.parsed["usage_percent"] == 42
        assert r.parsed["total_bytes"] == 8589934592

    def test_empty(self, driver):
        r = driver.parse_output("memory_usage", '{"code":0,"data":{}}')
        assert r.parsed["usage_percent"] is None


class TestAPIInterfaceStatus:
    def test_normal(self, driver, load):
        r = driver.parse_output("interface_status", load("api_interface.json"))
        d = r.parsed
        assert d["total"] == 4
        assert d["abnormal_count"] == 1
        assert "eth2" in d["abnormal_interfaces"]
        eth2 = next(i for i in d["interfaces"] if i["name"] == "eth2")
        assert eth2["in_errors"] == 5

    def test_all_up(self, driver):
        data = '{"code":0,"data":[{"if_name":"eth0","phy_status":"up","proto_status":"up","in_error":0,"out_error":0}]}'
        r = driver.parse_output("interface_status", data)
        assert r.parsed["abnormal_count"] == 0


class TestAPILogbuffer:
    def test_normal(self, driver, load):
        r = driver.parse_output("logbuffer", load("api_log.json"))
        assert r.parsed["total_lines"] == 3
        assert r.parsed["error_count"] == 1


# ── API 解析：边界和异常 ────────────────────────────────────────


class TestAPIEdgeCases:
    def test_invalid_json(self, driver):
        """无效 JSON 应返回空数据，不抛异常"""
        r = driver.parse_output("device_info", "not json at all")
        assert r.success is True
        assert r.parsed["model"] == ""

    def test_empty_string(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.success is True
        assert r.parsed["usage_percent"] is None

    def test_json_with_no_data_field(self, driver):
        """JSON 没有 data 字段"""
        r = driver.parse_output("cpu_usage", '{"code":0,"msg":"ok"}')
        assert r.success is True
        assert r.parsed["usage_percent"] is None

    def test_interface_data_is_dict(self, driver):
        """接口 data 是 dict 包含 interfaces 列表"""
        data = '{"code":0,"data":{"interfaces":[{"if_name":"eth0","phy_status":"up","proto_status":"up","in_error":0,"out_error":0}]}}'
        r = driver.parse_output("interface_status", data)
        assert r.parsed["total"] == 1

    def test_interface_data_is_list(self, driver):
        """接口 data 直接是 list"""
        data = '{"code":0,"data":[{"if_name":"eth0","phy_status":"up","proto_status":"up"}]}'
        r = driver.parse_output("interface_status", data)
        assert r.parsed["total"] == 1

    def test_interface_data_not_list(self, driver):
        """接口 data 是字符串，.get() 会抛异常 → 解析失败"""
        data = '{"code":0,"data":"unexpected"}'
        r = driver.parse_output("interface_status", data)
        # string 没有 .get() 方法，解析器抛异常 → driver 返回 success=False
        assert r.success is False

    def test_routing_with_dict_data(self, driver):
        """路由 data 是 dict 包含 routes 列表"""
        data = '{"code":0,"data":{"routes":[{"dest":"0.0.0.0/0"}]}}'
        r = driver.parse_output("routing_table", data)
        assert r.parsed["routes"] == 1

    def test_routing_with_list_data(self, driver):
        """路由 data 直接是 list"""
        data = '{"code":0,"data":[{"dest":"0.0.0.0/0"}]}'
        r = driver.parse_output("routing_table", data)
        assert r.parsed["routes"] == 1

    def test_routing_data_not_list(self, driver):
        """路由 data 是字符串 → 解析失败"""
        data = '{"code":0,"data":"unexpected"}'
        r = driver.parse_output("routing_table", data)
        assert r.success is False

    def test_log_with_dict_data(self, driver):
        """日志 data 是 dict 包含 logs 列表"""
        data = '{"code":0,"data":{"logs":[{"level":"error","message":"test"}]}}'
        r = driver.parse_output("logbuffer", data)
        assert r.parsed["total_lines"] == 1

    def test_log_data_not_list(self, driver):
        """日志 data 是字符串 → 解析失败"""
        data = '{"code":0,"data":"unexpected"}'
        r = driver.parse_output("logbuffer", data)
        assert r.success is False


# ── Web 解析：正常 ──────────────────────────────────────────────


class TestWebDeviceInfo:
    def test_with_selectors(self, driver):
        html = '''
        <div class="device-model"><span class="value">NGAF-3000</span></div>
        <div class="firmware-version"><span class="value">8.0.50</span></div>
        <div class="sn-code"><span class="value">SF3000XYZ789</span></div>
        <div class="uptime"><span class="value">60 days</span></div>
        '''
        r = driver.parse_output("device_info", html)
        assert r.parsed["model"] == "NGAF-3000"
        assert r.parsed["software_version"] == "8.0.50"
        assert r.parsed["serial_number"] == "SF3000XYZ789"

    def test_empty(self, driver):
        r = driver.parse_output("device_info", "")
        assert r.parsed["model"] == ""


class TestWebCpuUsage:
    def test_with_selectors(self, driver):
        html = '''
        <div class="cpu-10s-rate"><span class="value">35.2%</span></div>
        <div class="cpu-1min-rate"><span class="value">30.1%</span></div>
        <div class="cpu-5min-rate"><span class="value">28.5%</span></div>
        '''
        r = driver.parse_output("cpu_usage", html)
        assert r.parsed["usage_percent"] == 35
        assert r.parsed["usage_10s"] == 35.2

    def test_empty(self, driver):
        r = driver.parse_output("cpu_usage", "")
        assert r.parsed["usage_percent"] is None


class TestWebMemoryUsage:
    def test_with_selectors(self, driver):
        html = '''
        <div class="memory-used-rate"><span class="value">68%</span></div>
        <div class="memory-total"><span class="value">8589934592</span></div>
        <div class="memory-used"><span class="value">5841453056</span></div>
        '''
        r = driver.parse_output("memory_usage", html)
        assert r.parsed["usage_percent"] == 68
        assert r.parsed["total_bytes"] == 8589934592


# ── Web 解析：边界和异常 ────────────────────────────────────────


class TestWebEdgeCases:
    def test_single_level_selector(self, driver):
        """单级 CSS 选择器匹配"""
        from patrol.drivers.sangfor.parsers_web import _extract_value_by_selector
        html = '<div class="device-model">TestModel</div>'
        result = _extract_value_by_selector(html, ".device-model")
        assert result == "TestModel"

    def test_selector_not_found(self, driver):
        """选择器未匹配"""
        from patrol.drivers.sangfor.parsers_web import _extract_value_by_selector
        result = _extract_value_by_selector("<div>no class</div>", ".missing")
        assert result is None

    def test_parse_number_none(self, driver):
        """_parse_number 接收 None"""
        from patrol.drivers.sangfor.parsers_web import _parse_number
        assert _parse_number(None) is None

    def test_parse_number_integer(self, driver):
        """_parse_number 解析整数"""
        from patrol.drivers.sangfor.parsers_web import _parse_number
        assert _parse_number("42") == 42

    def test_parse_number_float(self, driver):
        """_parse_number 解析浮点数"""
        from patrol.drivers.sangfor.parsers_web import _parse_number
        assert _parse_number("35.2%") == 35.2

    def test_parse_number_no_digits(self, driver):
        """_parse_number 无数字"""
        from patrol.drivers.sangfor.parsers_web import _parse_number
        assert _parse_number("abc") is None

    def test_interface_with_matching_lines(self, driver):
        """接口解析器匹配 up/down 行"""
        text = "eth0 up\neth1 down\neth2 up\n"
        r = driver.parse_output("interface_status", text)
        assert r.parsed["total"] == 3
        assert r.parsed["abnormal_count"] == 1
        assert "eth1" in r.parsed["abnormal_interfaces"]

    def test_interface_all_down(self, driver):
        text = "eth0 down\neth1 offline\n"
        r = driver.parse_output("interface_status", text)
        assert r.parsed["abnormal_count"] == 2

    def test_interface_no_matches(self, driver):
        text = "no interface data here"
        r = driver.parse_output("interface_status", text)
        assert r.parsed["total"] == 0
