"""Menu taps for card screens.

The names are a plan the card picker already chose (DOWN a few times, then
RETURN, or RETURN twice for a chest). Nothing here runs unless the loop was
started with --menu-keys provisional. Those keys are not confirmed for
Vampire Survivors 1.16.107. See roadmap open question 3.

Taps are not WASD, so they do not look like the player taking over movement.
"""

from __future__ import annotations

import ctypes
from typing import Callable, Optional

from .wasd import INPUT, INPUTUNION, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP

# Provisional, unverified against 1.16.107.
MENU_VK = {
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "RETURN": 0x0D,
    "SPACE": 0x20,
}

SendFn = Callable[[str, bool], None]
_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _send_menu(name: str, down: bool) -> None:
    vk = MENU_VK.get(name)
    if vk is None:
        return
    flags = 0 if down else KEYEVENTF_KEYUP
    union = INPUTUNION()
    union.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    payload = INPUT(INPUT_KEYBOARD, union)
    _user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(INPUT))


class MenuDriver:
    def __init__(self, sender: Optional[SendFn] = None) -> None:
        self._sender = sender or _send_menu

    def tap(self, name: str) -> None:
        if name not in MENU_VK:
            return
        self._sender(name, True)
        self._sender(name, False)


class MenuExecutor:
    """Play a short tap plan once per card screen, with a gap so the game can see each tap."""

    def __init__(self, gap_s: float = 0.18) -> None:
        self.gap_s = gap_s
        self._signature = ""
        self._plan: tuple[str, ...] = ()
        self._index = 0
        self._next = 0.0

    def step(self, now: float, signature: str, plan: tuple[str, ...], driver: MenuDriver) -> bool:
        if signature != self._signature:
            self._signature = signature
            self._plan = plan
            self._index = 0
            self._next = now
        if self._index >= len(self._plan):
            return False
        if now < self._next:
            return True
        driver.tap(self._plan[self._index])
        self._index += 1
        self._next = now + self.gap_s
        return True
