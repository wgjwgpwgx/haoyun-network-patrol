"""API 采集器 - 基于 requests

职责：
  通过 REST API 采集设备数据。

当前支持：
  - 深信服 NGAF WebAPI（v8.0.35+，基于 token 鉴权）

设计约束：
  - Token 不出现在日志中
  - HTTPS 证书校验默认开启（问题 006）；自签名证书在设备配置 verify_ssl: false 跳过
  - 超时可配置
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from patrol.collector.base import BaseCollector
from patrol.models import DeviceAsset

logger = logging.getLogger(__name__)

# 禁用 SSL 警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class APIConnectionError(Exception):
    """API 连接失败"""


class APIAuthenticationError(Exception):
    """API 认证失败"""


class APIRequestError(Exception):
    """API 请求失败"""


# 厂商 API 配置
_API_PROFILES: dict[str, dict[str, Any]] = {
    "sangfor": {
        "login_path": "/api/v1/auth/login",
        "token_header": "Authorization",
        "token_prefix": "Bearer ",
    },
}


class APICollector(BaseCollector):
    """基于 requests 的 API 采集器"""

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._token: str = ""
        self._base_url: str = ""
        self._asset: DeviceAsset | None = None

    def connect(self, asset: DeviceAsset) -> None:
        """通过 API 登录获取 Token。

        Raises:
            APIAuthenticationError: 认证失败
            APIConnectionError: 连接失败
        """
        self._asset = asset
        self._base_url = f"{asset.web_protocol}://{asset.host}:{asset.web_port}"

        profile = _API_PROFILES.get(asset.vendor)
        if not profile:
            raise APIConnectionError(
                f"不支持的 API 厂商: {asset.vendor}，"
                f"已支持: {list(_API_PROFILES.keys())}"
            )

        self._session = requests.Session()
        # 问题 006:证书校验跟随设备配置(默认开启);自签名证书可 verify_ssl=false 跳过
        self._session.verify = asset.verify_ssl

        # 如果已有 Token，直接使用
        if asset.api_token:
            self._token = asset.api_token
            self._session.headers[profile["token_header"]] = (
                profile["token_prefix"] + self._token
            )
            logger.info("API 使用预配置 Token: %s", asset.host)
            return

        # 登录获取 Token
        login_url = self._base_url + profile["login_path"]
        logger.info("API 登录: %s", login_url)

        try:
            resp = self._session.post(
                login_url,
                json={"username": asset.username, "password": asset.password},
                timeout=asset.timeout,
            )
            if resp.status_code == 401:
                raise APIAuthenticationError(f"API 认证失败 {asset.host}")
            resp.raise_for_status()

            data = resp.json()
            # 深信服 NGAF 返回格式：{"code": 0, "data": {"token": "..."}}
            self._token = data.get("data", {}).get("token", "") or data.get("token", "")
            if not self._token:
                raise APIAuthenticationError(
                    f"API 登录成功但未获取到 Token: {asset.host}"
                )

            self._session.headers[profile["token_header"]] = (
                profile["token_prefix"] + self._token
            )
            logger.info("API 登录成功: %s", asset.host)

        except APIAuthenticationError:
            raise
        except requests.exceptions.SSLError as e:
            logger.error("API 证书校验失败 %s: %s", asset.host, e)
            raise APIConnectionError(
                f"HTTPS 证书校验失败 {asset.host}: 如设备使用自签名证书，"
                f"请在设备编辑中勾选「跳过 HTTPS 证书校验」"
            ) from e
        except requests.RequestException as e:
            logger.error("API 连接失败 %s: %s", asset.host, e)
            raise APIConnectionError(f"API 连接失败 {asset.host}: {e}") from e

    def execute(self, path: str, timeout: int = 30) -> str:
        """调用 API 端点，返回 JSON 字符串。

        Args:
            path: API 路径，如 /api/v1/system/info
            timeout: 请求超时（秒）

        Returns:
            JSON 字符串
        """
        if not self._session or not self._asset:
            raise APIRequestError("API 未连接")

        url = self._base_url + path
        logger.debug("[API] GET %s", url)

        try:
            resp = self._session.get(url, timeout=timeout)
            resp.raise_for_status()
            text = resp.text
            logger.debug("[API] 响应: %d 字符", len(text))
            return text
        except requests.RequestException as e:
            logger.error("[API] 请求失败 %s: %s", url, e)
            raise APIRequestError(f"API 请求失败 {url}: {e}") from e

    def disconnect(self) -> None:
        """关闭会话。"""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        if self._asset:
            logger.info("API 连接已断开: %s", self._asset.host)
