"""绿色包(Web 访问认证)冻结冒烟:证明问题 001 在打包形态下闭环可用。

流程:启动 dist 下的 exe(无环境变量凭据)→ 未登录 302 登录页 / API 401
→ 静态资源免认证 → 默认账号 admin/admin123 登录 → 登录后 200
→ 设置页改密(旧会话立即失效)→ 新密码登录 → 退出登录。

用法: python scripts/smoke_auth_frozen.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(r"E:\巡检助手\dist\昊云网络巡检助手")
EXE = ROOT / "启动巡检助手.exe"
PORT = 8785
BASE = f"http://127.0.0.1:{PORT}"

results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  <- {detail}" if detail and not ok else ""))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    # 0. 包内必须自带 config/auth.yaml(默认凭据随包分发)
    check((ROOT / "config" / "auth.yaml").exists(), "包内含 config/auth.yaml")

    env = {k: v for k, v in os.environ.items()
           if k not in ("PATROL_WEB_PASSWORD", "PATROL_WEB_USER")}
    env["PATROL_NO_BROWSER"] = "1"
    env["PATROL_PORT"] = str(PORT)

    proc = subprocess.Popen([str(EXE), "--web"], cwd=str(ROOT), env=env)
    try:
        with httpx.Client(base_url=BASE, follow_redirects=False, timeout=5) as c:
            # 等服务就绪(认证开启时登录页 200)
            up = None
            for _ in range(60):
                try:
                    up = c.get("/ui/login")
                    if up.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.5)
            else:
                raise SystemExit("服务未启动")

            # 1. 未认证:浏览器路径 302、API 401、静态资源放行
            r = c.get("/ui")
            check(r.status_code == 302 and r.headers.get("location") == "/ui/login",
                  "未登录访问 /ui → 302 登录页", f"{r.status_code} {r.headers.get('location')}")
            r = c.get("/static/vendor/bootstrap.min.css")
            check(r.status_code == 200, "登录页样式 /static 免认证 200", str(r.status_code))
            r = c.get("/devices")
            check(r.status_code == 401, "API 未认证 → 401", str(r.status_code))

            # 2. 登录页带默认账号提示且样式完整
            assert up is not None
            check("admin123" in up.text, "登录页展示默认账号提示")
            check("form-control" in up.text, "登录页样式完整(未被 401 拦截)")

            # 3. 错误密码被拒
            r = c.post("/ui/login", data={"username": "admin", "password": "wrong"})
            check(r.status_code == 303 and "error=" in r.headers.get("location", ""),
                  "错误密码 → 303 带错误提示", r.headers.get("location", ""))

            # 4. 默认账号登录成功(Cookie 进客户端会话罐,后续请求自动携带)
            r = c.post("/ui/login", data={"username": "admin", "password": "admin123"})
            cookie = r.headers.get("set-cookie", "")
            check(r.status_code == 303 and "patrol_session=" in cookie and "HttpOnly" in cookie,
                  "admin/admin123 登录 → 303 + HttpOnly 会话 Cookie", f"{r.status_code}")
            r = c.get("/ui")
            check(r.status_code == 200 and "退出登录" in r.text,
                  "持 Cookie 访问 /ui → 200 且导航含退出登录", str(r.status_code))
            r = c.get("/devices")
            check(r.status_code == 200, "持 Cookie 访问 API → 200", str(r.status_code))
            r = c.get("/ui/settings")
            check(r.status_code == 200 and "账号安全" in r.text,
                  "设置页含账号安全卡片", str(r.status_code))

            # 5. 设置页改密:旧会话立即失效,新密码可登录
            r = c.post("/ui/settings/account", data={
                "current_password": "admin123",
                "new_username": "",
                "new_password": "newpass2026",
                "new_password2": "newpass2026",
            })
            check(r.status_code == 303 and "account_msg=" in r.headers.get("location", ""),
                  "改密成功(account_msg)", r.headers.get("location", ""))
            r = c.get("/ui")  # 会话罐里仍是改密前的旧 Cookie
            check(r.status_code == 302, "改密后旧会话立即失效 → 302", str(r.status_code))
            r = c.post("/ui/login", data={"username": "admin", "password": "newpass2026"})
            check(r.status_code == 303 and "patrol_session=" in r.headers.get("set-cookie", ""),
                  "新密码登录成功", str(r.status_code))
            r = c.get("/ui/logout")
            check(r.status_code == 303 and r.headers.get("location") == "/ui/login",
                  "退出登录 → 303 登录页", r.headers.get("location", ""))

        # 6. 凭据未明文落盘
        text = (ROOT / "config" / "auth.yaml").read_text(encoding="utf-8")
        check("password_hash: pbkdf2_sha256$" in text and "newpass2026" not in text,
              "auth.yaml 密码散列存储(无明文)")
    finally:
        subprocess.run(["taskkill", "/f", "/t", "/pid", str(proc.pid)], capture_output=True)

    # 7. 还原包内默认凭据(冒烟改过密码),保证交付物仍是 admin/admin123
    src = Path(r"E:\巡检助手\config\auth.yaml")
    (ROOT / "config" / "auth.yaml").write_bytes(src.read_bytes())
    check((ROOT / "config" / "auth.yaml").read_bytes() == src.read_bytes(),
          "交付物凭据已还原为默认(散列形态)")

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 项通过")
    if failed:
        print("失败项:", failed)
        return 1
    print("绿色包 Web 访问认证闭环冒烟全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
