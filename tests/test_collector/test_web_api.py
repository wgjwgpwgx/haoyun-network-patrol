"""采集器测试（Web / API）- 使用 mock"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from patrol.collector.web import WebCollector, WebAuthenticationError, WebConnectionError
from patrol.collector.api import APICollector, APIAuthenticationError, APIConnectionError
from patrol.models import DeviceAsset


@pytest.fixture
def ssh_asset() -> DeviceAsset:
    return DeviceAsset(name="sw1", host="10.0.0.1", login_method="ssh",
                       username="admin", password="pw")


@pytest.fixture
def web_asset() -> DeviceAsset:
    return DeviceAsset(name="fw1", host="10.0.0.2", vendor="sangfor",
                       device_type="ngaf_firewall", login_method="web",
                       web_port=443, web_protocol="https",
                       username="admin", password="pw", screenshot=False)


@pytest.fixture
def dptech_asset() -> DeviceAsset:
    return DeviceAsset(name="fw2", host="10.0.0.3", vendor="dptech",
                       device_type="fw_firewall", login_method="web",
                       web_port=8443, web_protocol="https",
                       username="admin", password="pw", screenshot=False)


@pytest.fixture
def api_asset() -> DeviceAsset:
    return DeviceAsset(name="fw3", host="10.0.0.4", vendor="sangfor",
                       device_type="ngaf_firewall", login_method="api",
                       web_port=443, web_protocol="https",
                       username="admin", password="pw", api_token="")


# ── Web Collector ──────────────────────────────────────────────


class TestWebCollector:
    def test_unsupported_vendor(self):
        collector = WebCollector()
        asset = DeviceAsset(name="x", host="10.0.0.1", vendor="unknown",
                            login_method="web", username="a", password="b")
        with pytest.raises(WebConnectionError, match="不支持"):
            collector.connect(asset)

    def test_disconnect_without_connect(self):
        collector = WebCollector()
        collector.disconnect()  # 不应抛异常

    def test_execute_without_connect(self):
        collector = WebCollector()
        with pytest.raises(Exception):
            collector.execute("/test")


class TestWebLoginProfiles:
    def test_sangfor_profile_exists(self):
        from patrol.collector.web import _LOGIN_PROFILES
        assert "sangfor" in _LOGIN_PROFILES
        assert _LOGIN_PROFILES["sangfor"]["login_path"] == "/login"
        assert _LOGIN_PROFILES["sangfor"]["username_selector"] == 'input[name="username"]'
        assert _LOGIN_PROFILES["sangfor"]["password_selector"] == 'input[name="password"]'
        assert _LOGIN_PROFILES["sangfor"]["verifycode_selector"] == 'input[name="verifycode"]'

    def test_dptech_profile_exists(self):
        from patrol.collector.web import _LOGIN_PROFILES
        assert "dptech" in _LOGIN_PROFILES
        assert _LOGIN_PROFILES["dptech"]["login_path"] == "/login.html"
        assert _LOGIN_PROFILES["dptech"]["username_selector"] == 'input[name="user"]'
        assert _LOGIN_PROFILES["dptech"]["password_selector"] == 'input[name="pass"]'
        assert _LOGIN_PROFILES["dptech"]["verifycode_selector"] is None


# ── API Collector ──────────────────────────────────────────────


class TestAPICollector:
    def test_unsupported_vendor(self):
        collector = APICollector()
        asset = DeviceAsset(name="x", host="10.0.0.1", vendor="unknown",
                            login_method="api", username="a", password="b")
        with pytest.raises(APIConnectionError, match="不支持"):
            collector.connect(asset)

    def test_disconnect_without_connect(self):
        collector = APICollector()
        collector.disconnect()

    def test_execute_without_connect(self):
        collector = APICollector()
        with pytest.raises(Exception):
            collector.execute("/api/test")


class TestAPILoginProfiles:
    def test_sangfor_api_profile_exists(self):
        from patrol.collector.api import _API_PROFILES
        assert "sangfor" in _API_PROFILES
        assert _API_PROFILES["sangfor"]["login_path"] == "/api/v1/auth/login"


# ── CLI Collector 选择 ─────────────────────────────────────────


class TestCollectorSelection:
    def test_ssh_collector(self):
        from patrol.cli import _create_collector
        from patrol.collector.ssh import SSHCollector
        asset = DeviceAsset(name="sw", host="10.0.0.1", login_method="ssh",
                            username="a", password="b")
        assert isinstance(_create_collector(asset), SSHCollector)

    def test_web_collector(self):
        from patrol.cli import _create_collector
        from patrol.collector.web import WebCollector
        asset = DeviceAsset(name="fw", host="10.0.0.1", login_method="web",
                            vendor="sangfor", username="a", password="b")
        assert isinstance(_create_collector(asset), WebCollector)

    def test_api_collector(self):
        from patrol.cli import _create_collector
        from patrol.collector.api import APICollector
        asset = DeviceAsset(name="fw", host="10.0.0.1", login_method="api",
                            vendor="sangfor", username="a", password="b")
        assert isinstance(_create_collector(asset), APICollector)

    def test_unknown_method(self):
        from patrol.cli import _create_collector
        asset = DeviceAsset(name="x", host="10.0.0.1",
                            login_method="carrier_pigeon",
                            username="a", password="b")
        with pytest.raises(ValueError, match="不支持"):
            _create_collector(asset)


# ── DeviceAsset 新字段 ─────────────────────────────────────────


class TestDeviceAssetWebFields:
    def test_default_values(self):
        asset = DeviceAsset(name="sw", host="10.0.0.1", username="a", password="b")
        assert asset.login_method == "ssh"
        assert asset.web_port == 443
        assert asset.web_protocol == "https"
        assert asset.api_token == ""
        assert asset.screenshot is True

    def test_web_asset(self):
        asset = DeviceAsset(name="fw", host="10.0.0.1", vendor="sangfor",
                            login_method="web", web_port=4433,
                            web_protocol="https", username="a", password="b",
                            screenshot=False)
        assert asset.login_method == "web"
        assert asset.web_port == 4433
        assert asset.screenshot is False

    def test_api_asset(self):
        asset = DeviceAsset(name="fw", host="10.0.0.1", vendor="sangfor",
                            login_method="api", api_token="abc123",
                            username="a", password="b")
        assert asset.api_token == "abc123"
