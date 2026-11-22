"""API 采集器 HTTPS 证书校验测试(问题 006:verify=False → 设备级 verify_ssl)"""
from __future__ import annotations

import pytest
import requests

from patrol.api.schemas import DeviceCreate, DeviceUpdate
from patrol.collector.api import APICollector, APIConnectionError
from patrol.models import DeviceAsset


def _asset(**kw) -> DeviceAsset:
    base = dict(
        name="ngaf", host="10.1.1.1", vendor="sangfor",
        device_type="ngaf_firewall", login_method="api",
        username="admin", password="pw",
    )
    base.update(kw)
    return DeviceAsset(**base)


class _FakeResp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"code": 0, "data": {"token": "tok123"}}

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self):
        self.verify = True
        self.headers: dict = {}

    def post(self, *a, **kw):
        return _FakeResp()

    def get(self, *a, **kw):
        return _FakeResp()


class TestVerifySslDefault:
    def test_asset_default_verify_on(self):
        assert _asset().verify_ssl is True

    def test_schema_defaults(self):
        c = DeviceCreate(
            name="x", host="10.0.0.1", username="u", password="p"
        )
        assert c.verify_ssl is True
        assert DeviceUpdate().verify_ssl is None


class TestSessionVerify:
    def test_session_verify_follows_asset(self, monkeypatch):
        monkeypatch.setattr("patrol.collector.api.requests.Session", _FakeSession)
        col = APICollector()
        col.connect(_asset(verify_ssl=True))
        assert col._session.verify is True

        col2 = APICollector()
        col2.connect(_asset(verify_ssl=False))
        assert col2._session.verify is False

    def test_ssl_error_maps_to_friendly_hint(self, monkeypatch):
        class _FailSession(_FakeSession):
            def post(self, *a, **kw):
                raise requests.exceptions.SSLError("self signed certificate")

        monkeypatch.setattr("patrol.collector.api.requests.Session", _FailSession)
        col = APICollector()
        with pytest.raises(APIConnectionError, match="自签名"):
            col.connect(_asset())
