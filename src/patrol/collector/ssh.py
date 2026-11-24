"""SSH 采集器 - 基于 Netmiko

职责：
  连接设备、执行命令、返回原始输出。

设计约束：
  - 密码、密钥等敏感信息不出现在日志中
  - 连接失败和认证失败抛出不同异常，调用方可区分处理
  - 分页由 Netmiko 的 device_type 自动处理（H3C 使用 hp_comware）
  - 所有超时均可配置
"""
from __future__ import annotations

import logging
import re
from typing import Any

from netmiko import ConnectHandler
from netmiko.exceptions import (
    AuthenticationException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from patrol.collector.base import BaseCollector
from patrol.models import DeviceAsset

logger = logging.getLogger(__name__)


class SSHConnectionError(Exception):
    """SSH 连接失败（网络不通、端口未开、超时）"""


class SSHAuthenticationError(Exception):
    """SSH 认证失败（用户名/密码错误）"""


class SSHCommandError(Exception):
    """命令执行失败"""


def _resolve_netmiko_device_type(asset: DeviceAsset) -> str:
    """解析设备对应的 Netmiko device_type(SSH 或 Telnet)。

    以各 Driver 声明的 netmiko_device_type / netmiko_telnet_device_type
    属性为单一数据源;Telnet 复用凭据与 super 提权,仅类型与端口不同。
    """
    import patrol.drivers  # noqa: F401  确保全部驱动已注册
    from patrol.drivers.registry import get_driver

    driver = get_driver(asset.vendor, asset.device_type)

    if asset.login_method == "console":
        # 本机串口通道:复用 Cisco 串口终端仿真(厂商提示符差异待真机验证)
        return "cisco_ios_serial"

    if asset.login_method == "telnet":
        nm_type = driver.netmiko_telnet_device_type
        if not nm_type or nm_type == "generic":
            raise SSHConnectionError(
                f"设备 {asset.name} ({asset.vendor}/{asset.device_type}) "
                f"不支持 Telnet 登录,请改用 SSH 或 web/api 方式"
            )
        return nm_type

    nm_type = driver.netmiko_device_type
    if not nm_type or nm_type == "generic":
        raise SSHConnectionError(
            f"设备 {asset.name} ({asset.vendor}/{asset.device_type}) "
            f"不支持 SSH 采集,请改用 web/api 登录方式"
        )
    return nm_type


class SSHCollector(BaseCollector):
    """基于 Netmiko 的 SSH 采集器

    分页处理：Netmiko 根据 device_type 自动发送空格或回车翻页。
    H3C Comware 设备使用 device_type='hp_comware'，Netmiko 内置了
    终端分页处理逻辑，无需手动处理 '---- More ----' 提示。
    """

    def __init__(self) -> None:
        self._conn: ConnectHandler | None = None
        self._host: str = ""

    def connect(self, asset: DeviceAsset) -> None:
        """建立 SSH 连接。

        日志中只记录 host:port，不记录用户名和密码。

        Raises:
            SSHAuthenticationError: 认证失败
            SSHConnectionError: 连接失败（网络不通、超时、端口未开）
        """
        self._host = asset.host
        logger.info("SSH 连接 %s:%d", asset.host, asset.port)

        device_params: dict[str, Any] = {
            "device_type": _resolve_netmiko_device_type(asset),
            "host": asset.host,
            "username": asset.username,
            "password": asset.password,
            "port": asset.port,
            "conn_timeout": asset.timeout,
            "banner_timeout": asset.timeout,
            "auth_timeout": asset.timeout,
        }
        if asset.login_method == "console":
            # 串口通道:host 存 COM 口名,port 存波特率(默认 9600)
            device_params["serial_settings"] = {
                "port": asset.host, "baudrate": asset.port or 9600}
            device_params.pop("host", None)
            device_params.pop("port", None)
            device_params.pop("conn_timeout", None)
        if asset.super_password:
            # 类 IOS 设备(锐捷/迈普/中兴等)登录后若落在非特权模式(提示符 >),
            # netmiko 会自动尝试 enable:Super 密码即 enable 密码,不交给它的话
            # enable 密码与登录密码不同的设备会直接连接失败。
            # 华为/H3C 的 super 提权在连接建立后单独执行(见 _enter_super_mode)。
            device_params["secret"] = asset.super_password

        try:
            self._conn = ConnectHandler(**device_params)
        except (AuthenticationException, NetmikoAuthenticationException) as e:
            logger.error("认证失败 %s:%d", asset.host, asset.port)
            raise SSHAuthenticationError(
                f"SSH 认证失败 {asset.host}:{asset.port}"
            ) from e
        except NetmikoTimeoutException as e:
            logger.error("连接超时 %s:%d", asset.host, asset.port)
            raise SSHConnectionError(
                f"SSH 连接超时 {asset.host}:{asset.port}"
            ) from e
        except Exception as e:
            logger.error("连接失败 %s:%d - %s", asset.host, asset.port, e)
            raise SSHConnectionError(
                f"SSH 连接失败 {asset.host}:{asset.port} - {e}"
            ) from e

        logger.info("SSH 连接成功: %s:%d", asset.host, asset.port)

        # 配置了 Super 密码时登录后自动提权(华为/H3C 等的 super 命令)
        if asset.super_password:
            self._enter_super_mode(asset)

    def _enter_super_mode(self, asset: DeviceAsset) -> None:
        """执行 super 提权:发送 super 命令并在密码提示后回填密码。

        提权失败只记录告警、不中断巡检(部分命令可能因权限不足返回不完整)。
        日志不记录密码内容。
        """
        try:
            output: str = self._conn.send_command_timing(
                "super", delay_factor=2
            )
            if re.search(r"[Pp]assword|密码", output):
                self._conn.send_command_timing(
                    asset.super_password, delay_factor=2
                )
                logger.info("[%s] super 提权已执行", asset.host)
            else:
                logger.warning(
                    "[%s] super 命令未出现密码提示,可能已处于最高权限或设备不支持", asset.host
                )
        except Exception as e:
            logger.warning("[%s] super 提权失败(继续巡检): %s", asset.host, e)

    def execute(self, command: str, timeout: int = 60) -> str:
        """执行单条命令，返回原始回显。

        Netmiko 的 send_command 会自动处理分页（More 提示）。
        日志中只记录命令名和回显长度，不记录回显内容（可能含敏感信息）。

        Raises:
            SSHCommandError: 命令执行失败
        """
        if self._conn is None:
            raise SSHCommandError("SSH 未连接")

        # 只读白名单校验(销号清单 #7):任何写操作命令在下发前拦截
        from patrol.readonly import ReadOnlyViolation, assert_readonly
        try:
            assert_readonly(command)
        except ReadOnlyViolation as e:
            logger.error("[%s] 只读校验拦截: %s", self._host, e)
            raise SSHCommandError(str(e)) from e

        logger.debug("[%s] 执行命令: %s (timeout=%ds)", self._host, command, timeout)
        try:
            output: str = self._conn.send_command(
                command,
                read_timeout=timeout,
                strip_prompt=True,
                strip_command=True,
            )
        except Exception as e:
            logger.error("[%s] 命令执行失败: %s - %s", self._host, command, e)
            raise SSHCommandError(
                f"命令执行失败 [{self._host}] {command}: {e}"
            ) from e

        logger.debug("[%s] 命令回显: %d 字节", self._host, len(output))
        return output

    def disconnect(self) -> None:
        """断开 SSH 连接。未连接时静默返回。"""
        if self._conn is not None:
            try:
                self._conn.disconnect()
            except Exception:
                pass
            self._conn = None
            logger.info("SSH 连接已断开: %s", self._host)
