"""统一数据模型 - 所有层之间的数据契约

层级关系：
  DeviceAsset (配置) -> DeviceReport (采集结果) -> CheckItem (单项检查)
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def validate_host(value: str) -> str:
    """校验管理地址:仅允许 IP/主机名安全字符,阻断路径遍历。

    拒绝包含斜杠、反斜杠、.. 或其他特殊字符的值(host 会被拼进报告文件名)。
    """
    if not value or ".." in value or not re.fullmatch(r"[0-9A-Za-z.\-]+", value):
        raise ValueError(
            f"管理地址非法: {value!r}(仅允许 IP 或主机名,不能包含 / \\ .. 等字符)"
        )
    return value


# ── 设备资产模型 ──────────────────────────────────────────────────


class DeviceAsset(BaseModel):
    """设备资产 - 描述一台待巡检设备的静态配置

    从 YAML 配置文件加载，驱动采集和报告生成。
    支持三种采集方式：ssh / web / api
    """

    name: str
    """设备别名，用于报告显示"""

    customer: str = ""
    """归属客户(甲方公司)名称，关联客户信息模块"""

    host: str
    """管理 IP 地址(经 validate_host 校验,禁止路径分隔符)"""

    @field_validator("host")
    @classmethod
    def _check_host(cls, v: str) -> str:
        return validate_host(v)

    vendor: str = "h3c"
    """厂商标识，如 h3c / huawei / ruijie / sangfor / dptech"""

    device_type: str = "comware_switch"
    """设备类型，如 comware_switch / vrp_switch / ngaf_firewall / fw_firewall"""

    login_method: str = "ssh"
    """采集方式：ssh / web / api"""

    port: int = 22
    """SSH 端口（login_method=ssh 时使用）"""

    web_port: int = 443
    """Web 管理端口（login_method=web/api 时使用）"""

    web_protocol: str = "https"
    """Web 协议：http / https"""

    verify_ssl: bool = True
    """HTTPS 证书校验（login_method=web/api，问题 006）。自签名证书可设 false 跳过"""

    username: str = ""
    """登录用户名"""

    password: str = ""
    """登录密码"""

    super_password: str = ""
    """Super 密码(登录后提权用，如华为/H3C 的 super 命令)"""

    api_token: str = ""
    """API Token（login_method=api 时使用，如深信服 NGAF WebAPI）"""

    enabled: bool = True
    """是否启用巡检"""

    credential_ref: str = ""
    """凭据引用标识（预留）"""

    timeout: int = 30
    """连接超时（秒）"""

    command_timeout: int = 60
    """命令/页面加载超时（秒）"""

    screenshot: bool = True
    """Web 采集时是否截图留证"""

    known_issues: str = ""
    """已知异常项(逗号分隔检查项名,如"fan_status,interface_status")。
    这些项 FAIL 时报告标注为"预期行为",不计入异常。"""

    quick_mode: bool = False
    """快速巡检模式:只跑核心 5 项+上次异常项,跳过稳定项(老设备友好)。"""


# ── 检查结果模型 ──────────────────────────────────────────────────


class CheckStatus(str, Enum):
    """检查结果状态

    PASS    - 检查通过，指标在正常范围
    FAIL    - 确认异常，指标超出阈值
    UNKNOWN - 无法判断（解析失败、命令不支持、权限不足、采集失败）
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CheckItem(BaseModel):
    """单项检查结果

    采集 → 解析 → 分析 各阶段的最终产物。
    raw_output 保留原始命令输出（报告层会脱敏后再展示）。
    """

    name: str
    """检查项标识，如 cpu_usage"""

    category: str
    """检查类别，如 CPU / 内存 / 接口状态"""

    command: str
    """执行的设备命令"""

    raw_output: str
    """命令原始回显"""

    status: CheckStatus
    """检查判定结果"""

    message: str
    """人类可读的检查结论"""

    details: dict[str, Any] = Field(default_factory=dict)
    """结构化解析数据"""


class DeviceReport(BaseModel):
    """单台设备的巡检报告

    包含设备信息、所有检查项、采集时间。
    """

    asset: DeviceAsset
    """对应的设备资产"""

    model: str = ""
    """设备型号（从 display version 解析）"""

    software_version: str = ""
    """软件版本"""

    uptime: str = ""
    """运行时间"""

    serial_number: str = ""
    """序列号"""

    check_items: list[CheckItem] = Field(default_factory=list)
    """检查项列表"""

    collected_at: datetime = Field(default_factory=datetime.now)
    """采集时间"""

    error: str | None = None
    """整体错误信息（如连接失败）"""

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.check_items if c.status == CheckStatus.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.check_items if c.status == CheckStatus.FAIL)

    @property
    def unknown_count(self) -> int:
        return sum(1 for c in self.check_items if c.status == CheckStatus.UNKNOWN)

    @property
    def summary(self) -> str:
        return (
            f"PASS: {self.pass_count}, FAIL: {self.fail_count}, "
            f"UNKNOWN: {self.unknown_count}"
        )


class PatrolReport(BaseModel):
    """完整巡检报告（可包含多台设备）"""

    title: str = "网络设备巡检报告"
    devices: list[DeviceReport] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
    # AI 大模型分析结论(analyzer 写入,报告器渲染;None 表示未分析)
    ai_analysis: dict | None = None

    @property
    def total_devices(self) -> int:
        return len(self.devices)

    @property
    def has_failures(self) -> bool:
        return any(d.fail_count > 0 for d in self.devices)
