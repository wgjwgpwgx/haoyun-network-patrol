"""LLM 客户端测试(httpx MockTransport,不出网)"""
from __future__ import annotations

import json

import httpx
import pytest

from patrol.ai.client import LLMClient, LLMError
from patrol.ai.config import AIConfig


def _cfg(**kw) -> AIConfig:
    return AIConfig(enabled=True, api_key="test-key", **kw)


def _ok_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": content}}]
    })


@pytest.fixture
def patch_client(monkeypatch):
    """把 LLMClient 内部的 httpx.Client 替换为带 MockTransport 的版本。"""
    def install(handler):
        transport = httpx.MockTransport(handler)
        real_client = httpx.Client

        def _factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        monkeypatch.setattr("patrol.ai.client.httpx.Client", _factory)
    return install


class TestChat:
    def test_success(self, patch_client):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["model"] == "deepseek-chat"
            assert request.headers["Authorization"] == "Bearer test-key"
            return _ok_response("你好")
        patch_client(handler)
        assert LLMClient(_cfg()).chat([{"role": "user", "content": "hi"}]) == "你好"

    def test_json_mode_payload(self, patch_client):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return _ok_response("{}")
        patch_client(handler)
        LLMClient(_cfg()).chat([{"role": "user", "content": "x"}], json_mode=True)
        assert seen["body"]["response_format"] == {"type": "json_object"}

    def test_json_mode_fallback_when_rejected(self, patch_client):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append("response_format" in body)
            if "response_format" in body:
                return httpx.Response(400, text="response_format not supported")
            return _ok_response('{"ok": 1}')
        patch_client(handler)
        out = LLMClient(_cfg()).chat(
            [{"role": "user", "content": "x"}], json_mode=True
        )
        assert out == '{"ok": 1}'
        assert calls == [True, False]  # 先带 response_format,失败后降级重试

    def test_http_error_raises(self, patch_client):
        patch_client(lambda r: httpx.Response(401, text="unauthorized"))
        with pytest.raises(LLMError, match="401"):
            LLMClient(_cfg()).chat([{"role": "user", "content": "x"}])

    def test_malformed_response_raises(self, patch_client):
        patch_client(lambda r: httpx.Response(200, json={"nope": 1}))
        with pytest.raises(LLMError, match="响应格式异常"):
            LLMClient(_cfg()).chat([{"role": "user", "content": "x"}])

    def test_empty_content_raises(self, patch_client):
        patch_client(lambda r: _ok_response("   "))
        with pytest.raises(LLMError, match="空内容"):
            LLMClient(_cfg()).chat([{"role": "user", "content": "x"}])
