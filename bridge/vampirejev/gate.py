"""Arm / focus / pause gates. Keys are sent only when every check passes."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

from .snapshot import GameState

VK_CONTROL = 0x11
VK_RCONTROL = 0xA3
VK_LCONTROL = 0xA2
VK_WASD = {"W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GAME_PROCESS = "vampiresurvivors.exe"


def snapshot_playable(snapshot: Optional[GameState]) -> bool:
    if snapshot is None:
        return False
    return snapshot.run.running and not snapshot.run.paused and not snapshot.run.level_up


def should_send(armed: bool, focused: bool, snapshot: Optional[GameState]) -> bool:
    return bool(armed and focused and snapshot_playable(snapshot))


def key_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def arm_key_down() -> bool:
    return key_down(VK_CONTROL) or key_down(VK_RCONTROL) or key_down(VK_LCONTROL)


def right_ctrl_down() -> bool:
    return arm_key_down()


def physical_wasd_down() -> frozenset[str]:
    return frozenset(name for name, vk in VK_WASD.items() if key_down(vk))


def user_wasd_override(
    command_keys: frozenset[str],
    physical: Optional[frozenset[str]] = None,
    ours: Optional[frozenset[str]] = None,
) -> bool:
    """True when the human is holding a WASD key the bot is not responsible for.

    GetAsyncKeyState also sees keys we injected, so `ours` (the driver's current
    down set) must be ignored or a heading change looks like a player takeover.
    """
    held = physical if physical is not None else physical_wasd_down()
    owned = ours if ours is not None else frozenset()
    return any(key not in command_keys and key not in owned for key in held)


def game_window_focused(process_name: str = GAME_PROCESS) -> bool:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return False
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return False
        image = buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        return image == process_name.lower()
    finally:
        kernel32.CloseHandle(handle)
