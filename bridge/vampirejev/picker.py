"""Plain code that picks an option. This is also the without-Jev comparison.

The score uses only the buckets already written on the option: how valuable it
is, how dangerous the way there is, and how far it is. It re-scores every tick
but keeps the current option unless that option is gone or another is clearly
better, so the bot does not flip-flop.
"""

from __future__ import annotations

from .options import Option

VALUE = {"high": 3.0, "medium": 2.0, "low": 0.8}
DANGER = {"clear": 0.0, "light": 1.1, "heavy": 4.5}
DISTANCE = {"close": 0.0, "medium": 0.5, "far": 1.2}
SWITCH_MARGIN = 0.75


def score_option(option: Option) -> float:
    return VALUE.get(option.value, 0.0) - DANGER.get(option.danger, 0.0) - DISTANCE.get(option.distance, 0.0)


class CodePicker:
    def __init__(self, margin: float = SWITCH_MARGIN) -> None:
        self.margin = margin
        self.current: str | None = None

    def reset(self) -> None:
        self.current = None

    def choose(self, options: list[Option]) -> Option | None:
        if not options:
            self.current = None
            return None
        ranked = sorted(options, key=lambda item: (-score_option(item), item.id))
        best = ranked[0]
        current = next((item for item in options if item.id == self.current), None)
        if current is not None and score_option(best) - score_option(current) < self.margin:
            return current
        self.current = best.id
        return best
