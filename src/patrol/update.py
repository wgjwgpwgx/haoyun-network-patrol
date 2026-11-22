"""软件更新检查

更新源为一个 JSON 清单(manifest)，格式:
    {
        "version": "0.2.0",              # 最新版本号(必填)
        "url": "https://.../xx-绿色版.zip", # 更新包下载地址(可选)
        "notes": "更新说明(可选)"
    }

清单支持 http(s) 地址与本地文件路径(便于内网/离线分发)。
更新源地址保存在 config/settings.yaml 的 update_manifest_url 字段。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

_SETTINGS_PATH = Path("config") / "settings.yaml"


def load_update_url(settings_path: str | Path | None = None) -> str:
    """读取更新源地址(未配置时返回空串)。"""
    path = Path(settings_path) if settings_path else _SETTINGS_PATH
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if isinstance(data, dict):
        return str(data.get("update_manifest_url") or "").strip()
    return ""


def save_update_url(url: str, settings_path: str | Path | None = None) -> None:
    """保存更新源地址(仅更新该字段，保留其余设置)。"""
    path = Path(settings_path) if settings_path else _SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except yaml.YAMLError:
            data = {}
    data["update_manifest_url"] = url.strip()
    header = (
        "# 软件设置(系统设置页面自动保存)\n"
        "# update_manifest_url: 更新清单 JSON 地址,支持 http(s) 或本地文件路径\n"
        '# 清单格式: {"version": "0.2.0", "url": "https://.../更新包.zip", "notes": "更新说明", "sha256": "可选校验和"}\n'
    )
    from patrol.utils.fs import atomic_write_text

    atomic_write_text(
        path, header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    )


def parse_version(text: str) -> tuple[int, ...]:
    """把 'v0.2.0' / '0.10.1' 之类的版本号解析为可比较的元组。"""
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def _fetch_manifest(url: str, timeout: float) -> dict[str, Any]:
    """拉取更新清单:http(s) 走网络,其余按本地文件路径处理。"""
    if re.match(r"^https?://", url, re.IGNORECASE):
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            text = resp.text
    else:
        text = Path(url).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("更新清单格式错误(应为 JSON 对象)")
    return data


def check_for_update(
    manifest_url: str | None = None,
    current: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """检查更新,返回结构化结果。

    status 取值:
      unconfigured - 未配置更新源
      uptodate     - 已是最新版本
      available    - 发现新版本(带下载地址)
      error        - 检查失败(网络/清单异常)
    """
    from patrol import __version__ as pkg_version

    cur = (current or pkg_version).strip()
    url = manifest_url if manifest_url is not None else load_update_url()
    result: dict[str, Any] = {
        "status": "error",
        "current": cur,
        "latest": "",
        "url": "",
        "notes": "",
        "sha256": "",
        "message": "",
    }

    if not url:
        result["status"] = "unconfigured"
        result["message"] = "未配置更新源，请先在上方填写更新清单地址"
        return result

    try:
        manifest = _fetch_manifest(url, timeout)
        latest = str(manifest.get("version") or "").strip()
        if not latest:
            raise ValueError("更新清单缺少 version 字段")
        result["latest"] = latest
        result["url"] = str(manifest.get("url") or "").strip()
        result["notes"] = str(manifest.get("notes") or "").strip()
        result["sha256"] = str(manifest.get("sha256") or "").strip()

        if parse_version(latest) > parse_version(cur):
            result["status"] = "available"
            result["message"] = f"发现新版本 v{latest}，请下载更新包完成升级"
        else:
            result["status"] = "uptodate"
            result["message"] = f"已是最新版本(v{cur})"
    except Exception as e:  # 网络/解析异常统一转为友好提示
        result["status"] = "error"
        result["message"] = f"检查更新失败: {e}"

    return result
