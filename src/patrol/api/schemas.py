"""API 请求/响应数据模型

设计原则：
  - 请求模型做输入校验（字段类型、必填、范围）
  - 响应模型不返回密码
  - 所有模型使用 Pydantic v2
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from patrol.models import validate_host


# ── 设备相关 ────────────────────────────────────────────────────


class DeviceCreate(BaseModel):
    """创建设备请求"""
    name: str = Field(..., min_length=1, max_length=100, description="设备别名")
    customer: str = Field("", max_length=100, description="归属客户(甲方公司)名称")
    host: str = Field(..., min_length=1, max_length=64, description="管理 IP")
    vendor: str = Field("h3c", max_length=50)
    device_type: str = Field("comware_switch", max_length=50)
    login_method: str = Field("ssh", max_length=10, description="采集方式: ssh/web/api")
    port: int = Field(22, ge=1, le=65535)
    web_port: int = Field(443, ge=1, le=65535)
    web_protocol: str = Field("https", max_length=10)
    verify_ssl: bool = True  # HTTPS 证书校验;自签名证书可 False 跳过(问题 006)
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)
    super_password: str = Field("", max_length=200, description="Super 密码(登录后提权)")
    api_token: str = Field("", max_length=500)
    enabled: bool = True
    screenshot: bool = True
    timeout: int = Field(30, ge=1, le=300)
    command_timeout: int = Field(60, ge=1, le=600)

    _check_host = field_validator("host")(lambda v: validate_host(v))


class DeviceUpdate(BaseModel):
    """修改设备请求（所有字段可选）"""
    name: str | None = Field(None, min_length=1, max_length=100)
    customer: str | None = Field(None, max_length=100)
    host: str | None = Field(None, min_length=1, max_length=64)
    vendor: str | None = Field(None, max_length=50)
    device_type: str | None = Field(None, max_length=50)
    port: int | None = Field(None, ge=1, le=65535)
    username: str | None = Field(None, min_length=1, max_length=100)
    password: str | None = Field(None, min_length=1, max_length=200)
    super_password: str | None = Field(None, max_length=200)
    enabled: bool | None = None
    timeout: int | None = Field(None, ge=1, le=300)
    command_timeout: int | None = Field(None, ge=1, le=600)
    verify_ssl: bool | None = None

    _check_host = field_validator("host")(lambda v: validate_host(v))


class DeviceOut(BaseModel):
    """设备响应（不包含密码、Super 密码和 token）"""
    name: str
    customer: str
    host: str
    vendor: str
    device_type: str
    login_method: str
    port: int
    web_port: int
    web_protocol: str
    username: str
    enabled: bool
    timeout: int
    command_timeout: int


# ── 客户信息 ──────────────────────────────────────────────────


class CustomerCreate(BaseModel):
    """创建客户请求"""
    name: str = Field(..., min_length=1, max_length=100, description="客户(甲方公司)名称")
    contact: str = Field("", max_length=100, description="联系人")
    phone: str = Field("", max_length=50, description="联系电话")
    remark: str = Field("", max_length=500, description="备注")


class CustomerUpdate(BaseModel):
    """修改客户请求（所有字段可选）"""
    name: str | None = Field(None, min_length=1, max_length=100)
    contact: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    remark: str | None = Field(None, max_length=500)


class CustomerOut(BaseModel):
    """客户响应"""
    name: str
    contact: str
    phone: str
    remark: str


# ── 巡检任务相关 ────────────────────────────────────────────────


class TaskCreate(BaseModel):
    """创建巡检任务请求"""
    device_name: str = Field(..., min_length=1, max_length=100, description="目标设备名称")


class TaskOut(BaseModel):
    """巡检任务响应"""
    task_id: str
    device_name: str
    device_host: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    report_file: str | None = None
    error: str | None = None
