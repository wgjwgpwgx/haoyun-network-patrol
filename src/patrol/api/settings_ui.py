"""系统设置 - 产品信息 / 开源协议 / AI API Key / 软件更新(含自动更新)

独立于 patrol.api.ui 的路由模块,只读写 config/ai.yaml 与 config/settings.yaml
以及 update/ 更新工作区,不触碰设备/任务/报告等既有功能。
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from patrol import __version__
from patrol.ai.presets import PRESET_GROUPS, match_preset
from patrol.update import check_for_update, load_update_url, save_update_url

router = APIRouter(prefix="/ui/settings", tags=["系统设置"])

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)

# ── 产品信息(作者定稿,单一来源 patrol.product,署名勿改) ──────
from patrol.product import (  # noqa: E402  (re-export 保持旧引用不变)
    AUTHOR,
    AUTHOR_QQ,
    LICENSE_NAME,
    LICENSE_TEXT,
    PRODUCT_NAME,
    PRODUCT_NAME_EN,
)

_AI_PATH = Path("config") / "ai.yaml"


def _ctx(request: Request, **kwargs) -> dict:
    from patrol.api.auth import auth_enabled
    return {"request": request, "auth_on": auth_enabled(), **kwargs}


def _load_ai_dict() -> dict:
    """读取 config/ai.yaml 原始字段(不含环境变量覆盖)。"""
    try:
        data = yaml.safe_load(_AI_PATH.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _save_ai_dict(data: dict) -> None:
    """写回 config/ai.yaml,保留注释头与未在表单中的字段。"""
    _AI_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# AI 大模型分析配置(系统设置页面自动保存)\n"
        "# 兼容所有 OpenAI Chat Completions 协议服务(DeepSeek / 智谱GLM / 通义千问 / Kimi / Ollama 等)\n"
        "# 修改后无需重启,下次巡检/手动分析即生效。\n"
    )
    # 已有文件的注释块(使用说明)原样保留,只替换数据部分
    if _AI_PATH.exists():
        comments = []
        for line in _AI_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                comments.append(line)
            elif line.strip():
                break
        if comments:
            header = "\n".join(comments) + "\n"
    from patrol.utils.fs import atomic_write_text

    atomic_write_text(
        _AI_PATH, header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    )


def _mask_key(key: str) -> str:
    """API Key 展示为掩码,只露末 4 位。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * 8 + key[-4:]


@router.get("", response_class=HTMLResponse)
def settings_page(
    request: Request,
    saved: str = "",
    error: str = "",
    update_result: dict | None = None,
    ai_test: dict | None = None,
    ai_override: dict | None = None,
    account_msg: str = "",
    account_err: str = "",
):
    """系统设置页:产品信息、MIT 协议、AI 配置、软件更新、账号安全。"""
    from patrol.ai import load_ai_config
    from patrol.api.auth import auth_status
    from patrol.updater import is_frozen, load_pending

    ai_raw = _load_ai_dict()
    if ai_override:
        ai_raw = {**ai_raw, **{k: v for k, v in ai_override.items() if v is not None}}
    ai_effective = load_ai_config()
    masked = _mask_key(
        str((ai_override or {}).get("api_key") or ai_raw.get("api_key") or "")
    )
    return templates.TemplateResponse("ui/settings.html", _ctx(
        request,
        active="settings",
        saved=saved,
        error=error,
        product_name=PRODUCT_NAME,
        product_name_en=PRODUCT_NAME_EN,
        app_version=__version__,
        author=AUTHOR,
        author_qq=AUTHOR_QQ,
        license_name=LICENSE_NAME,
        license_text=LICENSE_TEXT,
        ai=ai_raw,
        ai_ready=ai_effective.ready,
        ai_key_masked=masked,
        ai_env_override=any(
            os.environ.get(k)
            for k in ("PATROL_AI_API_KEY", "PATROL_AI_BASE_URL", "PATROL_AI_MODEL")
        ),
        ai_test=ai_test,
        llm_presets=PRESET_GROUPS,
        preset_matched=match_preset(str(ai_raw.get("base_url") or "")),
        update_url=load_update_url(),
        update_result=update_result,
        update_pending=load_pending(),
        frozen=is_frozen(),
        auth=auth_status(),
        account_msg=account_msg,
        account_err=account_err,
    ))


@router.post("/account")
def settings_account(
    current_password: str = Form(default=""),
    new_username: str = Form(default=""),
    new_password: str = Form(default=""),
    new_password2: str = Form(default=""),
):
    """修改登录账号(用户名/密码);成功后旧会话立即失效。"""
    from urllib.parse import quote

    from patrol.api.auth import change_account

    new_password = new_password or ""
    new_password2 = new_password2 or ""
    if new_password != new_password2:
        return RedirectResponse(
            "/ui/settings?account_err=" + quote("两次输入的新密码不一致"),
            status_code=303,
        )
    try:
        msg = change_account(
            current_password or "",
            new_username or None,
            new_password or None,
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/ui/settings?account_err={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(
        f"/ui/settings?account_msg={quote(msg)}", status_code=303
    )


@router.post("/ai")
def settings_save_ai(
    enabled: str = Form(default=""),
    base_url: str = Form(default=""),
    api_key: str = Form(default=""),
    model: str = Form(default=""),
):
    """保存 AI 大模型配置(API Key 留空则保持原值不变)。"""
    data = _load_ai_dict()

    base_url = (base_url or "").strip()
    model = (model or "").strip()
    if enabled and not base_url:
        return RedirectResponse("/ui/settings?error=" + "接口地址不能为空", status_code=303)
    if base_url and not base_url.startswith(("http://", "https://")):
        return RedirectResponse("/ui/settings?error=" + "接口地址需以 http:// 或 https:// 开头", status_code=303)

    new_key = (api_key or "").strip()
    if new_key:
        data["api_key"] = new_key
    # 留空 → 保留原 api_key 字段
    data["enabled"] = bool(enabled)
    if base_url:
        data["base_url"] = base_url
    if model:
        data["model"] = model
    for field, default in (("timeout", 120), ("max_tokens", 4096), ("temperature", 0.2)):
        data.setdefault(field, default)

    _save_ai_dict(data)
    return RedirectResponse("/ui/settings?saved=ai", status_code=303)


@router.post("/test-ai", response_class=HTMLResponse)
def settings_test_ai(
    request: Request,
    enabled: str = Form(default=""),
    base_url: str = Form(default=""),
    api_key: str = Form(default=""),
    model: str = Form(default=""),
):
    """测试连通:用表单当前值发一条最小对话,验证 Key/地址/模型有效(不落盘)。"""
    import time

    from patrol.ai.client import LLMClient, LLMError
    from patrol.ai.config import AIConfig

    base_url = (base_url or "").strip()
    model = (model or "").strip()
    key = (api_key or "").strip() or str(_load_ai_dict().get("api_key") or "")
    override = {"enabled": bool(enabled), "base_url": base_url, "model": model,
                "api_key": key}

    if not base_url:
        result = {"ok": False, "message": "请先选择厂商或填写接口地址"}
    elif not key:
        result = {"ok": False, "message": "请先填写 API Key(Ollama 本地可随意填非空值)"}
    elif not model:
        result = {"ok": False, "message": "请先填写模型名"}
    else:
        cfg = AIConfig(enabled=True, base_url=base_url, api_key=key,
                       model=model, timeout=30, max_tokens=8)
        try:
            t0 = time.monotonic()
            reply = LLMClient(cfg).chat(
                [{"role": "user", "content": "连通性测试,请只回复:OK"}]
            )
            elapsed = time.monotonic() - t0
            result = {
                "ok": True,
                "message": f"连接成功({elapsed:.1f}s),模型响应:{reply.strip()[:60]}",
            }
        except LLMError as e:
            result = {"ok": False, "message": f"连接失败:{e}"}

    return settings_page(request, ai_test=result, ai_override=override)


@router.post("/update-url")
def settings_save_update_url(update_url: str = Form(default="")):
    """保存更新源地址。"""
    save_update_url(update_url)
    return RedirectResponse("/ui/settings?saved=update", status_code=303)


@router.post("/check-update", response_class=HTMLResponse)
def settings_check_update(request: Request):
    """软件更新按钮:拉取更新清单并展示检查结果。"""
    result = check_for_update()
    result["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return settings_page(request, update_result=result)


@router.post("/download-update", response_class=HTMLResponse)
def settings_download_update(request: Request):
    """自动更新第一步:下载更新包并暂存(支持 sha256 校验)。"""
    from patrol.updater import UpdateError, download_package, stage_update

    result = check_for_update()
    if result["status"] != "available":
        result["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return settings_page(
            request, update_result=result,
            error="当前没有可用更新,无需下载安装",
        )
    try:
        zip_path = download_package(
            result["url"], result["latest"], expected_sha256=result.get("sha256", "")
        )
        stage_update(zip_path, result["latest"])
    except UpdateError as e:
        result["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return settings_page(request, update_result=result, error=str(e))

    result = {
        **result,
        "status": "downloaded",
        "message": f"更新包 v{result['latest']} 已下载并校验,点击「重启并安装」完成更新",
    }
    return settings_page(request, update_result=result)


@router.post("/install-update", response_class=HTMLResponse)
def settings_install_update(request: Request):
    """自动更新第二步:启动替换脚本并退出主程序,由脚本完成替换后自动重启。"""
    import os as os_mod

    from patrol.updater import UpdateError, install_now, is_frozen, load_pending

    pending = load_pending()
    if pending is None:
        return settings_page(
            request, error="没有待安装的更新包,请先点击「下载并安装」",
        )
    try:
        install_now()
    except UpdateError as e:
        return settings_page(request, error=str(e), update_result=None)

    # 给响应留出落盘时间,随后退出,把 exe 让给更新脚本替换
    threading.Timer(3.0, os_mod._exit, (0,)).start()
    return settings_page(request, update_result={
        "status": "installing",
        "current": __version__,
        "latest": pending.get("version", ""),
        "message": "正在安装更新,程序即将退出并自动重启,请稍候 10~30 秒后刷新页面",
    })
