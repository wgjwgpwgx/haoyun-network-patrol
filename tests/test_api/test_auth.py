"""Web 登录认证测试(问题 001:默认开启 + 文件凭据)

语义:
  - 不配置任何东西 → config/auth.yaml 自动播种 admin/admin123,认证默认开启
  - PATROL_WEB_PASSWORD 环境变量 → 环境变量模式(兼容旧部署,优先级最高)
  - config/auth.yaml 中 enabled: false → 显式关闭
  - 登录失败限速、/static 放行、改密/改用户名闭环(旧会话立即失效)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from patrol.api import auth as auth_mod
from patrol.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_auth_state(monkeypatch):
    """清空节流记录并解除环境变量认证,用例间互不污染。"""
    monkeypatch.delenv("PATROL_WEB_PASSWORD", raising=False)
    monkeypatch.delenv("PATROL_WEB_USER", raising=False)
    auth_mod._fail_log.clear()
    yield
    auth_mod._fail_log.clear()


@pytest.fixture
def file_auth(tmp_path, monkeypatch):
    """隔离的 config/auth.yaml(缺失自动播种 admin/admin123)。"""
    monkeypatch.chdir(tmp_path)
    return auth_mod.load_auth_config()


def _disable_auth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    auth_mod.save_auth_config({**auth_mod.default_auth_config(), "enabled": False})


class TestDefaultOn:
    """问题 001 核心语义:不配置任何东西也必须有认证。"""

    def test_missing_config_seeds_default_account(self, file_auth):
        assert file_auth["enabled"] is True
        assert file_auth["username"] == "admin"
        assert auth_mod.verify_password("admin123", file_auth["password_hash"])
        assert auth_mod.auth_config_path().exists()

    def test_ui_redirects_to_login_by_default(self, file_auth, client):
        r = client.get("/ui", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/ui/login"

    def test_root_redirects_to_login_by_default(self, file_auth, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/ui/login"

    def test_api_gets_401_json_by_default(self, file_auth, client):
        r = client.get("/devices", follow_redirects=False)
        assert r.status_code == 401
        assert "detail" in r.json()

    def test_docs_gets_401_by_default(self, file_auth, client):
        r = client.get("/docs", follow_redirects=False)
        assert r.status_code == 401

    def test_default_credentials_can_login(self, file_auth, client):
        r = client.post(
            "/ui/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert auth_mod.COOKIE_NAME in r.cookies
        assert "HttpOnly" in r.headers.get("set-cookie", "")
        r2 = client.get("/ui", follow_redirects=False)
        assert r2.status_code == 200

    def test_login_page_shows_default_account_hint(self, file_auth, client):
        r = client.get("/ui/login", follow_redirects=False)
        assert r.status_code == 200
        assert "admin123" in r.text


class TestDisabled:
    def test_ui_accessible_without_login(self, tmp_path, monkeypatch, client):
        _disable_auth(tmp_path, monkeypatch)
        r = client.get("/ui", follow_redirects=False)
        assert r.status_code == 200

    def test_login_page_redirects_to_ui(self, tmp_path, monkeypatch, client):
        _disable_auth(tmp_path, monkeypatch)
        r = client.get("/ui/login", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/ui"


class TestEnvMode:
    """兼容旧部署:PATROL_WEB_PASSWORD 环境变量优先于配置文件。"""

    @pytest.fixture
    def env_auth(self, monkeypatch):
        monkeypatch.setenv("PATROL_WEB_USER", "admin")
        monkeypatch.setenv("PATROL_WEB_PASSWORD", "s3cret-pw")

    def test_env_enables_auth(self, tmp_path, monkeypatch, env_auth, client):
        monkeypatch.chdir(tmp_path)
        r = client.get("/ui", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/ui/login"

    def test_env_login_works(self, tmp_path, monkeypatch, env_auth, client):
        monkeypatch.chdir(tmp_path)
        r = client.post(
            "/ui/login",
            data={"username": "admin", "password": "s3cret-pw"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert auth_mod.COOKIE_NAME in r.cookies

    def test_env_overrides_config_file(self, tmp_path, monkeypatch, env_auth):
        monkeypatch.chdir(tmp_path)
        auth_mod.load_auth_config()  # 播种文件凭据 admin/admin123
        assert auth_mod.auth_mode() == "env"
        assert auth_mod.verify_login("admin", "s3cret-pw") is True
        assert auth_mod.verify_login("admin", "admin123") is False

    def test_change_account_rejected_in_env_mode(
        self, tmp_path, monkeypatch, env_auth
    ):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="环境变量"):
            auth_mod.change_account("s3cret-pw", new_password="new-pass-1")


class TestLoginFlow:
    def test_wrong_password_rejected(self, file_auth, client):
        r = client.post(
            "/ui/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "error=" in r.headers["location"]
        assert auth_mod.COOKIE_NAME not in r.cookies
        r2 = client.get("/ui", follow_redirects=False)
        assert r2.status_code == 302  # 仍未认证

    def test_wrong_username_rejected(self, file_auth, client):
        r = client.post(
            "/ui/login",
            data={"username": "root", "password": "admin123"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "error=" in r.headers["location"]

    def test_logout_invalidates_session(self, file_auth, client):
        client.post(
            "/ui/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        r = client.get("/ui/logout", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/ui/login"
        r2 = client.get("/ui", follow_redirects=False)
        assert r2.status_code == 302

    def test_login_page_redirects_when_already_logged_in(self, file_auth, client):
        client.post(
            "/ui/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        r = client.get("/ui/login", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/ui"


class TestStaticExempt:
    """登录页样式必须免认证,否则未登录页面无样式(历史缺陷)。"""

    def test_static_css_served_without_login(self, file_auth, client):
        r = client.get("/static/vendor/bootstrap.min.css", follow_redirects=False)
        assert r.status_code == 200

    def test_static_logo_served_without_login(self, file_auth, client):
        r = client.get("/static/logo.png", follow_redirects=False)
        assert r.status_code == 200

    def test_favicon_not_blocked(self, file_auth, client):
        r = client.get("/static/favicon.png", follow_redirects=False)
        assert r.status_code == 200


class TestThrottle:
    def test_locked_after_repeated_failures(self, file_auth, client, monkeypatch):
        monkeypatch.setattr(auth_mod, "_FAIL_LIMIT", 2)
        for _ in range(2):
            client.post(
                "/ui/login",
                data={"username": "admin", "password": "wrong"},
                follow_redirects=False,
            )
        # 即使密码正确,窗口内超限也拒绝
        r = client.post(
            "/ui/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "error=" in r.headers["location"]
        assert auth_mod.COOKIE_NAME not in r.cookies

    def test_clear_failures_unlocks(self, file_auth, client, monkeypatch):
        monkeypatch.setattr(auth_mod, "_FAIL_LIMIT", 1)
        client.post(
            "/ui/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
        assert auth_mod.is_locked("admin", "testclient")
        auth_mod.clear_failures("admin", "testclient")
        assert not auth_mod.is_locked("admin", "testclient")
        r = client.post(
            "/ui/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert auth_mod.COOKIE_NAME in r.cookies

    def test_window_expiry_unlocks(self, file_auth, monkeypatch):
        monkeypatch.setattr(auth_mod, "_FAIL_WINDOW", 0.0)
        for _ in range(10):
            auth_mod.record_failure("admin", "1.2.3.4")
        assert not auth_mod.is_locked("admin", "1.2.3.4")


class TestAccountChange:
    """设置页账号管理闭环:改密/改用户名,旧会话立即失效。"""

    def _login(self, client, username="admin", password="admin123"):
        return client.post(
            "/ui/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_change_password_full_loop(self, file_auth, client):
        self._login(client)
        r = client.post(
            "/ui/settings/account",
            data={
                "current_password": "admin123",
                "new_username": "",
                "new_password": "new-pass-9",
                "new_password2": "new-pass-9",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "account_msg=" in r.headers["location"]
        # 旧密码失效、旧会话失效
        assert client.get("/ui", follow_redirects=False).status_code == 302
        assert auth_mod.verify_login("admin", "admin123") is False
        # 新密码可登录
        assert self._login(client, "admin", "new-pass-9").status_code == 303
        assert client.get("/ui", follow_redirects=False).status_code == 200

    def test_change_username_full_loop(self, file_auth, client):
        self._login(client)
        r = client.post(
            "/ui/settings/account",
            data={
                "current_password": "admin123",
                "new_username": "haoyun",
                "new_password": "",
                "new_password2": "",
            },
            follow_redirects=False,
        )
        assert "account_msg=" in r.headers["location"]
        assert self._login(client, "admin", "admin123").status_code == 303
        assert self._login(client, "haoyun", "admin123").status_code == 303
        assert client.get("/ui", follow_redirects=False).status_code == 200

    def test_wrong_current_password_rejected(self, file_auth, client):
        self._login(client)
        r = client.post(
            "/ui/settings/account",
            data={
                "current_password": "not-my-pass",
                "new_password": "new-pass-9",
                "new_password2": "new-pass-9",
            },
            follow_redirects=False,
        )
        assert "account_err=" in r.headers["location"]
        assert auth_mod.verify_login("admin", "admin123") is True

    def test_mismatched_confirm_rejected(self, file_auth, client):
        self._login(client)
        r = client.post(
            "/ui/settings/account",
            data={
                "current_password": "admin123",
                "new_password": "new-pass-9",
                "new_password2": "different",
            },
            follow_redirects=False,
        )
        assert "account_err=" in r.headers["location"]
        assert auth_mod.verify_login("admin", "admin123") is True

    def test_short_password_rejected(self, file_auth):
        with pytest.raises(ValueError, match="至少 6"):
            auth_mod.change_account("admin123", new_password="12345")

    def test_nothing_to_change_rejected(self, file_auth):
        with pytest.raises(ValueError, match="至少填一项"):
            auth_mod.change_account("admin123")

    def test_settings_page_shows_account_card(self, file_auth, client):
        self._login(client)
        r = client.get("/ui/settings", follow_redirects=False)
        assert r.status_code == 200
        assert "账号安全" in r.text
        assert "/ui/settings/account" in r.text

    def test_password_hash_rotates_on_change(self, file_auth):
        old_hash = file_auth["password_hash"]
        old_secret = file_auth["secret"]
        auth_mod.change_account("admin123", new_password="new-pass-9")
        cfg = auth_mod.load_auth_config()
        assert cfg["password_hash"] != old_hash
        assert cfg["secret"] != old_secret  # 轮换会话密钥


class TestTokens:
    def test_expired_token_rejected(self, file_auth):
        import hashlib
        import hmac
        import time

        exp = str(int(time.time()) - 10)
        sig = hmac.new(
            auth_mod._secret(), exp.encode(), hashlib.sha256
        ).hexdigest()
        assert auth_mod._valid_token(f"{exp}.{sig}") is False

    def test_tampered_token_rejected(self, file_auth):
        token = auth_mod._issue_token()
        exp, sig = token.split(".")
        assert auth_mod._valid_token(f"{exp}.{sig[:-2]}00") is False
        assert auth_mod._valid_token(f"{exp}x.{sig}") is False
        assert auth_mod._valid_token("garbage") is False
        assert auth_mod._valid_token(None) is False

    def test_secret_rotation_invalidates_token(self, file_auth):
        token = auth_mod._issue_token()
        assert auth_mod._valid_token(token) is True
        cfg = auth_mod.load_auth_config()
        cfg["secret"] = "ff" * 32
        auth_mod.save_auth_config(cfg)
        assert auth_mod._valid_token(token) is False

    def test_session_ttl_from_config(self, file_auth, monkeypatch):
        cfg = auth_mod.load_auth_config()
        cfg["session_ttl_hours"] = 1
        auth_mod.save_auth_config(cfg)
        assert auth_mod._session_ttl() == 3600


class TestPasswordHashing:
    def test_roundtrip(self):
        stored = auth_mod.hash_password("s3cret")
        assert auth_mod.verify_password("s3cret", stored) is True
        assert auth_mod.verify_password("other", stored) is False

    def test_salt_makes_hashes_unique(self):
        a = auth_mod.hash_password("same")
        b = auth_mod.hash_password("same")
        assert a != b
        assert auth_mod.verify_password("same", a)
        assert auth_mod.verify_password("same", b)

    def test_garbage_stored_rejected(self):
        assert auth_mod.verify_password("x", "") is False
        assert auth_mod.verify_password("x", "not-a-hash") is False
        assert auth_mod.verify_password("x", "md5$1$aa$bb") is False
