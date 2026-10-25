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
    mind: dict[str, str] | None = None,
) -> None:
    global _last, _last_write
    lines = [
        f"armed={'1' if armed else '0'}",
        f"keys={''.join(sorted(keys))}",
        f"heading={heading or '-'}",
        f"focused={'1' if focused else '0'}",
        f"why={why}",
        f"mode={mode}",
        f"blocked={blocked}",
        "loop=1",
    ]
    if mind:
        for key in (
            "controller",
            "decider",
            "confidence",
            "latency_ms",
            "fallback",
            "stance",
            "option",
            "mark",
            "card",
            "model",
        ):
            if key in mind:
                lines.append(f"{key}={mind[key]}")
        for index in range(8):
            slot = f"opt{index}"
            if slot in mind:
                lines.append(f"{slot}={mind[slot]}")
    text = "\n".join(lines) + "\n"
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
    write_overlay_input(False, frozenset(), "-", False)
