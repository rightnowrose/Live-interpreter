"""Windows 全局热键（RegisterHotKey）。"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_SPECIAL = {
    "space": 0x20,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    value = (text or "").strip()
    if not value:
        return None
    parts = [p.strip().lower() for p in value.replace("＋", "+").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key = parts[-1]
    for part in parts[:-1]:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "meta", "super"):
            mods |= MOD_WIN
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _SPECIAL:
        vk = _SPECIAL[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    else:
        return None
    return mods | MOD_NOREPEAT, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[int], None]) -> None:
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, eventType, message):
        if sys.platform != "win32":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.callback(int(msg.wParam))
        except Exception:
            pass
        return False, 0


class HotkeyManager(QObject):
    triggered = Signal(str)
    failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._filter = _Filter(self._on_hotkey)
        self._registered: dict[int, str] = {}
        self._sequences: dict[str, str] = {}
        self._next_id = 0x5300
        if sys.platform == "win32":
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)

    def _on_hotkey(self, hotkey_id: int) -> None:
        action = self._registered.get(hotkey_id)
        if action:
            self.triggered.emit(action)

    def register(self, mapping: dict[str, str]) -> None:
        if sys.platform != "win32":
            return
        self.unregister_all()
        user32 = ctypes.windll.user32
        for action, sequence in mapping.items():
            parsed = parse_hotkey(sequence)
            if not parsed:
                continue
            mods, vk = parsed
            hotkey_id = self._next_id
            self._next_id += 1
            if user32.RegisterHotKey(None, hotkey_id, mods, vk):
                self._registered[hotkey_id] = action
                self._sequences[action] = sequence
            else:
                log.warning("注册热键失败：%s (%s)", sequence, action)
                self.failed.emit(action, sequence)

    def unregister_all(self) -> None:
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        for hotkey_id in list(self._registered):
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass
        self._registered.clear()
        self._sequences.clear()
