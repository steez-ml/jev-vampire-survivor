"""v1 polar pilot scoring: price contact instead of forbidding it, know walls, kite, stay hungry.

Every tick we score the 8 WASD headings and press the best one. Per heading ``i`` with unit vector
``h`` (all terms are squashed to roughly [0, 1] so the weights below mean what they say):

    + xp_w      * attract_i     gems in the wedge (+ smoothed neighbours) and chest pull
    - threat_w  * threat_i      enemy mass in the wedge, rings weighted, neighbours smoothed
    - contact_w * contact_i     predicted enemies inside personal space in ~0.3 s, priced in HP
    + open_w    * openness_i    free space in the wedge and its neighbours (enemies and walls)
    + kite_w    * perp_i        perpendicular to the blob's centre of mass (stretches it out)
    - wall_i                    live blocked cardinals, wall bins, wall memory, hard bounds
    + aim_w     * aim_i         weapon aim class pointed at killable mass (early game only)
    + stick_w   * [i == prev]   hysteresis

Hard vetoes (reflex layer): boss inside the wedge, too many predicted contacts, a cardinal the
stuck detector or body flags say is a wall right now. If every heading is vetoed we still move:
the least-contact heading wins, because standing still in a blob is the worst option.

Modes are just weight vectors chosen from HP, nearby mass and chests. The layout is deliberately
the "narrow semantic decision" Jev could take over later: pick a mode, never a key.
``VSJEV_NUDGE`` still overrides everything for A/B tests.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .polar import (
    HEADINGS,
    SECTOR_NAMES,
    SECTORS,
    center_of_mass_dir,
    heading_unit,
    hottest_xp_sector,
    inner_enemy_mass,
    neighbors,
    sector_index,
)
from .snapshot import GameState, TypedPin
from .weapons import aim_bonus

NUDGE_HEADINGS = {
    "N": (0.0, 1.0),
    "S": (0.0, -1.0),
    "E": (1.0, 0.0),
    "W": (-1.0, 0.0),
    "NE": (1.0, 1.0),
    "NW": (-1.0, 1.0),
    "SE": (1.0, -1.0),
    "SW": (-1.0, -1.0),
}

# Cardinal name -> heading index, and which headings contain that cardinal as a component.
CARDINAL_INDEX = {"N": 0, "E": 2, "S": 4, "W": 6}
DIAGONALS_WITH = {"N": (7, 1), "E": (1, 3), "S": (3, 5), "W": (5, 7)}

RING_XP_WEIGHT = (1.0, 0.7, 0.45)
RING_ENEMY_WEIGHT = (1.2, 0.5, 0.15)
RING_OPEN_WEIGHT = (1.0, 0.6, 0.25)
RING_COM_WEIGHT = (1.0, 0.7, 0.3)
NEIGHBOR_SHARE = 0.35
# XP attraction is a *share* of the visible (ring-weighted) XP, so a lone free gem still pulls,
# plus a small bonus for absolute size so a real pile beats a crumb.
XP_FLOOR = 0.5
XP_SCALE = 10.0
THREAT_SCALE = 4.0
OPEN_SCALE = 6.0
# Openness / kiting only matter when enemies are actually close (ring 0 + half of ring 1).
OPEN_MIN_MASS = 1.0
OPEN_FULL_MASS = 10.0
KITE_MIN_MASS = 3.0
KITE_FULL_MASS = 12.0
CONTACT_LOOKAHEAD_S = 0.3
PERSONAL_SPACE_R0 = 0.5
DEFAULT_SPEED_R0_PER_S = 1.2  # player speed fallback until the tracker has measured it
HEAL_TYPES = frozenset(
    {
        "ROAST",
        "ALWAYS_ROAST",
        "LITTLEHEART",
        "TP_WALL_CHICKEN",
        "TP_HEART_REFRESH",
        "TP_SOULSTEAL_LITTLEHEART",
    }
)
GOLD_TYPES = frozenset(
    {"COIN", "COINBAG1", "COINBAG2", "COINBAGMAX", "GILDED", "STATIC_GOLDPILE", "ALWAYS_COINBAG2"}
)
CLEAR_TYPES = frozenset({"VACUUM", "ROSARY", "OROLOGION"})
BOSS_RANGE_R1 = 1.0
WALL_LIVE_DIAGONAL = 0.6
WALL_MEMORY_EXACT = 0.7
WALL_MEMORY_DIAGONAL = 0.25
WALL_RECENT_EXACT = 0.35
WALL_RECENT_DIAGONAL = 0.12
WALL_BIN_WEIGHTS = (1.4, 0.45, 0.12)
WALL_BIN_NEIGHBOR = 0.3
BOUNDS_PENALTY = 1.5
BOUNDS_STEP = 4.0
SCORE_EPS = 1e-6


@dataclass(frozen=True)
class Command:
    dx: float = 0.0
    dy: float = 0.0
    heading: str = "—"

    @property
    def is_idle(self) -> bool:
        return abs(self.dx) < 1e-6 and abs(self.dy) < 1e-6


@dataclass(frozen=True)
class Weights:
    xp: float
    threat: float
    contact: float
    open: float
    kite: float
    chest: float
    heal: float
    loot: float
    aim: float
    stick: float


MODES: dict[str, Weights] = {
    # Early / sparse: hungry, brave, still steers weapons at things.
    "farm": Weights(xp=1.4, threat=1.0, contact=2.0, open=0.4, kite=0.25, chest=1.2, heal=0.6, loot=0.5, aim=0.5, stick=0.12),
    # Dense: open space and perpendicular movement matter more than the next gem.
    "kite": Weights(xp=0.8, threat=1.3, contact=2.2, open=1.2, kite=1.0, chest=0.6, heal=0.8, loot=0.3, aim=0.3, stick=0.12),
    # Low HP: survive first, but a clear roast or brazier is the point of fleeing *toward* something.
    "flee": Weights(xp=0.2, threat=1.8, contact=3.0, open=1.6, kite=0.6, chest=0.2, heal=2.4, loot=1.1, aim=0.0, stick=0.10),
    # A chest is visible and the way there is not a wall of enemies.
    "chest": Weights(xp=0.8, threat=1.0, contact=1.6, open=0.5, kite=0.25, chest=2.0, heal=0.5, loot=0.3, aim=0.2, stick=0.12),
}

KITE_MODE_MASS = 10.0
FLEE_HP_RATIO = 0.35
CHEST_MIN_HP_RATIO = 0.5


@dataclass(frozen=True)
class Context:
    """What the pilot knows beyond the snapshot."""

    blocked_live: frozenset[str] = frozenset()  # cardinals blocked now (stuck detector / body flags)
    blocked_memory: frozenset[str] = frozenset()  # cardinals remembered blocked at this spot
    recent_walls: dict[str, float] = field(default_factory=dict)  # cardinal -> freshness (0, 1]
    previous: int = -1  # last heading index
    mode: Optional[str] = None  # force a mode; None = choose from the snapshot
    player_speed: float = 0.0  # measured world units/s; 0 = unknown, use the r0-based fallback


@dataclass
class Decision:
    command: Command
    mode: str = "farm"
    phase: float = 0.0
    best: int = -1
    scores: list[float] = field(default_factory=lambda: [float("-inf")] * SECTORS)
    vetoed: list[bool] = field(default_factory=lambda: [False] * SECTORS)
    contacts: list[float] = field(default_factory=lambda: [0.0] * SECTORS)
    reason: str = ""

    @property
    def heading(self) -> str:
        return self.command.heading


def decide(snapshot: Optional[GameState], nudge: Optional[str] = None, context: Optional[Context] = None) -> Command:
    """Stateless entry point (tests, replay). The Pilot adds memory and hysteresis on top."""
    return decide_ex(snapshot, nudge, context).command


def decide_ex(snapshot: Optional[GameState], nudge: Optional[str] = None, context: Optional[Context] = None) -> Decision:
    token = (nudge if nudge is not None else os.environ.get("VSJEV_NUDGE", "")).strip().upper()
    heading = NUDGE_HEADINGS.get(token)
    if heading is not None:
        return Decision(Command(heading[0], heading[1], token), mode="nudge", reason="nudge")

    if snapshot is None or snapshot.player is None or not snapshot.run.running:
        return Decision(Command(), reason="no-run")

    ctx = context or Context()
    player = snapshot.player
    hp_ratio = _hp_ratio(snapshot)
    phase = phase_of(snapshot)
    mass_near = near_mass(snapshot.polar.enemy)
    mode = ctx.mode if ctx.mode in MODES else choose_mode(snapshot, hp_ratio, mass_near)
    w = MODES[mode]

    enemy = snapshot.polar.enemy
    xp = snapshot.polar.xp
    wall = snapshot.polar.wall
    radii = snapshot.polar.radii
    hunger = 1.0 + 0.5 * player.xp_frac
    xp_w = w.xp * (1.5 - 0.9 * phase) * hunger
    threat_w = w.threat * (0.7 + 0.8 * phase) * (1.6 - 0.8 * hp_ratio)
    kill_appetite = (1.0 - phase) if hp_ratio > 0.5 else 0.0
    contacts, boss_hits = _predict_contacts(snapshot, radii, ctx.player_speed)
    contact_veto_n = max(2.0, 4.0 - 2.0 * phase) if hp_ratio >= FLEE_HP_RATIO else 1.0
    com_x, com_y, _com_total = center_of_mass_dir(enemy, RING_COM_WEIGHT)
    kite_gain = _ramp(mass_near, KITE_MIN_MASS, KITE_FULL_MASS)
    open_gain = _ramp(mass_near, OPEN_MIN_MASS, OPEN_FULL_MASS)
    aim = aim_bonus(player.weapons, enemy, player.facing_x) if w.aim > 0.0 and kill_appetite > 0.0 else None
    xp_wedges = [_wedge(xp, i, RING_XP_WEIGHT) for i in range(SECTORS)]
    xp_total = sum(xp_wedges)
    xp_size = 0.7 + 0.3 * _tanh(xp_total / XP_SCALE)

    decision = Decision(Command(), mode=mode, phase=phase, contacts=list(contacts))
    for i, (hx, hy) in enumerate(HEADINGS):
        ux, uy = heading_unit(i)
        veto = False
        if boss_hits[i]:
            veto = True
        if contacts[i] >= contact_veto_n:
            veto = True
        if _live_blocked_exact(i, ctx.blocked_live):
            veto = True
        decision.vetoed[i] = veto

        attract = (xp_wedges[i] / (xp_total + XP_FLOOR)) * xp_size if xp_total > 0.0 else 0.0
        threat = _tanh(_wedge(enemy, i, RING_ENEMY_WEIGHT) / THREAT_SCALE)
        safe = _path_safe(threat, contacts[i], hp_ratio)
        # Chests / roast / braziers are detours, not charges. `safe` goes to 0 when the heading
        # is already a predicted contact, especially at low HP.
        chest = _pin_pull(player.x, player.y, ux, uy, snapshot.chests) * w.chest * safe
        heal = _typed_pull(player.x, player.y, ux, uy, snapshot.pickups, lambda pin: _pickup_value(pin, hp_ratio, phase)) * w.heal * safe
        loot = _typed_pull(player.x, player.y, ux, uy, snapshot.destructibles, lambda _pin: _destructible_value(hp_ratio)) * w.loot * safe
        contact_cost = _contact_cost(contacts[i], hp_ratio, phase)
        openness = _openness(enemy, wall, i)
        perp = 0.0
        if kite_gain > 0.0:
            perp = 1.0 - abs(ux * com_x + uy * com_y)
        wall_cost = _wall_cost(i, ctx, wall, snapshot, hx, hy)
        aim_term = aim[i] * kill_appetite if aim is not None else 0.0
        stick = 1.0 if i == ctx.previous else 0.0

        score = (
            xp_w * attract
            + chest
            + heal
            + loot
            - threat_w * threat
            - w.contact * contact_cost
            + w.open * open_gain * openness
            + w.kite * kite_gain * perp
            - wall_cost
            + w.aim * aim_term
            + w.stick * stick
        )
        decision.scores[i] = score

    best = -1
    best_score = float("-inf")
    for i in range(SECTORS):
        if decision.vetoed[i]:
            continue
        if decision.scores[i] > best_score:
            best_score = decision.scores[i]
            best = i

    forced = False
    if best < 0:
        # Everything is vetoed: run through the thinnest part rather than stand still.
        best = min(range(SECTORS), key=lambda i: (contacts[i], -decision.scores[i]))
        decision.reason = "all-vetoed"
        forced = True

    empty_world = (
        not any(xp)
        and not any(enemy)
        and not snapshot.chests
        and not snapshot.enemies
        and not snapshot.bosses
        and not snapshot.pickups
        and not snapshot.destructibles
    )
    if empty_world and not forced and best_score <= SCORE_EPS + w.stick:
        decision.best = -1
        decision.reason = decision.reason or "empty"
        return decision

    hx, hy = HEADINGS[best]
    decision.best = best
    decision.command = Command(hx, hy, SECTOR_NAMES[best])
    decision.reason = decision.reason or "score"
    return decision


def desired_mode(snapshot: Optional[GameState]) -> str:
    if snapshot is None or snapshot.player is None:
        return "farm"
    return choose_mode(snapshot, _hp_ratio(snapshot), near_mass(snapshot.polar.enemy))


def choose_mode(snapshot: GameState, hp_ratio: float, mass_near: float) -> str:
    if hp_ratio < FLEE_HP_RATIO:
        return "flee"
    if snapshot.chests and hp_ratio >= CHEST_MIN_HP_RATIO and mass_near < KITE_MODE_MASS * 1.5:
        return "chest"
    if mass_near >= KITE_MODE_MASS:
        return "kite"
    return "farm"


def phase_of(snapshot: GameState) -> float:
    """0 = fresh run with few enemies, 1 = late and dense. Drives hunger vs caution."""
    t = _clamp(snapshot.run.survived_seconds / 900.0)
    density = _clamp(snapshot.counts.enemies_stage / 150.0)
    return _clamp(0.6 * t + 0.6 * density)


def near_mass(enemy: Sequence[float]) -> float:
    return float(sum(enemy[:SECTORS]) + 0.5 * sum(enemy[SECTORS : 2 * SECTORS]))


def describe(snapshot: Optional[GameState], command: Command, decision: Optional[Decision] = None) -> str:
    if snapshot is None:
        return "xp=— inner=0 heading=" + command.heading
    text = (
        f"xp={hottest_xp_sector(snapshot.polar.xp)} "
        f"inner={inner_enemy_mass(snapshot.polar.enemy):.0f} "
        f"heading={command.heading}"
    )
    if decision is not None:
        text += f" mode={decision.mode} phase={decision.phase:.2f}"
        if decision.best >= 0:
            text += f" score={decision.scores[decision.best]:.2f}"
        vetoed = [SECTOR_NAMES[i] for i in range(SECTORS) if decision.vetoed[i]]
        if vetoed:
            text += " veto=" + ",".join(vetoed)
    return text


# --- terms -------------------------------------------------------------------------------------


def _wedge(bins: Sequence[float], index: int, ring_weights: Sequence[float]) -> float:
    left, right = neighbors(index)
    total = 0.0
    for ring, weight in enumerate(ring_weights):
        base = ring * SECTORS
        total += bins[base + index] * weight
        total += NEIGHBOR_SHARE * (bins[base + left] + bins[base + right]) * weight
    return total


def _openness(enemy: Sequence[float], wall: Optional[Sequence[float]], index: int) -> float:
    occupancy = _wedge(enemy, index, RING_OPEN_WEIGHT)
    if wall is not None:
        # A wall cell is as closed as a handful of enemies would make it.
        occupancy += 4.0 * _wedge(wall, index, RING_OPEN_WEIGHT)
    return 1.0 - _tanh(occupancy / OPEN_SCALE)


def _contact_cost(n: float, hp_ratio: float, phase: float) -> float:
    if n <= 0.0:
        return 0.0
    dmg_frac = 0.06 + 0.14 * phase  # HP fraction one enemy costs across a decision window
    return n * dmg_frac / max(hp_ratio, 0.25)


def _path_safe(threat: float, contacts: float, hp_ratio: float) -> float:
    """0 = do not walk this way for a chest/chicken; 1 = the heading is clear."""
    risk = min(1.0, 0.7 * threat + 0.55 * contacts)
    if hp_ratio < 0.55:
        risk = min(1.0, risk + (0.55 - hp_ratio))
    return max(0.0, 1.0 - risk)


def _pickup_value(pin: TypedPin, hp_ratio: float, phase: float) -> float:
    kind = (pin.type or "").upper()
    if kind in HEAL_TYPES:
        # Always a little useful; dominates when HP is low.
        return 0.35 + 1.65 * (1.0 - hp_ratio)
    if kind in GOLD_TYPES:
        return 0.35
    if kind in CLEAR_TYPES:
        return 0.25 + 0.35 * phase
    return 0.2


def _destructible_value(hp_ratio: float) -> float:
    # Expected value of a Mad Forest brazier: gold / power-up / maybe a chicken.
    return 0.25 + 0.85 * (1.0 - hp_ratio)


def _typed_pull(px: float, py: float, nx: float, ny: float, pins, value_of) -> float:
    if not pins:
        return 0.0
    best = 0.0
    for pin in pins:
        value = value_of(pin)
        if value <= 0.0:
            continue
        dx = pin.x - px
        dy = pin.y - py
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            continue
        aligned = (dx / dist) * nx + (dy / dist) * ny
        if aligned <= 0.75:
            continue
        pull = value * aligned / (1.0 + dist * 0.05)
        if pull > best:
            best = pull
    return best


def _predict_contacts(snapshot: GameState, radii: Sequence[float], player_speed: float) -> tuple[list[float], list[bool]]:
    """Per heading: how many inner-ring enemies end up inside personal space in 0.3 s if we walk that way.

    Both sides move: the enemy by its published velocity (clamped — units are not proven), and we
    by ``player_speed`` along the heading. Walking straight at something 1.5 units away therefore
    *is* a contact, walking away from it is not.
    """
    player = snapshot.player
    assert player is not None
    r0 = radii[0] if radii[0] > 1e-6 else 6.0
    personal = r0 * PERSONAL_SPACE_R0
    personal2 = personal * personal
    speed = player_speed if player_speed > 1e-6 else DEFAULT_SPEED_R0_PER_S * r0
    our_step = speed * CONTACT_LOOKAHEAD_S
    max_step = r0  # nobody crosses the inner ring in 0.3 s
    contacts = [0.0] * SECTORS
    for enemy in snapshot.enemies:
        dx0 = enemy.x - player.x
        dy0 = enemy.y - player.y
        sx = enemy.vx * CONTACT_LOOKAHEAD_S
        sy = enemy.vy * CONTACT_LOOKAHEAD_S
        step = math.hypot(sx, sy)
        if step > max_step:
            sx *= max_step / step
            sy *= max_step / step
        ex = dx0 + sx
        ey = dy0 + sy
        for i in range(SECTORS):
            ux, uy = heading_unit(i)
            rx = ex - ux * our_step
            ry = ey - uy * our_step
            if rx * rx + ry * ry <= personal2:
                contacts[i] += 1.0

    boss_hits = [False] * SECTORS
    boss_range = radii[1] * BOSS_RANGE_R1 if radii[1] > 1e-6 else 16.0
    boss_range2 = boss_range * boss_range
    for boss in snapshot.bosses:
        dx = boss.x - player.x
        dy = boss.y - player.y
        if dx * dx + dy * dy <= boss_range2:
            boss_hits[sector_index(dx, dy)] = True
    return contacts, boss_hits


def _live_blocked_exact(index: int, blocked: frozenset[str]) -> bool:
    return any(CARDINAL_INDEX[c] == index for c in blocked if c in CARDINAL_INDEX)


def _wall_cost(
    index: int,
    ctx: Context,
    wall: Optional[Sequence[float]],
    snapshot: GameState,
    hx: float,
    hy: float,
) -> float:
    cost = 0.0
    for cardinal in ctx.blocked_live:
        if index in DIAGONALS_WITH.get(cardinal, ()):
            cost += WALL_LIVE_DIAGONAL  # sliding along the wall still moves, but slower
    for cardinal in ctx.blocked_memory:
        if CARDINAL_INDEX.get(cardinal) == index:
            cost += WALL_MEMORY_EXACT
        elif index in DIAGONALS_WITH.get(cardinal, ()):
            cost += WALL_MEMORY_DIAGONAL
    for cardinal, fresh in ctx.recent_walls.items():
        if CARDINAL_INDEX.get(cardinal) == index:
            cost += WALL_RECENT_EXACT * fresh
        elif index in DIAGONALS_WITH.get(cardinal, ()):
            cost += WALL_RECENT_DIAGONAL * fresh
    if wall is not None:
        left, right = neighbors(index)
        for ring, weight in enumerate(WALL_BIN_WEIGHTS):
            base = ring * SECTORS
            cost += wall[base + index] * weight
            if ring == 0:
                cost += WALL_BIN_NEIGHBOR * (wall[base + left] + wall[base + right]) * weight
    if snapshot.bounds is not None:
        player = snapshot.player
        assert player is not None
        cost += _bounds_penalty(player.x, player.y, hx, hy, snapshot.bounds)
    return cost


def _pin_pull(px: float, py: float, nx: float, ny: float, pins) -> float:
    if not pins:
        return 0.0
    best = 0.0
    for pin in pins:
        dx = pin.x - px
        dy = pin.y - py
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            continue
        aligned = (dx / dist) * nx + (dy / dist) * ny
        if aligned <= 0.75:
            continue
        pull = aligned / (1.0 + dist * 0.05)
        if pull > best:
            best = pull
    return best


def _bounds_penalty(px: float, py: float, hx: float, hy: float, bounds) -> float:
    mag = math.hypot(hx, hy)
    if mag < 1e-6:
        return 0.0
    nx, ny = px + hx / mag * BOUNDS_STEP, py + hy / mag * BOUNDS_STEP
    if nx < bounds.x or ny < bounds.y or nx > bounds.x + bounds.w or ny > bounds.y + bounds.h:
        return BOUNDS_PENALTY
    return 0.0


def _hp_ratio(snapshot: GameState) -> float:
    player = snapshot.player
    assert player is not None
    hp_max = player.hp_max if player.hp_max > 1e-6 else 1.0
    return _clamp(player.hp / hp_max)


def _ramp(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 1.0 if value >= hi else 0.0
    return _clamp((value - lo) / (hi - lo))


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if value < lo else hi if value > hi else value


def _tanh(value: float) -> float:
    return math.tanh(value) if value > 0.0 else 0.0
