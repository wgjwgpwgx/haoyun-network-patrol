"""桌面小工具业务服务层(不依赖 tkinter)

把设备/客户/报告/AI/软件更新/账号等操作从界面层剥离,与 Web 端共用
同一套存储与校验规则,便于无界面单测。所有函数按相对路径读写
config/ 与 output/(启动器已 chdir 到程序根目录)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from patrol.api.store import CustomerStore, DeviceStore

OUTPUT_DIR = Path("output")


# ── 通用 ────────────────────────────────────────────────────────


def vendor_options() -> list[dict]:
    """厂商/设备类型选项(与 Web 端下拉框同一来源)。"""
    from patrol.api.ui import _vendor_options

    return _vendor_options()


def safe_report_name(filename: str) -> bool:
    """报告文件名防护:仅接受 output 下的纯 .html 文件名。"""
    return (
        bool(filename)
        and ".." not in filename
        and "/" not in filename
        and "\\" not in filename
        and filename.endswith(".html")
    )


def open_path(path: Path | str) -> None:
    """用系统默认程序打开文件/目录(报告文件交付物、配置目录等)。"""
    import os
    import subprocess

    p = str(path)
    if hasattr(os, "startfile"):  # Windows
        os.startfile(p)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", p], check=False)  # noqa: S603,S607
    else:  # Linux/其他:桌面环境标准打开方式
        subprocess.run(["xdg-open", p], check=False)  # noqa: S603,S607


# ── 设备/客户 ──────────────────────────────────────────────────


def autodetect(host: str, username: str, password: str,
               login_method: str = "ssh", port: int = 0) -> dict:
    """设备自动识别(U-2):登录执行 version 判厂商/型号。"""
    from patrol.autodetect import probe_device

    return probe_device(host, username, password, login_method=login_method,
                        port=port or None)


def save_device(
    devices: DeviceStore,
    customers: CustomerStore,
    name: str | None,
    fields: dict[str, Any],
) -> None:
    """新增(name 为 None)或更新设备;校验规则与 Web 端一致。

    fields 键:name/customer/host/vendor/device_type/login_method/port/
    web_port/username/password/super_password/timeout/command_timeout/
    verify_ssl/enabled。新增时 name/username/password 必填;
    更新时 password/super_password 留空表示保持原值。
    """
    from patrol.models import validate_host

    host = str(fields.get("host") or "").strip()
    validate_host(host)
    customer = str(fields.get("customer") or "").strip()
    if customer and customers.get(customer) is None:
        raise ValueError(f"归属客户不存在: {customer},请先在客户管理中添加")

    username = str(fields.get("username") or "").strip()
    password = str(fields.get("password") or "")
    super_password = str(fields.get("super_password") or "")
    payload: dict[str, Any] = {
        "customer": customer,
        "host": host,
        "vendor": str(fields.get("vendor") or "h3c"),
        "device_type": str(fields.get("device_type") or "comware_switch"),
        "login_method": str(fields.get("login_method") or "ssh"),
        "port": int(fields.get("port") or 22),
        "web_port": int(fields.get("web_port") or 443),
        "username": username,
        "timeout": int(fields.get("timeout") or 30),
        "command_timeout": int(fields.get("command_timeout") or 120),
        "verify_ssl": bool(fields.get("verify_ssl", True)),
        "enabled": bool(fields.get("enabled", True)),
    }

    if name is None:
        new_name = str(fields.get("name") or "").strip()
        if not new_name:
            raise ValueError("设备名称不能为空")
        if not username:
            raise ValueError("登录用户名不能为空")
        if not password:
            raise ValueError("登录密码不能为空")
        devices.create(
            {"name": new_name, "password": password,
             "super_password": super_password, **payload}
        )
    else:
        updates = dict(payload)
        if password:
            updates["password"] = password
        if super_password:
            updates["super_password"] = super_password
        devices.update(name, updates)


def smtp_config() -> dict:
    """读取 config/smtp.yaml(缺省空配置)。"""
    import yaml

    path = Path("config/smtp.yaml")
    if not path.exists():
        return {"enabled": False}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def send_report_email(recipients: list, subject: str, body: str,
                      attachments: list, cc: list | None = None) -> dict:
    """发送带报告附件的邮件(收件人由调用方从客户档案取)。

    返回 {ok, message};配置缺失/发送失败抛 RuntimeError(文案面向用户)。
    """
    cfg = smtp_config()
    if not cfg.get("enabled"):
        raise RuntimeError("邮件分发未启用:请编辑 config/smtp.yaml 配置并 enabled: true")
    if not cfg.get("host") or not cfg.get("username"):
        raise RuntimeError("SMTP 配置不完整:缺少 host 或 username")
    if not recipients:
        raise RuntimeError("接收人为空:请在客户管理中填写客户邮箱")
    try:
        return _send_report_email_impl(cfg, recipients, cc or [], subject,
                                       body, attachments)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001 - 用户可见
        raise RuntimeError(f"邮件发送失败:{e}") from e


def _send_report_email_impl(cfg: dict, recipients: list, cc: list,
                            subject: str, body: str,
                            attachments: list) -> dict:
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = cfg.get("from") or cfg.get("username", "")
    msg["To"] = ",".join(recipients)
    if cc:
        msg["Cc"] = ",".join(cc)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for path in attachments:
        p = Path(path)
        with open(p, "rb") as f:
            part = MIMEApplication(f.read())
        part.add_header("Content-Disposition", "attachment",
                        filename=Path(p).name)
        msg.attach(part)

    port = int(cfg.get("port", 465))
    if cfg.get("ssl", port == 465):
        server = smtplib.SMTP_SSL(cfg["host"], port, timeout=30)
    else:
        server = smtplib.SMTP(cfg["host"], port, timeout=30)
        if cfg.get("starttls", port == 587):
            server.starttls()
    try:
        server.login(cfg["username"], cfg["password"])
        server.sendmail(msg["From"], recipients + cc, msg.as_string())
    finally:
        server.quit()
    return {"ok": True, "message": f"已发送至 {len(recipients)} 位接收人"}


def save_customer(
    customers: CustomerStore,
    devices: DeviceStore,
    orig_name: str | None,
    fields: dict[str, Any],
) -> None:
    """新增(orig_name 为 None)或修改客户;重命名时同步设备归属引用。"""
    data = {
        "name": str(fields.get("name") or "").strip(),
        "contact": str(fields.get("contact") or "").strip(),
        "phone": str(fields.get("phone") or "").strip(),
        "email": str(fields.get("email") or "").strip(),
        "remark": str(fields.get("remark") or "").strip(),
    }
    if not data["name"]:
        raise ValueError("客户名称不能为空")
    if orig_name:
        updated = customers.update(orig_name, data)
        if updated["name"] != orig_name:
            for d in devices.list():
                if d.get("customer") == orig_name:
                    devices.update(d["name"], {"customer": updated["name"]})
    else:
        customers.create(data)


def device_count_by_customer(devices: DeviceStore) -> dict[str, int]:
    """各客户名下设备数。"""
    counts: dict[str, int] = {}
    for d in devices.list():
        cname = d.get("customer", "")
        if cname:
            counts[cname] = counts.get(cname, 0) + 1
    return counts


def task_summary(tasks: list[dict]) -> dict[str, int]:
    """任务状态计数(pending/running/completed/failed)。"""
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for t in tasks:
        status = t.get("status", "")
        if status in counts:
            counts[status] += 1
    return counts


# ── 报告 ────────────────────────────────────────────────────────


def list_reports(output_dir: Path = OUTPUT_DIR) -> list[dict]:
    """报告列表(与 Web 端字段一致:name/size/modified/has_preview/has_ai)。"""
    reports: list[dict] = []
    if not output_dir.exists():
        return reports
    for f in sorted(output_dir.glob("*.html"), reverse=True):
        size = f.stat().st_size
        modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        json_path = f.with_suffix(".json")
        has_ai = False
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                has_ai = bool(data.get("ai_analysis"))
            except (ValueError, OSError):
                pass
        reports.append({
            "name": f.name,
            "size": f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB",
            "modified": modified,
            "has_preview": json_path.exists(),
            "has_ai": has_ai,
        })
    return reports


def load_report_data(filename: str, output_dir: Path = OUTPUT_DIR) -> dict:
    """读取报告结构化数据(伴生 .json);文件名不合法抛 ValueError。"""
    if not safe_report_name(filename):
        raise ValueError("非法的报告文件名")
    json_path = output_dir / filename.replace(".html", ".json")
    if not json_path.exists():
        raise FileNotFoundError("缺少报告数据文件(.json),无法预览")
    return json.loads(json_path.read_text(encoding="utf-8"))


def report_summary(data: dict) -> dict:
    """汇总报告数据:通过/失败/未知计数、风险项与 AI 结论。"""
    total_pass = sum(d.get("pass_count", 0) for d in data.get("devices", []))
    total_fail = sum(d.get("fail_count", 0) for d in data.get("devices", []))
    total_unknown = sum(d.get("unknown_count", 0) for d in data.get("devices", []))

    fail_items = []
    for dev in data.get("devices", []):
        for item in dev.get("check_items", []):
            if item.get("status") == "FAIL":
                fail_items.append({
                    "device_name": dev.get("name", ""),
                    "category": item.get("category", ""),
                    "message": item.get("message", ""),
                    "severity": item.get("details", {}).get("severity", "warning"),
                    "suggestion": item.get("details", {}).get("suggestion", ""),
                })
    return {
        "total_pass": total_pass,
        "total_fail": total_fail,
        "total_unknown": total_unknown,
        "fail_items": fail_items,
        "ai": data.get("ai_analysis") or {},
    }


def delete_reports(filenames: list[str], output_dir: Path = OUTPUT_DIR) -> int:
    """删除报告 HTML 及伴生 JSON(不合法文件名静默跳过),返回删除数。"""
    count = 0
    for filename in filenames:
        if not safe_report_name(filename):
            continue
        html_path = output_dir / filename
        json_path = html_path.with_suffix(".json")
        removed = False
        for p in (html_path, json_path):
            if p.exists():
                p.unlink()
                removed = True
        if removed:
            count += 1
    return count


def run_ai_analysis(filename: str, output_dir: Path = OUTPUT_DIR) -> None:
    """对已有报告执行/重跑 AI 分析,同步更新 JSON 与 HTML。

    失败抛 RuntimeError(ValueError 为文件名不合法),文案面向用户。
    """
    from patrol.ai import AINotConfigured, analyze_report, load_ai_config
    from patrol.reporter.html import HTMLReporter
    from patrol.reporter.rebuild import rebuild_report

    if not safe_report_name(filename):
        raise ValueError("非法的报告文件名")
    json_path = output_dir / filename.replace(".html", ".json")
    if not json_path.exists():
        raise RuntimeError("缺少报告数据文件,无法分析")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        report = rebuild_report(data)
        result = analyze_report(report, load_ai_config())
    except AINotConfigured:
        raise RuntimeError("AI 分析未启用,请先在「系统设置 → AI 大模型分析」中配置") from None
    except Exception as e:  # noqa: BLE001 - 用户可见的失败提示
        raise RuntimeError(f"AI 分析失败: {e}") from e

    data["ai_analysis"] = result
    report.ai_analysis = result
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    html_path = output_dir / filename
    if html_path.exists():
        HTMLReporter().generate(report, html_path)


def export_word(filename: str, output_dir: Path = OUTPUT_DIR,
                formal: bool = False) -> Path:
    """从 JSON 数据生成 Word 报告(formal=True 为正式汇报版),返回生成路径。"""
    from patrol.reporter.rebuild import rebuild_report
    from patrol.reporter.word import (
        WordReporter, build_report_meta, generate_word_filename,
    )

    data = load_report_data(filename, output_dir)
    report = rebuild_report(data)
    word_name = generate_word_filename(report)
    if formal:
        word_name = word_name.replace("巡检报告_", "巡检报告(正式版)_", 1)
    word_path = output_dir / word_name
    WordReporter().generate(report, word_path,
                            meta=build_report_meta(report, formal=formal))
    from patrol.utils.archive import archive_report
    archive_report(word_path, report.devices[0].asset.customer
                   if report.devices else "")
    return word_path


def export_excel(filename: str, output_dir: Path = OUTPUT_DIR) -> Path:
    """从 JSON 数据生成 Excel 台账报告(模板三),返回生成路径。"""
    from patrol.reporter.excel import ExcelReporter, generate_excel_filename
    from patrol.reporter.rebuild import rebuild_report

    data = load_report_data(filename, output_dir)
    report = rebuild_report(data)
    excel_path = output_dir / generate_excel_filename(report)
    ExcelReporter().generate(report, excel_path)
    from patrol.utils.archive import archive_report
    archive_report(excel_path, report.devices[0].asset.customer
                   if report.devices else "")
    return excel_path


def export_pdf(filename: str, output_dir: Path = OUTPUT_DIR) -> Path:
    """从 JSON 数据生成 PDF 报告;无转换环境抛 RuntimeError。"""
    from patrol.reporter.pdf import (
        PDFReporter,
        check_pdf_capability,
        generate_pdf_filename,
    )
    from patrol.reporter.rebuild import rebuild_report

    caps = check_pdf_capability()
    if not any(caps.values()):
        raise RuntimeError("PDF 转换不可用,需要安装 Microsoft Word 或 LibreOffice")
    data = load_report_data(filename, output_dir)
    report = rebuild_report(data)
    pdf_path = output_dir / generate_pdf_filename(report)
    PDFReporter().generate(report, pdf_path)
    return pdf_path


def format_ai_conclusion(ai: dict) -> str:
    """把 AI 结论渲染成文本(预览窗口用);含逐台融合评估。"""
    if not ai:
        return ""
    from patrol.ai import risk_label_cn

    lines = [
        f"健康评分: {ai.get('health_score', '—')}    "
        f"综合风险: {risk_label_cn(str(ai.get('overall_risk') or '—'))}",
        "",
        "【结论摘要】",
        str(ai.get("executive_summary") or "—"),
    ]
    for a in ai.get("device_assessments") or []:
        if isinstance(a, dict) and a.get("device") and a.get("assessment"):
            lines.append(f"  · {a['device']}:{a['assessment']}")
    for key, title in (
        ("key_findings", "关键发现"),
        ("recommendations", "处置建议"),
        ("maintenance_suggestions", "维护建议"),
    ):
        items = ai.get(key) or []
        lines += ["", f"【{title}】"]
        if isinstance(items, list):
            for i, it in enumerate(items, 1):
                lines.append(f"{i}. {it}")
        else:
            lines.append(str(items))
    return "\n".join(lines)


# ── AI 配置 ────────────────────────────────────────────────────


def ai_load_raw() -> dict:
    """读取 config/ai.yaml 原始字段(不含环境变量覆盖)。"""
    from patrol.api.settings_ui import _load_ai_dict

    return _load_ai_dict()


def ai_masked_key() -> str:
    """API Key 掩码展示。"""
    from patrol.api.settings_ui import _mask_key

    return _mask_key(str(ai_load_raw().get("api_key") or ""))


def ai_save(enabled: bool, base_url: str, api_key: str, model: str) -> None:
    """保存 AI 配置(api_key 留空保持原值);校验同 Web 端。"""
    from patrol.api.settings_ui import _save_ai_dict

    data = ai_load_raw()
    base_url = (base_url or "").strip()
    model = (model or "").strip()
    if enabled and not base_url:
        raise ValueError("接口地址不能为空")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ValueError("接口地址需以 http:// 或 https:// 开头")

    new_key = (api_key or "").strip()
    if new_key:
        data["api_key"] = new_key
    data["enabled"] = bool(enabled)
    if base_url:
        data["base_url"] = base_url
    if model:
        data["model"] = model
    for field, default in (("timeout", 120), ("max_tokens", 4096), ("temperature", 0.2)):
        data.setdefault(field, default)
    _save_ai_dict(data)


def ai_test(base_url: str, api_key: str, model: str) -> dict:
    """测试连通(不落盘),同 Web 端。返回 {ok, message}。"""
    import time

    from patrol.ai.client import LLMClient, LLMError
    from patrol.ai.config import AIConfig

    base_url = (base_url or "").strip()
    model = (model or "").strip()
    key = (api_key or "").strip() or str(ai_load_raw().get("api_key") or "")

    if not base_url:
        return {"ok": False, "message": "请先选择厂商或填写接口地址"}
    if not key:
        return {"ok": False, "message": "请先填写 API Key(Ollama 本地可随意填非空值)"}
    if not model:
        return {"ok": False, "message": "请先填写模型名"}

    cfg = AIConfig(enabled=True, base_url=base_url, api_key=key,
                   model=model, timeout=30, max_tokens=8)
    try:
        t0 = time.monotonic()
        reply = LLMClient(cfg).chat(
            [{"role": "user", "content": "连通性测试,请只回复:OK"}]
        )
        elapsed = time.monotonic() - t0
        return {
            "ok": True,
            "message": f"连接成功({elapsed:.1f}s),模型响应:{reply.strip()[:60]}",
        }
    except LLMError as e:
        return {"ok": False, "message": f"连接失败:{e}"}


# ── 软件更新 ───────────────────────────────────────────────────


def check_update() -> dict:
    """拉取更新清单并附检查时间。"""
    from patrol.update import check_for_update

    result = check_for_update()
    result["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return result


def download_update(result: dict | None = None) -> dict:
    """下载更新包并暂存(支持 sha256 校验);无可用更新抛 RuntimeError。"""
    from patrol.updater import UpdateError, download_package, stage_update

    result = result if result is not None else check_update()
    if result.get("status") != "available":
        raise RuntimeError("当前没有可用更新,无需下载安装")
    try:
        zip_path = download_package(
            result["url"], result["latest"], expected_sha256=result.get("sha256", "")
        )
        stage_update(zip_path, result["latest"])
    except UpdateError as e:
        raise RuntimeError(str(e)) from e
    return {
        **result,
        "status": "downloaded",
        "message": f"更新包 v{result['latest']} 已下载并校验,点击「重启并安装」完成更新",
    }


def install_update() -> str:
    """启动替换脚本并退出主程序(仅绿色版可用);返回待装版本号。"""
    from patrol.updater import UpdateError, install_now, load_pending

    pending = load_pending()
    if pending is None:
        raise RuntimeError("没有待安装的更新包,请先点击「下载并安装」")
    try:
        install_now()
    except UpdateError as e:
        raise RuntimeError(str(e)) from e
    return str(pending.get("version", ""))


# ── 账号(网页访问模式) ────────────────────────────────────────


def auth_status() -> dict:
    """网页登录状态(mode/mode_label/username)。"""
    from patrol.api.auth import auth_status as _status

    return _status()


def change_account(
    current_password: str,
    new_username: str | None,
    new_password: str | None,
) -> str:
    """修改网页登录账号;失败抛 ValueError。"""
    from patrol.api.auth import change_account as _change

    return _change(current_password, new_username, new_password)


def run_async(work: Callable[[], Any], on_done: Callable[[Any], None],
              on_error: Callable[[Exception], None]) -> None:
    """后台线程执行 work(),回调在调用方线程触发(界面用 widgets.run_in_thread)。"""
    import threading

    def _runner() -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - 汇报给调用方
            on_error(exc)
            return
        on_done(result)

    threading.Thread(target=_runner, daemon=True).start()


# ── 定时巡检(销号清单 #13b:Windows 计划任务) ─────────────────

SCHEDULE_TASK_NAME = "HaoyunPatrolSchedule"


def _schedule_tr() -> str:
    """构造计划任务命令行:切到程序根目录后执行全量巡检(CLI)。"""
    import sys

    from patrol.launcher import app_root, is_frozen

    root = app_root()
    if is_frozen():
        exe = f'"{sys.executable}"'
        inner = f'{exe} run'
    else:
        inner = f'"{sys.executable}" -m patrol'
    # cmd /c 先 cd 再执行,保证 config/output 相对路径正确
    return f'cmd /c cd /d "{root}" && {inner}'


def schedule_status() -> dict:
    """查询计划任务安装状态 {installed, weekly}。"""
    import subprocess

    r = subprocess.run(  # noqa: S603
        ["schtasks", "/Query", "/TN", SCHEDULE_TASK_NAME],
        capture_output=True, text=True)
    installed = r.returncode == 0
    weekly = installed and "每周" in (r.stdout or "") or \
        installed and "Weekly" in (r.stdout or "")
    return {"installed": installed, "weekly": weekly}


def install_schedule(weekly: bool = True) -> None:
    """安装计划任务:每周三 02:00 / 每月 1 日 02:00 全量巡检。"""
    import subprocess
    import sys

    if not sys.platform == "win32":
        raise RuntimeError("定时巡检仅支持 Windows")
    args = ["schtasks", "/Create", "/F", "/TN", SCHEDULE_TASK_NAME,
            "/ST", "02:00", "/TR", _schedule_tr()]
    if weekly:
        args += ["/SC", "WEEKLY", "/D", "WED"]
    else:
        args += ["/SC", "MONTHLY", "/D", "1"]
    r = subprocess.run(args, capture_output=True, text=True)  # noqa: S603
    if r.returncode != 0:
        raise RuntimeError(f"计划任务创建失败: {(r.stderr or r.stdout).strip()}")


def remove_schedule() -> None:
    """卸载计划任务(未安装时静默成功)。"""
    import subprocess

    subprocess.run(  # noqa: S603
        ["schtasks", "/Delete", "/F", "/TN", SCHEDULE_TASK_NAME],
        capture_output=True, text=True)
