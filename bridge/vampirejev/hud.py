"""Write current arm/keys to the overlay sidecar. Plugin status file is overwritten and cannot hold this."""

from __future__ import annotations

import time
from pathlib import Path

INPUT_PATH = Path(__file__).resolve().parents[2] / "overlay-input.txt"

_last = ""
_last_write = 0.0


def write_overlay_input(
    armed: bool,
    keys: frozenset[str],
    heading: str,
    focused: bool = False,
    why: str = "",
    mode: str = "",
    blocked: str = "",
) -> None:
    global _last, _last_write
    text = (
        f"armed={'1' if armed else '0'}\n"
        f"keys={''.join(sorted(keys))}\n"
        f"heading={heading or '—'}\n"
        f"focused={'1' if focused else '0'}\n"
        f"why={why}\n"
        f"mode={mode}\n"
        f"blocked={blocked}\n"
        f"loop=1\n"
    )
    now = time.monotonic()
    if text == _last and now - _last_write < 0.4:
        return
    _last = text
    _last_write = now
    try:
        INPUT_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass


def clear_overlay_input() -> None:
    write_overlay_input(False, frozenset(), "—", False)
