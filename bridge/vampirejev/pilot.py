"""Pilot: the stateful layer around the stateless scorer.

Owns everything that needs memory across ticks:
- MotionTracker  -> which cardinals are walls right now (pressed W, y did not move)
- body flags     -> the game's own per-frame "blocked" sides (v4), calibrated against the tracker
- WallMemory     -> walls seen earlier at this world position
- mode hysteresis (no flip-flopping between farm/kite every tick)
- heading dwell  (commit to a heading for a few ticks unless it becomes vetoed or clearly worse)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .gate import snapshot_playable
from .memory import MotionTracker, WallMemory
from .polar import HEADINGS, SECTOR_NAMES
from .policy import MODES, Command, Context, Decision, decide_ex, desired_mode
from .snapshot import GameState

MODE_MIN_DWELL_S = 0.6
HEADING_DWELL_S = 0.15
SWITCH_MARGIN = 0.25
BODY_CALIBRATION_VOTES = 3


@dataclass
class PilotOutput:
    command: Command
    decision: Decision
    mode: str = "farm"
    blocked: frozenset[str] = frozenset()  # live blocked cardinals (tracker ∪ calibrated body flags)
    remembered: frozenset[str] = frozenset()
    stuck: bool = False
    body_y_flipped: Optional[bool] = None
    notes: list[str] = field(default_factory=list)


class Pilot:
    def __init__(self, mode_lock: Optional[str] = None, use_body_flags: bool = True) -> None:
        self.mode_lock = mode_lock if mode_lock in MODES else None
        self.use_body_flags = use_body_flags
        self.tracker = MotionTracker()
        self.memory = WallMemory()
        self.mode = "farm"
        self._mode_since = float("-inf")
        self._previous = -1
        self._dwell_until = float("-inf")
        self._last_t = None
        # Phaser names its sides up/down in its own y convention. We learn whether "up" means world +Y
        # by voting each time the tracker and the body flags both report a vertical wall.
        self._body_flip_votes = 0
        self.body_y_flipped: Optional[bool] = None
        self.last: Optional[PilotOutput] = None

    def reset(self) -> None:
        self.tracker.reset()
        self.memory = WallMemory(cell=self.memory.cell)
        self._previous = -1
        self._dwell_until = float("-inf")
        self.mode = "farm"
        self._mode_since = float("-inf")
        self._last_t = None

    def step(self, snapshot: Optional[GameState], sent_keys: Iterable[str], now: float) -> PilotOutput:
        if snapshot is None or snapshot.player is None or not snapshot_playable(snapshot):
            self.tracker.reset()
            self._previous = -1
            decision = decide_ex(snapshot, context=Context(mode=self.mode_lock))
            out = PilotOutput(decision.command, decision, mode=decision.mode)
            self.last = out
            return out

        player = snapshot.player
        t = snapshot.t_ms / 1000.0
        if self._last_t is not None and (t < self._last_t or t - self._last_t > 5.0):
            # New run, or the producer restarted: forget walls and hysteresis.
            self.reset()
        self._last_t = t

        r0 = snapshot.polar.radii[0] if snapshot.polar.radii[0] > 1e-6 else 6.0
        self.memory.set_cell_size(max(0.5 * r0, 0.5))
        live = self.tracker.observe(t, player.x, player.y, sent_keys, r0)
        body = self._body_blocked(player.blocked if player.has_blocked else frozenset(), live)
        blocked = live | body
        if live:
            self.memory.mark(player.x, player.y, live, t)
        remembered = self.memory.blocked_at(player.x, player.y, t) - blocked
        if int(t) % 5 == 0:
            self.memory.prune(t)

        mode = self.mode_lock or self._mode_with_hysteresis(snapshot, now)
        context = Context(
            blocked_live=blocked,
            blocked_memory=remembered,
            recent_walls=self.memory.recent(t),
            previous=self._previous,
            mode=mode,
            player_speed=self.tracker.free_speed,
        )
        decision = decide_ex(snapshot, context=context)
        if decision.mode != "nudge":
            self._apply_dwell(decision, now)
        self._previous = decision.best

        out = PilotOutput(
            decision.command,
            decision,
            mode=decision.mode,
            blocked=blocked,
            remembered=remembered,
            stuck=bool(live),
            body_y_flipped=self.body_y_flipped,
        )
        self.last = out
        return out

    # --- internals ------------------------------------------------------------------------------

    def _mode_with_hysteresis(self, snapshot: GameState, now: float) -> str:
        desired = desired_mode(snapshot)
        if desired == self.mode:
            return self.mode
        if desired == "flee" or now - self._mode_since >= MODE_MIN_DWELL_S:
            self.mode = desired
            self._mode_since = now
        return self.mode

    def _apply_dwell(self, decision: Decision, now: float) -> None:
        """Keep the previous heading for a short while unless it got vetoed or is clearly worse."""
        prev = self._previous
        best = decision.best
        if best < 0:
            return
        if prev < 0 or prev == best:
            if prev != best:
                self._dwell_until = now + HEADING_DWELL_S
            return
        keep = (
            not decision.vetoed[prev]
            and now < self._dwell_until
            and decision.scores[best] - decision.scores[prev] < SWITCH_MARGIN
        )
        if not keep:
            self._dwell_until = now + HEADING_DWELL_S
            return
        hx, hy = HEADINGS[prev]
        decision.best = prev
        decision.command = Command(hx, hy, SECTOR_NAMES[prev])
        decision.reason = "dwell"

    def _body_blocked(self, raw: frozenset[str], live: frozenset[str]) -> frozenset[str]:
        if not self.use_body_flags or not raw:
            return frozenset()
        out = set()
        if "left" in raw:
            out.add("W")
        if "right" in raw:
            out.add("E")
        vertical = {"up", "down"} & raw
        if vertical:
            self._vote_body_flip(raw, live)
            if self.body_y_flipped is not None:
                up_means = "S" if self.body_y_flipped else "N"
                down_means = "N" if self.body_y_flipped else "S"
                if "up" in raw:
                    out.add(up_means)
                if "down" in raw:
                    out.add(down_means)
        return frozenset(out)

    def _vote_body_flip(self, raw: frozenset[str], live: frozenset[str]) -> None:
        if self.body_y_flipped is not None:
            return
        vote = None
        if "up" in raw and "down" not in raw:
            if "N" in live and "S" not in live:
                vote = False
            elif "S" in live and "N" not in live:
                vote = True
        elif "down" in raw and "up" not in raw:
            if "S" in live and "N" not in live:
                vote = False
            elif "N" in live and "S" not in live:
                vote = True
        if vote is None:
            return
        self._body_flip_votes += 1 if vote else -1
        if abs(self._body_flip_votes) >= BODY_CALIBRATION_VOTES:
            self.body_y_flipped = self._body_flip_votes > 0
