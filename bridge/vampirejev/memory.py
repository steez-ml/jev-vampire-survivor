"""Proprioception: learn walls from what the bot pressed versus how the player actually moved.

The v3 snapshot never says "you hit a wall". This module is the ground truth for that even when
the v4 wall probe is live: if we have been holding W for a quarter second and y has not changed,
north is blocked right here. The same trick robots use to detect wheel slip.

- MotionTracker: rolling window of (time, x, y, keys held). Reports cardinals blocked *now*.
- WallMemory: coarse world grid that remembers "north was blocked in this cell" for a while,
  so the bot does not have to re-test the same wall every tick when it comes back.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable

CARDINALS = ("N", "E", "S", "W")
KEY_TO_CARDINAL = {"W": "N", "D": "E", "S": "S", "A": "W"}
# cardinal -> (axis index into (x, y), sign of forward motion along that axis)
CARDINAL_AXIS = {"N": (1, 1.0), "S": (1, -1.0), "E": (0, 1.0), "W": (0, -1.0)}


@dataclass(frozen=True)
class MotionSample:
    t: float
    x: float
    y: float
    keys: frozenset[str]


class MotionTracker:
    """Compare commanded cardinals against observed displacement.

    A cardinal is reported blocked when its key has been held for at least ``min_hold_s`` and the
    displacement along that axis over the hold is below ``stuck_ratio`` of what free movement
    would have produced. Free speed is learned (EMA of observed speed while moving) with a floor
    expressed in inner-ring radii per second so the first seconds of a run are safe too.
    """

    def __init__(
        self,
        min_hold_s: float = 0.22,
        window_s: float = 0.6,
        stuck_ratio: float = 0.2,
        expire_s: float = 0.6,
        floor_r0_per_s: float = 0.5,
    ) -> None:
        self.min_hold_s = min_hold_s
        self.window_s = window_s
        self.stuck_ratio = stuck_ratio
        self.expire_s = expire_s
        self.floor_r0_per_s = floor_r0_per_s
        self._samples: Deque[MotionSample] = deque()
        self._free_speed = 0.0
        self._blocked_until: dict[str, float] = {}
        self.events = 0

    @property
    def free_speed(self) -> float:
        return self._free_speed

    def reset(self) -> None:
        self._samples.clear()
        self._blocked_until.clear()

    def observe(self, t: float, x: float, y: float, keys: Iterable[str], r0: float) -> frozenset[str]:
        held = frozenset(KEY_TO_CARDINAL[k] for k in keys if k in KEY_TO_CARDINAL)
        if self._samples and t < self._samples[-1].t:
            # Clock went backwards (new run / restarted producer): start over.
            self.reset()
        self._samples.append(MotionSample(t, x, y, held))
        cutoff = t - self.window_s
        while len(self._samples) > 2 and self._samples[0].t < cutoff:
            self._samples.popleft()

        self._learn_free_speed()
        if held:
            self._detect(t, held, r0)
        return self.blocked(t)

    def blocked(self, t: float) -> frozenset[str]:
        return frozenset(c for c, until in self._blocked_until.items() if until > t)

    def _learn_free_speed(self) -> None:
        if len(self._samples) < 2:
            return
        newest = self._samples[-1]
        prev = self._samples[-2]
        dt = newest.t - prev.t
        if dt <= 1e-3 or dt > 0.5:
            return
        dist = ((newest.x - prev.x) ** 2 + (newest.y - prev.y) ** 2) ** 0.5
        speed = dist / dt
        if speed <= 1e-6:
            return
        # Only ever learn upward quickly; decay slowly so a temporary slow (wall slide) does not
        # convince us the character is slow.
        if speed > self._free_speed:
            self._free_speed = 0.7 * self._free_speed + 0.3 * speed
        else:
            self._free_speed = 0.995 * self._free_speed + 0.005 * speed

    def _detect(self, t: float, held: frozenset[str], r0: float) -> None:
        newest = self._samples[-1]
        expected_speed = max(self._free_speed, self.floor_r0_per_s * max(r0, 1e-3))
        for cardinal in held:
            start = self._hold_start(cardinal)
            if start is None:
                continue
            span = newest.t - start.t
            if span < self.min_hold_s:
                continue
            axis, sign = CARDINAL_AXIS[cardinal]
            delta = (newest.x - start.x, newest.y - start.y)[axis] * sign
            expected = expected_speed * span
            if delta < self.stuck_ratio * expected:
                if self._blocked_until.get(cardinal, 0.0) <= t:
                    self.events += 1
                self._blocked_until[cardinal] = t + self.expire_s

    def _hold_start(self, cardinal: str) -> MotionSample | None:
        """Oldest sample of the current continuous hold of this cardinal (None if not held)."""
        start = None
        for sample in reversed(self._samples):
            if cardinal not in sample.keys:
                break
            start = sample
        return start


class WallMemory:
    """Coarse world grid of cardinals that were blocked at that cell, plus a short global memory.

    - Cell marks expire after ``ttl_s`` and answer "is there a wall on this side *here*".
    - ``recent`` remembers when each side was last a wall *anywhere*; its freshness decays over
      ``recent_ttl_s``. Bumping N and then S inside a corridor makes both sides unattractive for a
      few seconds, which is exactly the "this map is horizontal" prior a human forms.
    """

    def __init__(self, cell: float = 3.0, ttl_s: float = 30.0, recent_ttl_s: float = 8.0) -> None:
        self.cell = max(cell, 1e-3)
        self.ttl_s = ttl_s
        self.recent_ttl_s = recent_ttl_s
        self._cells: dict[tuple[int, int], dict[str, float]] = {}
        self._recent: dict[str, float] = {}

    def set_cell_size(self, cell: float) -> None:
        if cell > 1e-3 and abs(cell - self.cell) > 1e-6:
            self.cell = cell
            self._cells.clear()

    def key(self, x: float, y: float) -> tuple[int, int]:
        return (int(x // self.cell), int(y // self.cell))

    def mark(self, x: float, y: float, cardinals: Iterable[str], t: float) -> None:
        marks = frozenset(c for c in cardinals if c in CARDINALS)
        if not marks:
            return
        cell = self._cells.setdefault(self.key(x, y), {})
        for cardinal in marks:
            cell[cardinal] = t + self.ttl_s
            self._recent[cardinal] = t

    def recent(self, t: float) -> dict[str, float]:
        """Cardinal -> freshness in (0, 1]; 1 = blocked just now, gone after recent_ttl_s."""
        out = {}
        for cardinal, last in self._recent.items():
            age = t - last
            if age < 0.0:
                continue
            fresh = 1.0 - age / self.recent_ttl_s
            if fresh > 0.0:
                out[cardinal] = fresh
        return out

    def blocked_at(self, x: float, y: float, t: float) -> frozenset[str]:
        cell = self._cells.get(self.key(x, y))
        if not cell:
            return frozenset()
        return frozenset(c for c, until in cell.items() if until > t)

    def prune(self, t: float) -> None:
        dead = []
        for key, cell in self._cells.items():
            for cardinal in [c for c, until in cell.items() if until <= t]:
                del cell[cardinal]
            if not cell:
                dead.append(key)
        for key in dead:
            del self._cells[key]

    def __len__(self) -> int:
        return sum(len(cell) for cell in self._cells.values())
