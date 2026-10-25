"""Decide whether a Jev answer is usable.

A pick is used only when it is fresh, the option it names is still on the list,
and the confidence clears a conservative starting threshold. A later answer that
fails any of those does not cancel a commitment the motor is already carrying
out. That rule lives in the mind, which calls this and then keeps the old pick.
"""

from __future__ import annotations

from .jevclient import JevResult

FRESHNESS_S = 1.0
MIN_CONFIDENCE = 0.55


def accept_choice(result: JevResult | None, option_ids: set[str], now: float, *, freshness_s: float = FRESHNESS_S, min_confidence: float = MIN_CONFIDENCE) -> str | None:
    if result is None or not result.ok or result.kind != "movement":
        return None
    if now - result.built_mono > freshness_s:
        return None
    if result.choice not in option_ids:
        return None
    if result.confidence < min_confidence:
        return None
    return result.choice


def fresh_play_safe(result: JevResult | None, now: float, *, freshness_s: float = FRESHNESS_S) -> float | None:
    """The safety nudge is independent of whether the movement pick was confident."""
    if result is None or not result.ok or result.play_safe is None:
        return None
    if now - result.built_mono > freshness_s:
        return None
    return result.play_safe
