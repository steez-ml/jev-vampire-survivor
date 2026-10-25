"""The only code that chooses movement keys.

It walks toward the committed option's aim point, in that option's stance.
A reflex sidesteps anything dangerous that would touch us in the next fraction
of a second. Contact with enemies our weapons kill quickly is allowed when the
stance asked for it. Bosses and a wall the player is pressed against are hard
vetoes. Jev never presses these keys.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from .memory import MotionTracker, WallMemory
from .options import APPROACH, AURA, ESCAPE, STRIKE, WALK, Option
from .perception import Body, Perception
from .polar import HEADINGS, SECTOR_NAMES, heading_unit, sector_index
from .policy import NUDGE_HEADINGS, Command
from .snapshot import GameState

HORIZON_S = 0.3
ARRIVE = 0.45
ALLOW_CONTACT = frozenset({APPROACH, WALK, STRIKE, AURA})
BODY_CALIBRATION_VOTES = 3


@dataclass
class Steer:
    command: Command
    reflex: bool
    blocked: frozenset[str]
    remembered: frozenset[str]
    stuck: bool
    body_y_flipped: Optional[bool]
    note: str = ""


def choose_heading(
    player_x: float,
    player_y: float,
    speed: float,
    option: Option | None,
    bodies: list[Body],
    blocked: frozenset[str],
    bosses: list[tuple[float, float]],
    play_safe: float | None,
    low_hp: bool,
) -> tuple[int, bool]:
    """Return a heading index, or -1 to stand still, and whether the reflex changed it."""
    desired = -1
    stance = ESCAPE
    if option is not None:
        stance = option.stance
        dx = option.aim_x - player_x
        dy = option.aim_y - player_y
        if math.hypot(dx, dy) >= ARRIVE:
            desired = sector_index(dx, dy)
    desired = apply_vetoes(desired, player_x, player_y, blocked, bosses)
    radius = contact_radius(play_safe, low_hp)
    stepped = sidestep(desired, player_x, player_y, speed, bodies, stance, radius)
    if stepped is None:
        return desired, False
    stepped = apply_vetoes(stepped, player_x, player_y, blocked, bosses)
    return stepped, stepped != desired


def contact_radius(play_safe: float | None, low_hp: bool) -> float:
    radius = 0.9
    if play_safe is not None:
        radius = 0.65 + 0.7 * max(0.0, min(1.0, play_safe))
    if low_hp:
        radius = max(radius, 1.35)
    return radius


def apply_vetoes(
    index: int,
    player_x: float,
    player_y: float,
    blocked: frozenset[str],
    bosses: list[tuple[float, float]],
) -> int:
    if index < 0:
        return -1
    for step in (0, 1, -1, 2, -2, 3, -3, 4):
        alt = (index + step) % 8
        if SECTOR_NAMES[alt] in blocked:
            continue
        if boss_ahead(player_x, player_y, alt, bosses):
            continue
        return alt
    return index


def boss_ahead(player_x: float, player_y: float, index: int, bosses: list[tuple[float, float]]) -> bool:
    hx, hy = heading_unit(index)
    for bx, by in bosses:
        dx = bx - player_x
        dy = by - player_y
        dist = math.hypot(dx, dy)
        if dist > 4.0 or dist < 1e-6:
            continue
        if dx / dist * hx + dy / dist * hy > 0.7 and dist < 3.5:
            return True
    return False


def sidestep(
    desired: int,
    player_x: float,
    player_y: float,
    speed: float,
    bodies: list[Body],
    stance: str,
    radius: float,
) -> int | None:
    allow = stance in ALLOW_CONTACT
    if not _hits(desired, player_x, player_y, speed, bodies, radius, allow):
        return None
    best = desired if desired >= 0 else 0
    best_clearance = -1.0
    for index in range(8):
        clearance = _clearance(index, player_x, player_y, speed, bodies, radius, allow)
        if clearance > best_clearance + 1e-6:
            best_clearance = clearance
            best = index
    if desired >= 0 and best == desired:
        return None
    return best


def _hits(index: int, px: float, py: float, speed: float, bodies: list[Body], radius: float, allow: bool) -> bool:
    if index < 0:
        fx, fy = px, py
    else:
        fx, fy = _future(px, py, speed, index)
    return any(_blocks(body, allow) and math.hypot(body.x + body.vx * HORIZON_S - fx, body.y + body.vy * HORIZON_S - fy) <= radius for body in bodies)


def _clearance(index: int, px: float, py: float, speed: float, bodies: list[Body], radius: float, allow: bool) -> float:
    fx, fy = _future(px, py, speed, index)
    nearest = 99.0
    blocked = False
    for body in bodies:
        if not _blocks(body, allow):
            continue
        dist = math.hypot(body.x + body.vx * HORIZON_S - fx, body.y + body.vy * HORIZON_S - fy)
        nearest = min(nearest, dist)
        if dist <= radius:
            blocked = True
    if blocked:
        return nearest * 0.01
    return nearest


def _blocks(body: Body, allow_killable: bool) -> bool:
    if body.dangerous:
        return True
    return not allow_killable


def _future(px: float, py: float, speed: float, index: int) -> tuple[float, float]:
    hx, hy = heading_unit(index)
    step = (speed if speed > 0.2 else 3.0) * HORIZON_S
    return px + hx * step, py + hy * step


def command_for(index: int) -> Command:
    if index < 0:
        return Command()
    hx, hy = HEADINGS[index]
    return Command(hx, hy, SECTOR_NAMES[index])


class Motor:
    """Wall memory and the stuck detector, then the heading above."""

    def __init__(self, use_body_flags: bool = True) -> None:
        self.use_body_flags = use_body_flags
        self.tracker = MotionTracker()
        self.memory = WallMemory()
        self._last_t: float | None = None
        self._body_flip_votes = 0
        self.body_y_flipped: bool | None = None

    def reset(self) -> None:
        self.tracker.reset()
        self.memory = WallMemory(cell=self.memory.cell)
        self._last_t = None

    def step(
        self,
        snapshot: GameState,
        option: Option | None,
        perception: Perception,
        sent_keys: Iterable[str],
        play_safe: float | None,
    ) -> Steer:
        nudge = _nudge_command()
        if nudge is not None:
            return Steer(nudge, False, frozenset(), frozenset(), False, self.body_y_flipped, note="nudge")
        player = snapshot.player
        if player is None or not snapshot.run.running:
            self.tracker.reset()
            return Steer(Command(), False, frozenset(), frozenset(), False, self.body_y_flipped)

        t = snapshot.t_ms / 1000.0
        if self._last_t is not None and (t < self._last_t or t - self._last_t > 5.0):
            self.reset()
        self._last_t = t
        if snapshot.run.paused or snapshot.run.level_up:
            self.tracker.reset()
            return Steer(Command(), False, frozenset(), frozenset(), False, self.body_y_flipped)

        r0 = snapshot.polar.radii[0] if snapshot.polar.radii[0] > 1e-6 else 6.0
        self.memory.set_cell_size(max(0.5 * r0, 0.5))
        live = self.tracker.observe(t, player.x, player.y, sent_keys, r0)
        body = self._body_blocked(player.blocked if player.has_blocked else frozenset(), live)
        blocked = live | body
        if live:
            self.memory.mark(player.x, player.y, live, t)
        remembered = self.memory.blocked_at(player.x, player.y, t)
        # A wall we are pressed against right now is a hard veto. Remembered walls
        # still steer us off, but only the live ones veto a cardinal outright.
        veto = blocked
        if int(t) % 5 == 0:
            self.memory.prune(t)
        bosses = [(boss.x, boss.y) for boss in snapshot.bosses]
        index, reflex = choose_heading(
            player.x,
            player.y,
            player.speed,
            option,
            perception.bodies,
            veto,
            bosses,
            play_safe,
            perception.low_hp,
        )
        # Soft cost of a remembered wall: if the heading is that cardinal, slide off it.
        if not reflex:
            index = apply_vetoes(index, player.x, player.y, remembered, bosses)
        return Steer(
            command_for(index),
            reflex,
            blocked,
            remembered - blocked,
            bool(live),
            self.body_y_flipped,
        )

    def _body_blocked(self, raw: frozenset[str], live: frozenset[str]) -> frozenset[str]:
        # Same calibration as the baseline pilot: Phaser names up/down in its own y.
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


def _nudge_command() -> Command | None:
    token = os.environ.get("VSJEV_NUDGE", "").strip().upper()
    heading = NUDGE_HEADINGS.get(token)
    if heading is None:
        return None
    return Command(heading[0], heading[1], token)
