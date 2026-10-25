"""Facts the rest of the bridge can use, still in code's own numbers.

The words Jev sees are built later, from these facts. Killable versus dangerous
comes from the stage's own max-HP table (sorted into frail, sturdy, and tanky)
and, once a run has shown it, from how fast that type actually loses HP near us.
Nothing here compares a weapon's damage number to an HP number.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .enemy_bands import MAD_FOREST_BANDS
from .snapshot import EnemyStats, Entity, GameState
from .words import hp_band, next_level_band

FRAIL = "frail"
STURDY = "sturdy"
TANKY = "tanky"
UNKNOWN = "unknown"

# How a type fares against the weapons we have, as a bucket.
KILLABLE = "killable"
SLOW = "slow"
SURVIVES = "survives"

NEAR_S = 1.5
DROP_FAST = 0.7
HOLD_SLOW = 0.1
# Seconds of HP history kept per enemy. Must stay longer than NEAR_S, or "survives" can never be seen.
HISTORY_S = 3.0
# An id not seen for this long is forgotten, so a 30-minute run does not grow the table.
FORGET_S = 5.0
# The game pools enemies. A jump back up in HP means the id now belongs to a fresh enemy.
RESPAWN_JUMP = 0.3


@dataclass
class Body:
    type: str
    x: float
    y: float
    vx: float
    vy: float
    uid: str
    hp: float | None
    hp_max: float | None
    boss: bool
    band: str
    outlook: str

    @property
    def dangerous(self) -> bool:
        if self.boss:
            return True
        return self.outlook != KILLABLE


@dataclass
class Perception:
    bodies: list[Body]
    hp_ratio: float
    hp_band: str
    low_hp: bool
    minute: int
    level: int | None
    next_level: str
    trend: str
    boss_present: bool
    bands: dict[str, str]


@dataclass
class PerceptionMemory:
    """HP samples and the enemy-count trend for one run. Reset when the clock jumps."""

    _hp: dict[str, deque] = field(default_factory=dict)
    _type_of: dict[str, str] = field(default_factory=dict)
    _seen: dict[str, float] = field(default_factory=dict)
    _outlooks: dict[str, str] = field(default_factory=dict)
    _trend: deque = field(default_factory=lambda: deque(maxlen=60))
    _last_t: float = -1.0

    def update(self, snapshot: GameState, bodies: list[Body]) -> None:
        t = snapshot.run.survived_seconds
        if self._last_t >= 0.0 and (t < self._last_t or t - self._last_t > 5.0):
            self._hp.clear()
            self._type_of.clear()
            self._seen.clear()
            self._trend.clear()
        self._last_t = t
        level = snapshot.player.level if snapshot.player and snapshot.player.level is not None else 0
        self._trend.append((t, snapshot.counts.enemies_stage, level))
        if snapshot.player is None:
            return
        radii = snapshot.polar.radii
        near = radii[0] if radii and radii[0] > 0 else 6.0
        for body in bodies:
            if not body.uid or body.hp is None or body.hp_max is None or body.hp_max <= 0:
                continue
            if math.hypot(body.x - snapshot.player.x, body.y - snapshot.player.y) > near:
                continue
            ratio = body.hp / body.hp_max
            hist = self._hp.get(body.uid)
            if hist is not None and (self._type_of.get(body.uid) != body.type or ratio > hist[-1][1] + RESPAWN_JUMP):
                hist = None
            if hist is None:
                hist = deque()
                self._hp[body.uid] = hist
            self._type_of[body.uid] = body.type
            self._seen[body.uid] = t
            hist.append((t, ratio))
            while hist and t - hist[0][0] > HISTORY_S:
                hist.popleft()
        for uid in [uid for uid, last in self._seen.items() if t - last > FORGET_S]:
            self._seen.pop(uid, None)
            self._hp.pop(uid, None)
            self._type_of.pop(uid, None)
        self._outlooks = self._learned_outlooks()

    def trend_text(self) -> str:
        if len(self._trend) < 2:
            return "no trend yet"
        old_t, old_n, old_level = self._trend[0]
        new_t, new_n, new_level = self._trend[-1]
        if new_t - old_t < 5.0:
            return "no trend yet"
        if new_n > old_n * 1.15:
            enemies = "rising"
        elif new_n < old_n * 0.85:
            enemies = "falling"
        else:
            enemies = "steady"
        level = "rising" if new_level > old_level else "steady"
        return f"enemy count {enemies}, level {level}"

    def outlook_for(self, type_name: str, default: str) -> str:
        """Promote or demote a catalog band once this run has watched that type lose HP."""
        return self._outlooks.get(type_name, default)

    def _learned_outlooks(self) -> dict[str, str]:
        fast: dict[str, int] = {}
        held: dict[str, int] = {}
        for uid, hist in self._hp.items():
            if not hist:
                continue
            type_name = self._type_of.get(uid, "")
            span = hist[-1][0] - hist[0][0]
            dropped = hist[0][1] - hist[-1][1]
            if span >= 0.6 and dropped >= DROP_FAST:
                fast[type_name] = fast.get(type_name, 0) + 1
            elif span >= NEAR_S and dropped <= HOLD_SLOW:
                held[type_name] = held.get(type_name, 0) + 1
        out: dict[str, str] = {}
        for type_name in set(fast) | set(held):
            f = fast.get(type_name, 0)
            h = held.get(type_name, 0)
            if h > 0 and h >= f:
                out[type_name] = SURVIVES
            elif f > h:
                out[type_name] = KILLABLE
        return out


def durability_bands(catalog: list[EnemyStats]) -> dict[str, str]:
    """Sort the stage's max HP values into three bands. One type alone stays sturdy."""
    valued = [(row.type, row.hp_max) for row in catalog if row.type and row.hp_max > 0]
    if not valued:
        return {}
    ordered = sorted({hp for _name, hp in valued})
    span = max(1, len(ordered) - 1)
    out: dict[str, str] = {}
    for name, hp in valued:
        frac = ordered.index(hp) / span
        if len(ordered) == 1:
            band = STURDY
        elif frac < 0.34:
            band = FRAIL
        elif frac < 0.67:
            band = STURDY
        else:
            band = TANKY
        out[name] = band
    return out


def outlook_from_band(band: str) -> str:
    if band == FRAIL:
        return KILLABLE
    if band == STURDY:
        return SLOW
    if band == TANKY:
        return SURVIVES
    return UNKNOWN


def perceive(snapshot: GameState, memory: PerceptionMemory | None = None) -> Perception:
    player = snapshot.player
    ratio = 1.0
    if player is not None and player.hp_max > 1e-6:
        ratio = max(0.0, min(1.0, player.hp / player.hp_max))
    # A published catalog is this run's data and replaces the static table.
    # An empty catalog means the mod has not sent one, which is the live case, so the table applies.
    bands = durability_bands(snapshot.enemy_catalog) if snapshot.enemy_catalog else dict(MAD_FOREST_BANDS)
    boss_points = [(boss.x, boss.y) for boss in snapshot.bosses]
    bodies: list[Body] = []
    seen_boss = False
    for enemy in snapshot.enemies:
        if _near_boss(enemy, boss_points):
            continue
        bodies.append(_body(enemy, boss=False, bands=bands, memory=memory))
    for boss in snapshot.bosses:
        seen_boss = True
        bodies.append(_body(boss, boss=True, bands=bands, memory=memory))
    if memory is not None and player is not None:
        memory.update(snapshot, bodies)
        for body in bodies:
            if body.boss:
                continue
            body.outlook = memory.outlook_for(body.type, body.outlook)
    known_xp = player is not None and player.xp_next > 1e-6
    frac = player.xp_frac if player is not None else 0.0
    return Perception(
        bodies=bodies,
        hp_ratio=ratio,
        hp_band=hp_band(ratio),
        low_hp=ratio < 0.35,
        minute=int(snapshot.run.survived_seconds // 60),
        level=player.level if player is not None else None,
        next_level=next_level_band(frac, known_xp),
        trend=memory.trend_text() if memory is not None else "no trend yet",
        boss_present=seen_boss or snapshot.counts.bosses_published > 0,
        bands=bands,
    )


def _near_boss(enemy: Entity, bosses: list[tuple[float, float]]) -> bool:
    return any(math.hypot(enemy.x - bx, enemy.y - by) < 0.4 for bx, by in bosses)


def _body(entity: Entity, boss: bool, bands: dict[str, str], memory: PerceptionMemory | None) -> Body:
    band = TANKY if boss else bands.get(entity.type, UNKNOWN)
    outlook = SURVIVES if boss else outlook_from_band(band)
    return Body(
        type=entity.type,
        x=entity.x,
        y=entity.y,
        vx=entity.vx,
        vy=entity.vy,
        uid=entity.uid,
        hp=entity.hp,
        hp_max=entity.hp_max,
        boss=boss,
        band=band,
        outlook=outlook,
    )
