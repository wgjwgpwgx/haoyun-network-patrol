"""Web 采集器 - 基于 Playwright

职责：
  通过浏览器访问设备 Web 管理页面，登录后采集数据并截图留证。

支持：
  - HTTPS 自签名证书（ignore_https_errors=True）
  - 深信服 NGAF 登录页（/login）
  - 迪普 DPtech 登录页（/login.html）
  - 验证码检测（开启验证码时返回错误提示）
  - 截图留证（保存到 output/screenshots/）
  - 会话保持（Cookie 自动管理）

设计约束：
  - 密码不出现在日志中
  - 截图自动保存，文件名含设备名和时间戳
  - 页面加载超时可配置
  - 登录失败和页面加载失败抛出不同异常
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from patrol.collector.base import BaseCollector
from patrol.models import DeviceAsset

logger = logging.getLogger(__name__)


class WebConnectionError(Exception):
    """Web 连接失败（网络不通、页面无法加载）"""


class WebAuthenticationError(Exception):
    """Web 认证失败（用户名/密码错误、验证码）"""


class WebPageError(Exception):
    """页面操作失败（元素找不到、页面超时）"""


# 各厂商的登录页配置
_LOGIN_PROFILES: dict[str, dict[str, Any]] = {
    "sangfor": {
        "login_path": "/login",
        "username_selector": 'input[name="username"]',
        "password_selector": 'input[name="password"]',
        "verifycode_selector": 'input[name="verifycode"]',
        "submit_selector": 'button[type="submit"], .login-btn, input[type="submit"]',
        "success_indicator": '.sidebar, .main-container, nav, [class*="menu"]',
    },
    "dptech": {
        "login_path": "/login.html",
        "username_selector": 'input[name="user"]',
        "password_selector": 'input[name="pass"]',
        "verifycode_selector": None,
        "submit_selector": 'input[type="submit"], button[type="submit"], .login-btn',
        "success_indicator": 'frame, iframe, .main, #main',
    },
}


class WebCollector(BaseCollector):
    """基于 Playwright 的 Web 采集器"""

    def __init__(self) -> None:
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._pw: Any = None
        self._asset: DeviceAsset | None = None
        self._screenshot_dir = Path("output/screenshots")

    def _cleanup(self) -> None:
        """关闭浏览器与 Playwright 进程(幂等,异常路径与正常断开共用)。"""
        for closer in (
            lambda: self._context.close(),
            lambda: self._browser.close(),
            lambda: self._pw.stop(),
        ):
            try:
                closer()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None

    def connect(self, asset: DeviceAsset) -> None:
        """打开浏览器并登录设备 Web 管理界面。

        Raises:
            WebAuthenticationError: 登录失败
            WebConnectionError: 页面无法加载
        """
        from playwright.sync_api import sync_playwright

        self._asset = asset
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        profile = _LOGIN_PROFILES.get(asset.vendor)
        if not profile:
            raise WebConnectionError(
                f"不支持的 Web 登录厂商: {asset.vendor}，"
                f"已支持: {list(_LOGIN_PROFILES.keys())}"
            )

        base_url = f"{asset.web_protocol}://{asset.host}:{asset.web_port}"
        login_url = base_url + profile["login_path"]

        logger.info("Web 连接 %s (vendor=%s)", base_url, asset.vendor)

        try:
            pw = sync_playwright().start()
            self._pw = pw
            self._browser = pw.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                ignore_https_errors=True,
                viewport={"width": 1920, "height": 1080},
            )
            self._page = self._context.new_page()
            self._page.set_default_timeout(asset.timeout * 1000)

            # 访问登录页
            logger.info("访问登录页: %s", login_url)
            self._page.goto(login_url, wait_until="networkidle")

            # 检查是否有验证码
            if profile["verifycode_selector"]:
                verify_el = self._page.query_selector(profile["verifycode_selector"])
                if verify_el and verify_el.is_visible():
                    raise WebAuthenticationError(
                        f"设备 {asset.name} 启用了验证码，请先在设备上关闭验证码后重试"
                    )

            # 填写用户名密码
            self._page.fill(profile["username_selector"], asset.username)
            self._page.fill(profile["password_selector"], asset.password)

            # 点击登录
            self._page.click(profile["submit_selector"])
            self._page.wait_for_load_state("networkidle")

            # 检查是否登录成功（等待页面跳转或加载主界面）
            try:
                self._page.wait_for_selector(
                    profile["success_indicator"], timeout=10000
                )
            except Exception:
                # 截图记录失败状态
                self._take_screenshot("login_failed")
                raise WebAuthenticationError(
                    f"Web 登录失败 {asset.host}: 登录后未检测到主界面"
                )

            logger.info("Web 登录成功: %s", asset.host)

        except WebAuthenticationError:
            self._cleanup()
            raise
        except Exception as e:
            self._cleanup()
            logger.error("Web 连接失败 %s: %s", asset.host, e)
            raise WebConnectionError(f"Web 连接失败 {asset.host}: {e}") from e

    def execute(self, path: str, timeout: int = 30) -> str:
        """访问指定路径并返回页面文本内容。

        Args:
            path: 页面路径，如 /#/system/overview 或 /system/system_info.html
            timeout: 页面加载超时（秒）

        Returns:
            页面的文本内容

        Raises:
            WebPageError: 页面加载失败
        """
        if not self._page or not self._asset:
            raise WebPageError("Web 未连接")

        base_url = f"{self._asset.web_protocol}://{self._asset.host}:{self._asset.web_port}"
        url = base_url + path

        logger.debug("[Web] 访问: %s", url)
        try:
            self._page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            # 等待页面渲染
            self._page.wait_for_load_state("domcontentloaded")

            # 获取页面文本
            text = self._page.inner_text("body")
            logger.debug("[Web] 页面文本: %d 字符", len(text))
            return text

        except Exception as e:
            logger.error("[Web] 页面加载失败 %s: %s", url, e)
            raise WebPageError(f"页面加载失败 {url}: {e}") from e

    def execute_js(self, js_code: str, timeout: int = 30) -> Any:
        """在页面中执行 JavaScript 并返回结果。

        用于从 SPA 应用中提取数据（如深信服 NGAF 的 Vue 应用）。
        """
        if not self._page:
            raise WebPageError("Web 未连接")

        try:
            result = self._page.evaluate(js_code)
            return result
        except Exception as e:
            logger.error("[Web] JS 执行失败: %s", e)
            raise WebPageError(f"JS 执行失败: {e}") from e

    def take_screenshot(self, name: str) -> Path:
        """手动截图，返回文件路径。"""
        return self._take_screenshot(name)

    def navigate_and_screenshot(self, path: str, label: str, timeout: int = 30) -> tuple[str, Path]:
        """访问指定页面，获取文本内容并截图留证。

        Args:
            path: 页面路径
            label: 截图标签（如 cpu / memory / interface）
            timeout: 页面加载超时（秒）

        Returns:
            (页面文本, 截图文件路径)
        """
        text = self.execute(path, timeout=timeout)
        screenshot_path = self._take_screenshot(label)
        return text, screenshot_path

    def _take_screenshot(self, label: str) -> Path:
        """截图并保存到 output/screenshots/。"""
        if not self._page or not self._asset:
            return Path("")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self._asset.host}_{label}_{ts}.png"
        filepath = self._screenshot_dir / filename

        try:
            self._page.screenshot(path=str(filepath), full_page=True)
            logger.info("截图已保存: %s", filepath)
        except Exception as e:
            logger.warning("截图失败: %s", e)

        return filepath

    def disconnect(self) -> None:
        """关闭浏览器并停止 Playwright 进程。"""
        self._cleanup()
        if self._asset:
            logger.info("Web 连接已断开: %s", self._asset.host)
