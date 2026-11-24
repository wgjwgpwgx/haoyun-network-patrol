"""Web 登录认证(默认开启,config/auth.yaml 文件凭据)

背景:验收遗留问题 001——原实现仅环境变量 PATROL_WEB_PASSWORD 可启用,
绿色包用户从不设置环境变量,等效"无认证"。现改为默认开启:config/auth.yaml
缺失时自动播种 admin/admin123(使用说明中明示),登录后在
「系统设置 → 账号安全」修改;config/auth.yaml 中 enabled: false 可显式关闭。

凭据来源(优先级从高到低):
  1. 环境变量 PATROL_WEB_PASSWORD(可选 PATROL_WEB_USER,默认 admin)——兼容旧部署
  2. config/auth.yaml(缺失自动播种默认账号)

机制:
  - 无状态会话:Cookie 值为 "过期时间戳.HMAC-SHA256 签名",密钥为配置中的 secret
  - 修改用户名/密码即轮换 secret,所有旧会话立即失效
  - 密码以 PBKDF2-SHA256(10 万轮)加盐存储,不明文落盘
  - 登录失败限速:同用户名+来源 IP,60 秒内错 5 次即锁定
  - Cookie 属性 HttpOnly + SameSite=Lax(基础 CSRF 缓解)
  - 浏览器路径(/ /ui /reports)未认证 → 302 到登录页;API 路径 → 401 JSON;
    /static 静态资源放行(登录页需要样式)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

COOKIE_NAME = "patrol_session"
SESSION_TTL = 12 * 3600  # 会话默认有效期 12 小时(config/auth.yaml 的 session_ttl_hours 可调)

DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin123"
PBKDF2_ITERATIONS = 100_000

# 登录失败限速:同用户名+来源 IP,窗口内错 _FAIL_LIMIT 次即锁定 _FAIL_WINDOW 秒
_FAIL_LIMIT = 5
_FAIL_WINDOW = 60.0
_fail_log: dict[str, list[float]] = {}

_templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)


# ── 密码散列(PBKDF2-SHA256,标准库实现) ─────────────────────
def hash_password(password: str, *, salt: bytes | None = None,
                  iterations: int = PBKDF2_ITERATIONS) -> str:
    """生成 'pbkdf2_sha256$轮数$盐hex$散列hex' 形式的存储串。"""
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iter_s),
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ── config/auth.yaml 读写 ─────────────────────────────────────
def auth_config_path() -> Path:
    return Path("config") / "auth.yaml"


def default_auth_config() -> dict:
    return {
        "enabled": True,
        "username": DEFAULT_USER,
        "password_hash": hash_password(DEFAULT_PASSWORD),
        "secret": secrets.token_hex(32),
        "session_ttl_hours": 12,
    }


_AUTH_HEADER = (
    "# Web 登录认证配置(问题 001:默认开启)\n"
    "# 首次使用默认账号 admin / admin123,登录后请在「系统设置 → 账号安全」修改。\n"
    "# enabled: false 可关闭认证(仅建议本机/受信环境使用)。\n"
    "# 修改密码/用户名会轮换 secret,所有已登录会话立即失效。\n"
)


def save_auth_config(cfg: dict, path: Path | None = None) -> None:
    path = path or auth_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "enabled": bool(cfg.get("enabled", True)),
        "username": str(cfg.get("username", DEFAULT_USER)),
        "password_hash": str(cfg.get("password_hash", "")),
        "secret": str(cfg.get("secret", "")),
        "session_ttl_hours": int(cfg.get("session_ttl_hours", 12)),
    }
    from patrol.utils.fs import atomic_write_text

    atomic_write_text(
        path, _AUTH_HEADER + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    )


def load_auth_config(path: Path | None = None) -> dict:
    """读取 config/auth.yaml;文件缺失时自动播种默认账号(admin/admin123)。

    文件存在但读不了或内容无效时绝不落盘重置:否则一次手改出错、文件被截断或
    临时不可读,登录凭据就被悄悄换成文档里公开的默认密码。此时保持原文件不动,
    本次运行拒绝所有登录,日志给出恢复办法(修复或删除该文件后重启)。
    """
    path = path or auth_config_path()
    if not path.exists():
        cfg = default_auth_config()
        save_auth_config(cfg, path)
        return cfg
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        data, reason = None, f"读取失败: {e}"
    if isinstance(data, dict) and data.get("password_hash"):
        return data
    reason = reason if data is None else "缺少 password_hash 或内容不是映射"
    logger.error("Web 登录配置 %s 不可用(%s),已拒绝所有登录;"
                 "请修复或删除该文件后重启", path, reason)
    return {"enabled": True, "username": "", "password_hash": "",
            "secret": secrets.token_hex(32), "session_ttl_hours": 12}


# ── 凭据解析:环境变量 > config/auth.yaml ──────────────────────
def _active() -> tuple[str, dict]:
    """返回 (mode, cfg):mode 为 'env' / 'file' / 'off'。"""
    env_pw = os.environ.get("PATROL_WEB_PASSWORD", "")
    if env_pw:
        return "env", {
            "username": os.environ.get("PATROL_WEB_USER", DEFAULT_USER),
            "password": env_pw,
        }
    cfg = load_auth_config()
    if not cfg.get("enabled", True):
        return "off", cfg
    return "file", cfg


def auth_mode() -> str:
    return _active()[0]


def auth_enabled() -> bool:
    return auth_mode() != "off"


def auth_username() -> str:
    mode, cfg = _active()
    if mode == "off":
        return ""
    return str(cfg.get("username", DEFAULT_USER))


def auth_status() -> dict:
    """设置页展示用:认证状态、当前用户名。"""
    mode, _ = _active()
    return {
        "mode": mode,
        "mode_label": {"env": "环境变量", "file": "配置文件", "off": "已关闭"}[mode],
        "username": auth_username() if mode != "off" else "",
    }


def verify_login(username: str, password: str) -> bool:
    mode, cfg = _active()
    if mode == "env":
        return (
            hmac.compare_digest(username, str(cfg["username"]))
            and hmac.compare_digest(password, str(cfg["password"]))
        )
    return (
        hmac.compare_digest(username, str(cfg.get("username", "")))
        and verify_password(password, str(cfg.get("password_hash", "")))
    )


def change_account(
    current_password: str,
    new_username: str | None = None,
    new_password: str | None = None,
) -> str:
    """修改登录账号;成功即轮换会话密钥(旧会话全部失效)。失败抛 ValueError。"""
    mode, cfg = _active()
    if mode != "file":
        raise ValueError(
            "当前为环境变量认证(PATROL_WEB_PASSWORD),请修改环境变量后重启"
        )
    if not verify_password(current_password, str(cfg.get("password_hash", ""))):
        raise ValueError("当前密码不正确")

    username = (new_username or "").strip()
    password = new_password or ""
    if not username and not password:
        raise ValueError("没有需要修改的内容(用户名或新密码至少填一项)")

    if username:
        if not (2 <= len(username) <= 32):
            raise ValueError("用户名长度需在 2-32 个字符之间")
        if any(ch.isspace() for ch in username):
            raise ValueError("用户名不能包含空格")
        cfg["username"] = username
    if password:
        if len(password) < 6:
            raise ValueError("新密码至少 6 个字符")
        cfg["password_hash"] = hash_password(password)

    # 轮换会话密钥:旧 Cookie 全部失效
    cfg["secret"] = secrets.token_hex(32)
    save_auth_config(cfg)
    return "账号已更新,所有已登录会话已失效,请重新登录"


# ── 登录失败限速 ──────────────────────────────────────────────
def _throttle_key(username: str, ip: str) -> str:
    return f"{username}|{ip}"


def is_locked(username: str, ip: str) -> bool:
    now = time.time()
    key = _throttle_key(username, ip)
    fails = [t for t in _fail_log.get(key, []) if now - t < _FAIL_WINDOW]
    _fail_log[key] = fails
    return len(fails) >= _FAIL_LIMIT


def record_failure(username: str, ip: str) -> None:
    key = _throttle_key(username, ip)
    _fail_log.setdefault(key, []).append(time.time())


def clear_failures(username: str, ip: str) -> None:
    _fail_log.pop(_throttle_key(username, ip), None)


# ── 会话令牌(无状态 exp.HMAC) ────────────────────────────────
def _secret() -> bytes:
    mode, cfg = _active()
    if mode == "env":
        return hashlib.sha256(
            f"patrol::{cfg['username']}::{cfg['password']}".encode()
        ).digest()
    raw = str(cfg.get("secret", ""))
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return hashlib.sha256(raw.encode()).digest()


def _session_ttl() -> int:
    mode, cfg = _active()
    if mode == "env":
        return SESSION_TTL
    try:
        hours = float(cfg.get("session_ttl_hours", 12))
    except (TypeError, ValueError):
        hours = 12.0
    return int(hours * 3600)


def _issue_token() -> str:
    exp = str(int(time.time()) + _session_ttl())
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, _, sig = token.partition(".")
    if not exp.isdigit() or not hmac.compare_digest(
        sig, hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    ):
        return False
    return int(exp) > time.time()


def _is_exempt_path(path: str) -> bool:
    """免认证路径:登录页与静态资源(登录页需要样式)。"""
    return (
        path == "/ui/login" or path.startswith("/static") or path == "/favicon.ico"
    )


def _is_browser_path(path: str) -> bool:
    return (
        path == "/" or path.startswith("/ui") or path.startswith("/reports")
    )


def setup_auth(app: FastAPI) -> None:
    """注册认证中间件与登录/登出路由。"""

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if auth_enabled():
            path = request.url.path
            if not _is_exempt_path(path):
                if not _valid_token(request.cookies.get(COOKIE_NAME)):
                    if _is_browser_path(path):
                        return RedirectResponse("/ui/login", status_code=302)
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "未认证,请先访问 /ui/login 登录"},
                    )
        return await call_next(request)

    @app.get("/ui/login", include_in_schema=False)
    def login_form(request: Request, error: str = ""):
        if not auth_enabled():
            return RedirectResponse("/ui", status_code=303)
        if _valid_token(request.cookies.get(COOKIE_NAME)):
            return RedirectResponse("/ui", status_code=303)
        return _templates.TemplateResponse("ui/login.html", {
            "request": request, "error": error,
        })

    @app.post("/ui/login", include_in_schema=False)
    def login_submit(
        request: Request,
        username: str = Form(...), password: str = Form(...),
    ):
        from urllib.parse import quote

        if not auth_enabled():
            return RedirectResponse("/ui", status_code=303)
        ip = (request.client.host if request.client else "") or "local"
        username = username.strip()
        if is_locked(username, ip):
            return RedirectResponse(
                f"/ui/login?error={quote('尝试过于频繁,请 1 分钟后再试')}",
                status_code=303,
            )
        if not verify_login(username, password):
            record_failure(username, ip)
            return RedirectResponse(
                f"/ui/login?error={quote('用户名或密码错误')}", status_code=303
            )
        clear_failures(username, ip)
        resp = RedirectResponse("/ui", status_code=303)
        resp.set_cookie(
            COOKIE_NAME, _issue_token(),
            httponly=True, samesite="lax", max_age=_session_ttl(),
        )
        return resp

    @app.get("/ui/logout", include_in_schema=False)
    def logout():
        target = "/ui" if not auth_enabled() else "/ui/login"
        resp = RedirectResponse(target, status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp
