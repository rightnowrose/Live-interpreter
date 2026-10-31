"""API Key 的本地加密存储（Windows DPAPI）。

DPAPI 使用当前 Windows 用户的凭据加密，复制 config.json 到其他机器无法解密。
非 Windows 环境下退化为 base64（仅避免明文直接暴露，不提供真正安全性）。
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

_PREFIX_DPAPI = "dpapi:"
_PREFIX_B64 = "b64:"


if sys.platform == "win32":

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL


def _blob(data: bytes) -> "_DataBlob":
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi_protect(data: bytes) -> bytes:
    blob_in = _blob(data)
    blob_out = _DataBlob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "LocalInterpreter",  # 保留旧 DPAPI 目标名，升级后仍能解密已存 Key
        None,
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    blob_in = _blob(data)
    blob_out = _DataBlob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def encrypt(text: str) -> str:
    if not text:
        return ""
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return _PREFIX_DPAPI + base64.b64encode(_dpapi_protect(raw)).decode("ascii")
        except OSError:
            pass
    return _PREFIX_B64 + base64.b64encode(raw).decode("ascii")


def decrypt(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_PREFIX_DPAPI):
        try:
            raw = base64.b64decode(value[len(_PREFIX_DPAPI) :])
            return _dpapi_unprotect(raw).decode("utf-8")
        except (OSError, ValueError):
            return ""
    if value.startswith(_PREFIX_B64):
        try:
            return base64.b64decode(value[len(_PREFIX_B64) :]).decode("utf-8")
        except ValueError:
            return ""
    # 兼容手写的明文
    return value


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "•" * max(0, len(key) - 2)
    return f"{key[:5]}…{key[-4:]}"
