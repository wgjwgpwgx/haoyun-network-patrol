"""字段智能识别:表头同义词(高置信)+ 内容特征(兜底)双层引擎"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── 目标字段与同义词表(归一化后匹配:全半角/空格/大小写统一) ──────

FIELD_SYNONYMS: dict[str, set[str]] = {
    "host": {"ip", "地址", "管理地址", "管理ip", "ip地址", "设备ip", "设备地址",
             "运维地址", "网络地址", "host", "address", "登录地址", "主机地址"},
    "username": {"用户名", "账号", "帐号", "登录名", "登录账号", "登录帐号",
                 "设备账号", "设备帐号", "管理员账号", "ssh账号", "username",
                 "user", "登录用户名"},
    "password": {"密码", "口令", "一级密码", "登录密码", "登录口令", "设备密码",
                 "ssh密码", "password", "pwd", "pass", "登录密码"},
    "super_password": {"super密码", "super口令", "super", "二级密码", "特权密码",
                       "特权口令", "enable密码", "enablepassword", "enable",
                       "supassword", "superpassword"},
    "name": {"设备名", "设备名称", "名称", "主机名", "hostname", "设备别名",
             "别名", "节点名", "nodename", "设备"},
    "login_method": {"登录方式", "接入方式", "连接方式", "登录类型", "方式",
                     "协议", "logintype", "loginmethod", "method"},
    "vendor": {"厂商", "品牌", "vendor", "厂家", "供应商", "设备厂商"},
    "device_type": {"设备类型", "类型", "devicetype", "型号类型", "设备型号类型"},
    "port": {"端口", "port", "ssh端口", "管理端口", "登录端口"},
    "customer": {"单位", "客户", "公司", "甲方", "归属", "单位名称", "客户名称",
                 "客户单位", "所属单位", "customer"},
    "remark": {"备注", "说明", "remark", "note", "注释", "位置", "机房", "机柜"},
}

# 密码类字段:内容特征层无法区分一级/super,只给 password 评特征分
CONTENT_DETECTABLE = ("host", "port", "login_method", "username", "password")

REQUIRED_FIELDS = ("host", "username", "password")

_IPV4 = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}$")
_LOGIN_METHOD_VALUES = {
    "ssh": "ssh", "telnet": "telnet", "web": "web", "网页": "web",
    "网页采集": "web", "api": "api", "接口": "api", "console": "console",
    "串口": "console", "console口": "console",
}
_USERNAME_HINTS = ("admin", "root", "net", "ops", "sys", "run", "super", "user")


def normalize(text: str) -> str:
    """归一化:全角→半角、去所有空白、统一小写(容忍"管 理 地 址"这类表头)。"""
    out = []
    for ch in str(text or ""):
        code = ord(ch)
        if code == 0x3000:
            code = 32
        elif 0xFF01 <= code <= 0xFF5E:
            code -= 0xFEE0
        out.append(chr(code))
    return "".join(out).strip().lower().replace(" ", "").replace("	", "")


@dataclass
class ColumnMatch:
    """一个字段到表格列的映射结果"""
    field: str
    column: int          # 列下标(0 起)
    header: str          # 原始表头(或占位列名)
    confidence: float    # 0~1,<0.8 时预览界面标黄
    reason: str          # 识别依据说明(预览界面展示)


def looks_like_header(row: list[str]) -> bool:
    """首行是否像表头:任一单元格命中同义词(精确)即认定。"""
    for cell in row:
        n = normalize(cell)
        if not n:
            continue
        for syns in FIELD_SYNONYMS.values():
            if n in syns:
                return True
    return False


def _content_score(field: str, values: list[str]) -> tuple[float, str] | None:
    """内容特征评分:返回 (置信度, 依据) 或 None。values 为非空样本。"""
    if not values:
        return None
    n = len(values)

    if field == "host":
        hits = sum(1 for v in values if _IPV4.match(v))
        rate = hits / n
        if rate >= 0.6:
            return 0.9, f"{hits}/{n} 行为 IP 地址格式"

    if field == "port":
        ports = [v for v in values if v.isdigit() and 1 <= int(v) <= 65535]
        common = [v for v in ports if v in ("22", "23", "443", "8022", "8080")]
        if len(ports) / n >= 0.6:
            extra = ",含常见端口" if common else ""
            return 0.9, f"{len(ports)}/{n} 行为端口数值{extra}"

    if field == "login_method":
        hits = sum(1 for v in values if v.lower() in _LOGIN_METHOD_VALUES)
        if hits / n >= 0.6:
            return 0.9, f"{hits}/{n} 行取值为登录方式(ssh/telnet/web…)"

    if field == "username":
        ok = [v for v in values
              if 0 < len(v) <= 32 and " " not in v and not v.isdigit()]
        if len(ok) / n >= 0.6:
            hinted = sum(1 for v in ok if any(h in v.lower() for h in _USERNAME_HINTS))
            conf = 0.75 if hinted >= max(1, len(ok) // 2) else 0.6
            return conf, f"短文本无空格{hinted and f',{hinted} 行含常见账号词' or ''}"

    if field == "password":
        # 与"用户名"的区分:同时含 ASCII 字母与数字且较长
        # (中文设备名"核心交换1"不算,其中文 isalpha 为真但非 ASCII)
        mixed = [v for v in values
                 if len(v) >= 4 and any(c.isdigit() for c in v)
                 and any(c.isascii() and c.isalpha() for c in v)]
        if len(mixed) / n >= 0.5:
            return 0.6, f"{len(mixed)}/{n} 行为字母数字混合串(请确认为密码)"

    return None


def detect_columns(headers: list[str], rows: list[list[str]],
                   sample: int = 20) -> dict[str, ColumnMatch]:
    """双层识别:返回 {字段: ColumnMatch}。

    第一层表头同义词:精确 1.0 / 包含 0.9;
    第二层内容特征:仅对未被占用的列和未覆盖的可特征字段;
    一列只归一个字段(高置信优先,平手按列序)。
    """
    matched: dict[str, ColumnMatch] = {}
    used_cols: set[int] = set()

    def take(field: str, col: int, conf: float, reason: str) -> None:
        # 已有更高置信映射则保持
        old = matched.get(field)
        if old and old.confidence >= conf:
            return
        matched[field] = ColumnMatch(field, col, headers[col], conf, reason)
        used_cols.add(col)

    # ── 第一层:表头同义词 ─────────────────────────────────────
    for col, header in enumerate(headers):
        n = normalize(header)
        if not n:
            continue
        for field, syns in FIELD_SYNONYMS.items():
            if n in syns:
                take(field, col, 1.0, f"表头〔{header}〕精确匹配")
                break
    # 精确未命中的字段再做"包含"匹配(如"设备管理IP地址"含"管理ip")
    for col, header in enumerate(headers):
        if col in used_cols:
            continue
        n = normalize(header)
        if not n or len(n) < 2:
            continue
        for field, syns in FIELD_SYNONYMS.items():
            if field in matched:
                continue
            if any(len(s) >= 2 and s in n for s in syns):
                take(field, col, 0.9, f"表头〔{header}〕近似匹配")
                break

    # ── 第二层:内容特征(仅未占用列 + 可特征字段) ─────────────
    samples = [[(row[c] if c < len(row) else "") for c in range(len(headers))]
               for row in rows[:sample]]
    for field in CONTENT_DETECTABLE:
        if field in matched:
            continue
        best: tuple[float, int, str] | None = None
        for col in range(len(headers)):
            if col in used_cols:
                continue
            values = [r[col] for r in samples if r[col]]
            got = _content_score(field, values)
            if got and (best is None or got[0] > best[0]):
                best = (got[0], col, got[1])
        if best:
            take(field, best[1], best[0], best[2])

    return matched
