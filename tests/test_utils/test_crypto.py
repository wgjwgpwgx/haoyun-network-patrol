"""凭据 DPAPI 加密测试(销号清单 #12):磁盘密文/内存明文/兼容旧明文。"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from patrol.api.store import DeviceStore
from patrol.utils.crypto import (
    PREFIX, decrypt_device_dict, encrypt_device_dict, protect, unprotect,
)

WIN = sys.platform == "win32"


def test_roundtrip():
    if not WIN:
        return  # DPAPI 仅 Windows
    enc = protect("s3cret-Pw")
    assert enc.startswith(PREFIX) and "s3cret" not in enc
    assert unprotect(enc) == "s3cret-Pw"


def test_plaintext_passthrough():
    assert unprotect("plain123") == "plain123"   # 旧明文兼容
    assert protect("") == ""                      # 空不加密


def test_non_windows_degrades_to_plain(monkeypatch):
    """非 Windows:加密原样返回、密文宁空勿错(修复模块级 ctypes NameError)。"""
    from patrol.utils import crypto
    monkeypatch.setattr(crypto, "_IS_WINDOWS", False)
    assert crypto.protect("s3cret") == "s3cret"
    assert crypto.unprotect(PREFIX + "AAAA") == ""
    d = {"name": "t", "password": "pw", "api_token": "tk"}
    out = crypto.encrypt_device_dict(d)
    assert out["password"] == "pw" and out["api_token"] == "tk"


def test_store_disk_is_cipher_memory_is_plain(tmp_path: Path):
    ds = DeviceStore(str(tmp_path / "d.yaml"))
    ds.create({"name": "t", "host": "10.0.0.1", "password": "Pw#123",
               "super_password": "Sup#9", "api_token": "tk"})

    # 内存明文
    dev = ds.get("t")
    assert dev["password"] == "Pw#123" and dev["super_password"] == "Sup#9"

    # 磁盘密文
    if WIN:
        raw = yaml.safe_load((tmp_path / "d.yaml").read_text(encoding="utf-8"))
        stored = {d["name"]: d for d in raw["devices"]}["t"]
        assert stored["password"].startswith(PREFIX)
        assert "Pw#123" not in (tmp_path / "d.yaml").read_text(encoding="utf-8")

    # 重新加载后仍可读(同机同用户)
    ds2 = DeviceStore(str(tmp_path / "d.yaml"))
    assert ds2.get("t")["password"] == "Pw#123"


def test_legacy_plain_file_loads(tmp_path: Path):
    f = tmp_path / "d.yaml"
    f.write_text(
        "devices:\n- {name: old, host: 10.0.0.2, password: legacypw}\n",
        encoding="utf-8")
    ds = DeviceStore(str(f))
    assert ds.get("old")["password"] == "legacypw"  # 无前缀按明文
    ds.update("old", {"timeout": 30})
    if WIN:  # 回写后已加密
        raw = f.read_text(encoding="utf-8")
        assert "legacypw" not in raw
    assert ds.get("old")["password"] == "legacypw"
