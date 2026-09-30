"""Map an 8-way heading to WASD and send it with Win32 SendInput."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Iterable, Optional

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1

VK = {
    "W": 0x57,
    "A": 0x41,
    "S": 0x53,
    "D": 0x44,
}

SCAN = {
    "W": 0x11,
    "A": 0x1E,
    "S": 0x1F,
    "D": 0x20,
}

DEADZONE = 0.1

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SendInput = _user32.SendInput
_SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_SendInput.restype = wintypes.UINT
_keybd_event = _user32.keybd_event
_keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR)
_keybd_event.restype = None

_send_failed = False

SendFn = Callable[[str, bool], None]


def heading_to_keys(dx: float, dy: float, deadzone: float = DEADZONE) -> frozenset[str]:
    keys: set[str] = set()
    if dy > deadzone:
        keys.add("W")
    elif dy < -deadzone:
        keys.add("S")
    if dx > deadzone:
        keys.add("D")
    elif dx < -deadzone:
        keys.add("A")
    return frozenset(keys)


def _send_key(name: str, down: bool) -> None:
    global _send_failed
    flags = 0 if down else KEYEVENTF_KEYUP
    union = INPUTUNION()
    union.ki = KEYBDINPUT(VK[name], SCAN[name], flags, 0, 0)
    payload = INPUT(INPUT_KEYBOARD, union)
    sent = _SendInput(1, ctypes.byref(payload), ctypes.sizeof(INPUT))
    if sent == 1:
        return
    _keybd_event(VK[name], SCAN[name], 0 if down else KEYEVENTF_KEYUP, 0)
    if not _send_failed:
        _send_failed = True
        err = ctypes.get_last_error()
        print(
            f"SendInput returned {sent} (last_error={err}, sizeof INPUT={ctypes.sizeof(INPUT)}); "
            "fell back to keybd_event",
            flush=True,
        )


class WasdDriver:
    def __init__(self, sender: Optional[SendFn] = None) -> None:
        self._down: set[str] = set()
        self._sender = sender or _send_key

    @property
    def down(self) -> frozenset[str]:
        return frozenset(self._down)

    def apply(self, dx: float, dy: float) -> frozenset[str]:
        return self.set_keys(heading_to_keys(dx, dy))

    def set_keys(self, wanted: Iterable[str]) -> frozenset[str]:
        target = {key for key in wanted if key in VK}
        for key in list(self._down - target):
            self._sender(key, False)
            self._down.remove(key)
        for key in target - self._down:
            self._sender(key, True)
            self._down.add(key)
        return frozenset(self._down)

    def all_up(self) -> None:
        self.set_keys(())
