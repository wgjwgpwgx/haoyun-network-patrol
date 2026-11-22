"""Windows DPAPI 凭据加密(销号清单 #12)

设备档案中的 password/super_password/api_token 落盘加密
(CryptProtectData,绑定当前 Windows 用户),内存中始终明文,
业务层无感。非 Windows 平台自动降级为明文(启动时提示一次)。
兼容旧明文:读取时无 enc$ 前缀按明文处理。
"""
from __future__ import annotations

import base64
import logging
import sys

logger = logging.getLogger(__name__)

PREFIX = "enc$"
_FIELDS = ("password", "super_password", "api_token")

_IS_WINDOWS = sys.platform == "win32"
_crypt32 = None
if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wt

    _crypt32 = ctypes.WinDLL("Crypt32.dll")
    _kernel32 = ctypes.WinDLL("Kernel32.dll")


class _DATA_BLOB(ctypes.Structure):
    if _IS_WINDOWS:
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> "_DATA_BLOB":
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _unblob(blob: "_DATA_BLOB") -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    _kernel32.LocalFree(blob.pbData)
    return out


def protect(plain: str) -> str:
    """加密字符串,返回 enc$base64;非 Windows 原样返回。"""
    if not _IS_WINDOWS or not plain:
        return plain
    inp = _blob(plain.encode("utf-8"))
    out = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        logger.warning("DPAPI 加密失败,字段将明文保存")
        return plain
    return PREFIX + base64.b64encode(_unblob(out)).decode("ascii")


def unprotect(value: str) -> str:
    """解密 enc$base64;无前缀(旧明文)原样返回。"""
    if not value or not value.startswith(PREFIX):
        return value
    if not _IS_WINDOWS:
        return ""  # 跨平台拿到密文无法解,宁空勿错
    try:
        inp = _blob(base64.b64decode(value[len(PREFIX):]))
        out = _DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
        return _unblob(out).decode("utf-8") if ok else ""
    except Exception:  # noqa: BLE001 - 解密失败不致命
        logger.warning("DPAPI 解密失败,字段按空处理")
        return ""


def encrypt_device_dict(device: dict) -> dict:
    """落盘前:凭据三字段加密(返回副本,不改原 dict)。"""
    out = dict(device)
    for f in _FIELDS:
        v = out.get(f)
        if v and not str(v).startswith(PREFIX):
            out[f] = protect(str(v))
    return out


def decrypt_device_dict(device: dict) -> dict:
    """读盘后:凭据三字段解密(原地更新并返回)。"""
    for f in _FIELDS:
        v = device.get(f)
        if v and str(v).startswith(PREFIX):
            device[f] = unprotect(str(v))
    return device
