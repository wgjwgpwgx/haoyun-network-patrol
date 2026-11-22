"""真机验收预检脚本

在正式真机巡检前一次性检查:依赖、浏览器、规则文件、配置解析、设备网络连通性。
全部只读,不向设备发送任何登录请求(仅 TCP 端口探测)。

用法:
    python scripts/preflight_check.py                     # 检查 config/devices.yaml
    python scripts/preflight_check.py -c 其他配置.yaml
    python scripts/preflight_check.py --skip-net          # 跳过网络探测(离线环境)
退出码: 0=全部通过  2=存在失败项
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

# 保证能导入 src 布局的 patrol 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

PASS, FAIL, WARN, SKIP = "✓ 通过", "✗ 失败", "! 警告", "- 跳过"
failures: list[str] = []
warnings: list[str] = []


def check(name: str, fn) -> None:
    """执行一项检查并打印结果。fn 返回 (状态, 说明) 或抛异常。"""
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = FAIL, f"{type(e).__name__}: {e}"
    mark = {"pass": PASS, "fail": FAIL, "warn": WARN, "skip": SKIP}[status]
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    if status == "fail":
        failures.append(name)
    elif status == "warn":
        warnings.append(name)


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """TCP 端口连通性探测(不发任何应用层数据)。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "端口可达"
    except (TimeoutError, socket.timeout):
        return False, "连接超时"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="真机验收预检")
    parser.add_argument("-c", "--config", default="config/devices.yaml", help="设备配置文件")
    parser.add_argument("--skip-net", action="store_true", help="跳过网络连通性探测")
    args = parser.parse_args()

    print("=" * 62)
    print("巡检助手 · 真机验收预检")
    print("=" * 62)

    # ── 1. 运行环境 ─────────────────────────────────────────────
    print("\n[1/5] 运行环境")
    check("Python >= 3.10", lambda: ("pass", sys.version.split()[0])
          if sys.version_info >= (3, 10) else ("fail", f"当前 {sys.version.split()[0]}"))

    def _deps():
        missing = []
        for mod in ("netmiko", "yaml", "pydantic", "jinja2", "fastapi",
                    "uvicorn", "docx", "playwright", "requests", "textfsm"):
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
        return ("fail", f"缺少: {', '.join(missing)}") if missing else ("pass", "10 个依赖全部可导入")

    check("Python 依赖", _deps)

    def _chromium():
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        try:
            b = p.chromium.launch(headless=True)
            ver = b.version
            b.close()
            return ("pass", f"chromium {ver}")
        finally:
            p.stop()

    check("Playwright Chromium(Web 采集需要)", _chromium)

    def _pdf_cap():
        caps = {}
        try:
            import win32com.client  # noqa: F401
            caps["Microsoft Word"] = True
        except Exception:
            pass
        import shutil
        if shutil.which("soffice") or shutil.which("libreoffice"):
            caps["LibreOffice"] = True
        if caps:
            return ("pass", "PDF 可用: " + " + ".join(caps))
        return ("warn", "未检测到 Word/LibreOffice,PDF 报告将不可用(HTML/Word 不受影响)")

    check("PDF 转换能力(可选)", _pdf_cap)

    # ── 2. 配置与规则 ───────────────────────────────────────────
    print("\n[2/5] 配置文件")
    config_path = Path(args.config)

    def _config_exists():
        return ("pass", str(config_path)) if config_path.exists() else ("fail", f"不存在: {config_path}")

    check("设备配置文件存在", _config_exists)

    devices: list[dict] = []
    if config_path.exists():
        import yaml

        def _config_parse():
            nonlocal devices
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            devices = [d for d in data.get("devices", []) if d.get("enabled", True)]
            total = len(data.get("devices", []))
            return ("pass", f"共 {total} 台,启用 {len(devices)} 台(禁用 {total - len(devices)} 台)")

        check("配置解析为合法 YAML", _config_parse)

        def _config_fields():
            bad = []
            for d in devices:
                for k in ("name", "host", "vendor", "device_type", "username"):
                    if not d.get(k):
                        bad.append(f"{d.get('name', '?')} 缺 {k}")
            return ("fail", "; ".join(bad)) if bad else ("pass", "启用设备关键字段齐全")

        check("设备必填字段", _config_fields)

    print("\n[3/5] 规则文件")
    rules_dir = Path("config/rules")
    for rf in sorted(rules_dir.glob("*.yaml")):
        def _rule(rf=rf):
            import yaml
            data = yaml.safe_load(rf.read_text(encoding="utf-8")) or {}
            n = len(data.get("rules", []))
            return ("pass", f"{n} 条规则") if n else ("warn", "规则为空")
        check(f"规则文件 {rf.name}", _rule)

    print("\n[4/5] 输出目录")
    out = Path("output")

    def _outdir():
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return ("pass", f"{out.resolve()} 可写")

    check("输出目录可写", _outdir)

    # ── 5. 设备连通性 ───────────────────────────────────────────
    print("\n[5/5] 设备网络连通性(TCP 探测,不登录)")
    if args.skip_net:
        print(f"  [{SKIP}] 已按参数跳过")
    elif not devices:
        print(f"  [{SKIP}] 无启用设备")
    else:
        for d in devices:
            method = d.get("login_method", "ssh")
            port = d.get("port", 22) if method == "ssh" else d.get("web_port", 443)
            host = d.get("host", "")

            def _probe(host=host, port=port):
                ok, msg = tcp_probe(host, int(port))
                return ("pass" if ok else "fail", f"{host}:{port} ({method}) {msg}")

            check(f"设备「{d.get('name', '?')}」", _probe)

    # ── 汇总 ────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print(f"预检结果: 失败 {len(failures)} 项 / 警告 {len(warnings)} 项")
    if failures:
        print("失败项(必须解决后再进行真机验收):")
        for f in failures:
            print(f"  - {f}")
        return 2
    print("关键项全部通过,可以开始真机验收。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
