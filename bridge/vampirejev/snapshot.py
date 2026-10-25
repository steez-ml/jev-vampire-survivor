"""Normalized game-state dataclasses (v3, optional v4, optional v5).

Every newer field defaults to "unknown" so an older producer still parses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .polar import CELLS, DEFAULT_RADII, empty_bins


@dataclass
class RunState:
    running: bool = False
    paused: bool = False
    level_up: bool = False
    survived_seconds: float = 0.0


@dataclass
class WeaponState:
    type: str = ""
    level: int = 0
    evo: bool = False
    # v5. None means this producer did not publish the live weapon shape.
    area: Optional[float] = None
    amount: Optional[int] = None


@dataclass
class PlayerState:
    x: float = 0.0
    y: float = 0.0
    hp: float = 0.0
    hp_max: float = 0.0
    speed: float = 0.0
    radius: float = 0.0
    # v4 (optional). None / empty means the producer did not publish it.
    level: Optional[int] = None
    xp: float = 0.0
    xp_next: float = 0.0
    magnet: float = 0.0
    facing_x: int = 0
    move_dir: tuple[float, float] = (0.0, 0.0)
    blocked: frozenset[str] = frozenset()
    has_blocked: bool = False
    weapons: list[WeaponState] = field(default_factory=list)
    passives: list["PassiveState"] = field(default_factory=list)

    @property
    def xp_frac(self) -> float:
        if self.xp_next <= 1e-6:
            return 0.0
        return max(0.0, min(1.0, self.xp / self.xp_next))


@dataclass
class Bounds:
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class Entity:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    # v5. Empty / None means the producer did not publish it.
    type: str = ""
    hp: Optional[float] = None
    hp_max: Optional[float] = None
    uid: str = ""


@dataclass
class TypedPin:
    type: str = ""
    x: float = 0.0
    y: float = 0.0


@dataclass
class XpPile:
    """A gem cluster in world space. The option builder's stable id comes from this, not from the polar bins."""

    x: float = 0.0
    y: float = 0.0
    value: float = 0.0


@dataclass
class EnemyStats:
    """One row of the stage's enemy table: max HP and speed, not our estimate of damage."""

    type: str = ""
    hp_max: float = 0.0
    speed: float = 0.0


@dataclass
class SectorCount:
    """How many of one enemy type sit in one compass sector. Sector 0 is north."""

    sector: int = 0
    type: str = ""
    count: int = 0


@dataclass
class PassiveState:
    type: str = ""
    level: int = 0


@dataclass
class CardOffer:
    index: int = 0
    name: str = ""
    kind: str = ""
    type: str = ""
    level: int = 0
    is_new: bool = False
    description: str = ""


@dataclass
class EvolutionPair:
    weapon: str = ""
    passive: str = ""
    result: str = ""


@dataclass
class CardScreen:
    """A paused in-run choice. kind is level_up, chest, or arcana."""

    kind: str = ""
    offers: list[CardOffer] = field(default_factory=list)
    rerolls: Optional[int] = None
    skips: Optional[int] = None
    banishes: Optional[int] = None


@dataclass
class Polar:
    rings: int = 3
    sectors: int = 8
    radii: tuple[float, float, float] = DEFAULT_RADII
    enemy: list[float] = field(default_factory=empty_bins)
    xp: list[float] = field(default_factory=empty_bins)
    # v4: hit fraction of collision-tile probes per cell; None when the channel is not live.
    wall: Optional[list[float]] = None


@dataclass
class Counts:
    enemies_stage: int = 0
    enemies_published: int = 0
    gems_stage: int = 0
    gems_published: int = 0
    chests_stage: int = 0
    chests_published: int = 0
    bosses_published: int = 0
    tilemaps: int = 0
    pickups_stage: int = 0
    pickups_published: int = 0
    destructibles_stage: int = 0
    destructibles_published: int = 0


@dataclass
class Perf:
    probe_us: int = 0


@dataclass
class GameState:
    schema_version: int = 3
    seq: int = 0
    t_ms: int = 0
    source: str = "bepinex"
    run: RunState = field(default_factory=RunState)
    player: Optional[PlayerState] = None
    bounds: Optional[Bounds] = None
    polar: Polar = field(default_factory=Polar)
    enemies: list[Entity] = field(default_factory=list)
    bosses: list[Entity] = field(default_factory=list)
    chests: list[Entity] = field(default_factory=list)
    pickups: list[TypedPin] = field(default_factory=list)
    destructibles: list[TypedPin] = field(default_factory=list)
    counts: Counts = field(default_factory=Counts)
    perf: Perf = field(default_factory=Perf)
    # v5. Empty / None means a v3 or v4 producer, or a v5 read that did not fire.
    xp_piles: list[XpPile] = field(default_factory=list)
    enemy_catalog: list[EnemyStats] = field(default_factory=list)
    enemy_sectors: list[SectorCount] = field(default_factory=list)
    card_screen: Optional[CardScreen] = None
    evolutions: list[EvolutionPair] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameState":
        run = data.get("run") or {}
        player = data.get("player")
        bounds = data.get("bounds")
        polar = data.get("polar") or {}
        counts = data.get("counts") or {}
        perf = data.get("perf") or {}
        radii_raw = polar.get("radii") or list(DEFAULT_RADII)
        radii = (
            float(radii_raw[0] if len(radii_raw) > 0 else DEFAULT_RADII[0]),
            float(radii_raw[1] if len(radii_raw) > 1 else DEFAULT_RADII[1]),
            float(radii_raw[2] if len(radii_raw) > 2 else DEFAULT_RADII[2]),
        )
        wall_raw = polar.get("wall")
        return cls(
            schema_version=int(data.get("schema_version") or 3),
            seq=int(data.get("seq") or 0),
            t_ms=int(data.get("t_ms") or 0),
            source=str(data.get("source") or "bepinex"),
            run=RunState(
                running=bool(run.get("running")),
                paused=bool(run.get("paused")),
                level_up=bool(run.get("level_up")),
                survived_seconds=float(run.get("survived_seconds") or 0.0),
            ),
            player=_player(player) if isinstance(player, dict) else None,
            bounds=Bounds(
                x=float(bounds.get("x") or 0.0),
                y=float(bounds.get("y") or 0.0),
                w=float(bounds.get("w") or 0.0),
                h=float(bounds.get("h") or 0.0),
            )
            if isinstance(bounds, dict)
            else None,
            polar=Polar(
                rings=int(polar.get("rings") or 3),
                sectors=int(polar.get("sectors") or 8),
                radii=radii,
                enemy=_floats(polar.get("enemy"), CELLS),
                xp=_floats(polar.get("xp"), CELLS),
                wall=_floats(wall_raw, CELLS) if isinstance(wall_raw, list) and wall_raw else None,
            ),
            enemies=[_entity(item, velocity=True) for item in data.get("enemies") or []],
            bosses=[_entity(item, velocity=False) for item in data.get("bosses") or []],
            chests=[_entity(item, velocity=False) for item in data.get("chests") or []],
            pickups=[_typed(item) for item in data.get("pickups") or []],
            destructibles=[_typed(item) for item in data.get("destructibles") or []],
            xp_piles=[_pile(item) for item in data.get("xp_piles") or []],
            enemy_catalog=[_stats(item) for item in data.get("enemy_catalog") or []],
            enemy_sectors=[_sector(item) for item in data.get("enemy_sectors") or []],
            card_screen=_card_screen(data.get("card_screen")),
            evolutions=[_evolution(item) for item in data.get("evolutions") or []],
            counts=Counts(
                enemies_stage=int(counts.get("enemies_stage") or 0),
                enemies_published=int(counts.get("enemies_published") or 0),
                gems_stage=int(counts.get("gems_stage") or 0),
                gems_published=int(counts.get("gems_published") or 0),
                chests_stage=int(counts.get("chests_stage") or 0),
                chests_published=int(counts.get("chests_published") or 0),
                bosses_published=int(counts.get("bosses_published") or 0),
                tilemaps=int(counts.get("tilemaps") or 0),
                pickups_stage=int(counts.get("pickups_stage") or 0),
                pickups_published=int(counts.get("pickups_published") or 0),
                destructibles_stage=int(counts.get("destructibles_stage") or 0),
                destructibles_published=int(counts.get("destructibles_published") or 0),
            ),
            perf=Perf(probe_us=int(perf.get("probe_us") or 0)),
        )

    @classmethod
    def from_json(cls, text: str) -> "GameState":
        return cls.from_dict(json.loads(text))


def _player(player: dict[str, Any]) -> PlayerState:
    move_raw = player.get("move_dir")
    move = (0.0, 0.0)
    if isinstance(move_raw, list) and len(move_raw) >= 2:
        try:
            move = (float(move_raw[0] or 0.0), float(move_raw[1] or 0.0))
        except (TypeError, ValueError):
            move = (0.0, 0.0)
    blocked_raw = player.get("blocked")
    has_blocked = isinstance(blocked_raw, list)
    blocked = frozenset(str(item) for item in blocked_raw if isinstance(item, str)) if has_blocked else frozenset()
    level_raw = player.get("level")
    weapons_raw = player.get("weapons")
    weapons: list[WeaponState] = []
    if isinstance(weapons_raw, list):
        for item in weapons_raw:
            if not isinstance(item, dict):
                continue
            amount_raw = item.get("amount")
            weapons.append(
                WeaponState(
                    type=str(item.get("type") or ""),
                    level=int(item.get("level") or 0),
                    evo=bool(item.get("evo")),
                    area=_opt_float(item, "area"),
                    amount=int(amount_raw) if isinstance(amount_raw, (int, float)) and not isinstance(amount_raw, bool) else None,
                )
            )
    passives: list[PassiveState] = []
    for item in player.get("passives") or []:
        if not isinstance(item, dict):
            continue
        passives.append(PassiveState(type=str(item.get("type") or ""), level=int(item.get("level") or 0)))
    facing_raw = player.get("facing_x") or 0
    try:
        facing = int(round(float(facing_raw)))
    except (TypeError, ValueError):
        facing = 0
    return PlayerState(
        x=float(player.get("x") or 0.0),
        y=float(player.get("y") or 0.0),
        hp=float(player.get("hp") or 0.0),
        hp_max=float(player.get("hp_max") or 0.0),
        speed=float(player.get("speed") or 0.0),
        radius=float(player.get("radius") or 0.0),
        level=int(level_raw) if isinstance(level_raw, (int, float)) and not isinstance(level_raw, bool) else None,
        xp=float(player.get("xp") or 0.0),
        xp_next=float(player.get("xp_next") or 0.0),
        magnet=float(player.get("magnet") or 0.0),
        facing_x=max(-1, min(1, facing)),
        move_dir=move,
        blocked=blocked,
        has_blocked=has_blocked,
        weapons=weapons,
        passives=passives,
    )


def _floats(raw: Any, length: int) -> list[float]:
    values = [0.0] * length
    if not isinstance(raw, list):
        return values
    for i, item in enumerate(raw[:length]):
        try:
            values[i] = float(item or 0.0)
        except (TypeError, ValueError):
            values[i] = 0.0
    return values


def _entity(item: Any, velocity: bool) -> Entity:
    if not isinstance(item, dict):
        return Entity()
    uid = item.get("id")
    return Entity(
        x=float(item.get("x") or 0.0),
        y=float(item.get("y") or 0.0),
        vx=float(item.get("vx") or 0.0) if velocity else 0.0,
        vy=float(item.get("vy") or 0.0) if velocity else 0.0,
        type=str(item.get("type") or ""),
        hp=_opt_float(item, "hp"),
        hp_max=_opt_float(item, "hp_max"),
        uid=str(uid) if uid is not None else "",
    )


def _typed(item: Any) -> TypedPin:
    if not isinstance(item, dict):
        return TypedPin()
    return TypedPin(
        type=str(item.get("type") or ""),
        x=float(item.get("x") or 0.0),
        y=float(item.get("y") or 0.0),
    )


def _opt_float(item: dict[str, Any], key: str) -> Optional[float]:
    if key not in item or item[key] is None:
        return None
    try:
        return float(item[key])
    except (TypeError, ValueError):
        return None


def _pile(item: Any) -> XpPile:
    if not isinstance(item, dict):
        return XpPile()
    return XpPile(x=float(item.get("x") or 0.0), y=float(item.get("y") or 0.0), value=float(item.get("value") or 0.0))


def _stats(item: Any) -> EnemyStats:
    if not isinstance(item, dict):
        return EnemyStats()
    return EnemyStats(
        type=str(item.get("type") or ""),
        hp_max=float(item.get("hp_max") or 0.0),
        speed=float(item.get("speed") or 0.0),
    )


def _sector(item: Any) -> SectorCount:
    if not isinstance(item, dict):
        return SectorCount()
    return SectorCount(
        sector=int(item.get("sector") or 0),
        type=str(item.get("type") or ""),
        count=int(item.get("count") or 0),
    )


def _evolution(item: Any) -> EvolutionPair:
    if not isinstance(item, dict):
        return EvolutionPair()
    return EvolutionPair(
        weapon=str(item.get("weapon") or ""),
        passive=str(item.get("passive") or ""),
        result=str(item.get("result") or ""),
    )


def _card_screen(raw: Any) -> Optional[CardScreen]:
    if not isinstance(raw, dict):
        return None
    offers: list[CardOffer] = []
    for item in raw.get("offers") or []:
        if not isinstance(item, dict):
            continue
        offers.append(
            CardOffer(
                index=int(item.get("index") or 0),
                name=str(item.get("name") or ""),
                kind=str(item.get("kind") or ""),
                type=str(item.get("type") or ""),
                level=int(item.get("level") or 0),
                is_new=bool(item.get("is_new")),
                description=str(item.get("description") or ""),
            )
        )
    return CardScreen(
        kind=str(raw.get("kind") or ""),
        offers=offers,
        rerolls=_opt_int(raw, "rerolls"),
        skips=_opt_int(raw, "skips"),
        banishes=_opt_int(raw, "banishes"),
    )


def _opt_int(item: dict[str, Any], key: str) -> Optional[int]:
    if key not in item or item[key] is None:
        return None
    try:
        return int(item[key])
    except (TypeError, ValueError):
        return None
