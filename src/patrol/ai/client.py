"""OpenAI 兼容 Chat Completions 客户端

轻量实现(httpx 直调),不引入 openai SDK 依赖。
兼容 DeepSeek / 智谱 GLM / 通义千问 / Kimi / Ollama 等 OpenAI 协议服务。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from patrol.ai.config import AIConfig

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败(网络/鉴权/限流/响应异常)。"""


class LLMClient:
    """最小 Chat Completions 客户端"""

    def __init__(self, config: AIConfig) -> None:
        self._config = config

    def chat(self, messages: list[dict], json_mode: bool = False) -> str:
        """调用对话接口,返回首个回复的文本内容。

        json_mode=True 时请求 JSON 输出(服务端不支持时自动降级重试一次)。
        """
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            content = self._post(payload)
        except LLMError:
            # 部分 OpenAI 兼容服务不支持 response_format,去掉后重试一次
            if json_mode:
                payload.pop("response_format", None)
                content = self._post(payload)
            else:
                raise
        return content

    def _post(self, payload: dict) -> str:
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._config.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"请求 LLM 服务失败: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"LLM 服务返回 {resp.status_code}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"LLM 响应格式异常: {e}") from e

        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM 返回了空内容")
        return content
