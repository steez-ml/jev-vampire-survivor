"""Build the short list of concrete options the navigator chooses from.

Each option is one thing worth doing right now: a target, a stance, and a
sentence. The id comes from what the target is (a world cell, or a sector when
that is all the snapshot knows), so a pick that arrives a fraction of a second
later still points at the same thing.

Coordinates stay on the option for the motor. The sentence is the only part
that is allowed to go to Jev.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .perception import SLOW, SURVIVES, Body, Perception
from .polar import SECTORS, ring_index, sector_index
from .snapshot import GameState, XpPile
from .weapons import AIM_FACING, AIM_MOVE, aim_class
from .words import (
    aura_reach,
    count_bucket,
    direction_name,
    distance_band,
    has_aura,
    option_id,
)

MAX_OPTIONS = 8
ROUTE_PAD = 2.4
# Enemies the polar bins count on the way to a target. The bins see past the few
# bodies the snapshot lists, but not what those enemies are. Uncalibrated.
CROWD_LIGHT = 3
CROWD_HEAVY = 8
HEAL_TYPES = frozenset({"ROAST", "ALWAYS_ROAST", "LITTLEHEART", "TP_WALL_CHICKEN"})
CLEAR_TYPES = frozenset({"VACUUM", "ROSARY", "OROLOGION"})

APPROACH = "approach"
STRIKE = "strike_side"
AURA = "aura_edge"
WALK = "walk_line"
KEEP = "keep_distance"
ESCAPE = "escape"


@dataclass
class Option:
    id: str
    kind: str
    stance: str
    x: float
    y: float
    aim_x: float
    aim_y: float
    facts: str
    value: str
    danger: str
    distance: str
    hold: bool = False


@dataclass(frozen=True)
class Route:
    danger: str
    killable: bool
    clause: str


def build_options(snapshot: GameState, perception: Perception) -> list[Option]:
    player = snapshot.player
    if player is None:
        return []
    radii = snapshot.polar.radii
    made: list[Option] = []
    made.extend(_gem_options(snapshot, perception, radii))
    made.extend(_pin_options(snapshot, perception, radii))
    made.extend(_enemy_options(snapshot, perception, radii))
    made.extend(_sector_options(snapshot, perception, radii))
    opened = _open_option(snapshot, perception, radii)
    if opened is not None:
        made.append(opened)
    return _trim(made)


def _rank(option: Option) -> float:
    # Same weights as the code picker. Kept here so this module does not import it.
    value = {"high": 3.0, "medium": 2.0, "low": 0.8}.get(option.value, 0.0)
    danger = {"clear": 0.0, "light": 1.1, "heavy": 4.5}.get(option.danger, 0.0)
    distance = {"close": 0.0, "medium": 0.5, "far": 1.2}.get(option.distance, 0.0)
    return value - danger - distance


def _trim(options: list[Option]) -> list[Option]:
    if len(options) <= MAX_OPTIONS:
        return options
    escapes = [item for item in options if item.kind == "open"]
    rest = [item for item in options if item.kind != "open"]
    rest.sort(key=lambda item: (-_rank(item), item.id))
    kept = rest[: MAX_OPTIONS - (1 if escapes else 0)]
    if escapes:
        escapes.sort(key=lambda item: (-_rank(item), item.id))
        kept.append(escapes[0])
    return kept


def _gem_options(snapshot: GameState, perception: Perception, radii: tuple[float, float, float]) -> list[Option]:
    player = snapshot.player
    assert player is not None
    piles = list(snapshot.xp_piles) or _piles_from_polar(snapshot)
    out: list[Option] = []
    seen: set[str] = set()
    for pile in piles:
        if pile.value < 4:
            continue
        ident = option_id("gems", pile.x, pile.y)
        if ident in seen:
            continue
        seen.add(ident)
        dist = math.hypot(pile.x - player.x, pile.y - player.y)
        route = _route(snapshot, perception, pile.x, pile.y)
        stance = _travel_stance(snapshot, route.killable)
        aim_x, aim_y = _travel_aim(player.x, player.y, pile.x, pile.y, stance, player.facing_x)
        value = "high" if pile.value >= 20 else "medium" if pile.value >= 6 else "low"
        direction = direction_name(pile.x - player.x, pile.y - player.y)
        band = distance_band(dist, radii)
        out.append(
            Option(
                id=ident,
                kind="gems",
                stance=stance,
                x=pile.x,
                y=pile.y,
                aim_x=aim_x,
                aim_y=aim_y,
                facts=_join(
                    f"Gem pile {direction}, {band}",
                    route.clause,
                    _killable_clause(route.killable),
                ),
                value=value,
                danger=route.danger,
                distance=band,
            )
        )
    return out


def _piles_from_polar(snapshot: GameState) -> list[XpPile]:
    """Estimate a pile from the XP bins when the mod has not published world clusters.

    The cell id drifts as the player moves, because the bin is relative. Real
    xp_piles are preferred whenever the snapshot has them.
    """
    player = snapshot.player
    if player is None:
        return []
    radii = snapshot.polar.radii
    piles: list[XpPile] = []
    for cell, value in enumerate(snapshot.polar.xp):
        if value < 4:
            continue
        ring = cell // SECTORS
        sector = cell % SECTORS
        if ring <= 0:
            dist = radii[0] * 0.5
        elif ring == 1:
            dist = (radii[0] + radii[1]) * 0.5
        else:
            dist = (radii[1] + radii[2]) * 0.5
        angle = sector * (math.pi / 4.0)
        piles.append(
            XpPile(
                player.x + math.sin(angle) * dist,
                player.y + math.cos(angle) * dist,
                value,
            )
        )
    piles.sort(key=lambda pile: -pile.value)
    return piles[:4]


def _pin_options(snapshot: GameState, perception: Perception, radii: tuple[float, float, float]) -> list[Option]:
    player = snapshot.player
    assert player is not None
    out: list[Option] = []
    for pin in snapshot.pickups:
        kind_name = (pin.type or "").upper()
        if kind_name in HEAL_TYPES:
            value = "high" if perception.low_hp else "low"
            label = "Floor chicken" if "ROAST" in kind_name or "CHICKEN" in kind_name or kind_name == "LITTLEHEART" else "Pickup"
        elif kind_name in CLEAR_TYPES:
            value = "medium"
            label = "Pickup that clears space"
        else:
            value = "low"
            label = "Pickup"
        out.append(_pin(snapshot, perception, radii, "pickup", pin.type or "pickup", pin.x, pin.y, value, label))
    for chest in snapshot.chests:
        out.append(_pin(snapshot, perception, radii, "chest", "chest", chest.x, chest.y, "medium", "Treasure chest"))
    for prop in snapshot.destructibles:
        value = "high" if perception.low_hp else "low"
        label = "Brazier" if (prop.type or "").upper() == "BRAZIER" else "Breakable"
        out.append(_pin(snapshot, perception, radii, "brazier", prop.type or "prop", prop.x, prop.y, value, label))
    return out


def _pin(
    snapshot: GameState,
    perception: Perception,
    radii: tuple[float, float, float],
    kind: str,
    type_name: str,
    x: float,
    y: float,
    value: str,
    label: str,
) -> Option:
    player = snapshot.player
    assert player is not None
    prefix = kind if kind != "brazier" else "brazier"
    ident = option_id(prefix if kind != "pickup" else f"pickup_{_slug(type_name)}", x, y)
    dist = math.hypot(x - player.x, y - player.y)
    route = _route(snapshot, perception, x, y)
    stance = _travel_stance(snapshot, route.killable)
    aim_x, aim_y = _travel_aim(player.x, player.y, x, y, stance, player.facing_x)
    band = distance_band(dist, radii)
    return Option(
        id=ident,
        kind=kind,
        stance=stance,
        x=x,
        y=y,
        aim_x=aim_x,
        aim_y=aim_y,
        facts=_join(f"{label} {direction_name(x - player.x, y - player.y)}, {band}", route.clause),
        value=value,
        danger=route.danger,
        distance=band,
    )


def _enemy_options(snapshot: GameState, perception: Perception, radii: tuple[float, float, float]) -> list[Option]:
    player = snapshot.player
    assert player is not None
    groups = _clusters(perception.bodies)
    out: list[Option] = []
    for members in groups:
        cx = sum(body.x for body in members) / len(members)
        cy = sum(body.y for body in members) / len(members)
        boss = any(body.boss for body in members)
        dangerous = any(body.dangerous for body in members)
        if boss:
            # A boss is a veto, not a destination.
            continue
        type_name = members[0].type or "enemies"
        ident = option_id(_slug(type_name), cx, cy)
        dist = math.hypot(cx - player.x, cy - player.y)
        stance = _fight_stance(snapshot, dangerous)
        aim_x, aim_y = _fight_aim(player.x, player.y, cx, cy, members, stance, snapshot)
        band = distance_band(dist, radii)
        outlook = _group_outlook(members)
        value = "low" if dangerous else "medium" if len(members) >= 3 else "low"
        danger = "heavy" if any(body.boss or body.outlook == SURVIVES or body.band == "tanky" for body in members) else "light" if dangerous else "clear"
        out.append(
            Option(
                id=ident,
                kind="enemies",
                stance=stance,
                x=cx,
                y=cy,
                aim_x=aim_x,
                aim_y=aim_y,
                facts=_enemy_facts(type_name, len(members), direction_name(cx - player.x, cy - player.y), band, stance, outlook, snapshot),
                value=value,
                danger=danger,
                distance=band,
                hold=stance in {AURA, KEEP},
            )
        )
    return out


def _sector_options(snapshot: GameState, perception: Perception, radii: tuple[float, float, float]) -> list[Option]:
    """A screen full of one type, past the handful of bodies the snapshot lists."""
    player = snapshot.player
    assert player is not None
    present = {body.type for body in perception.bodies if body.type}
    out: list[Option] = []
    for row in snapshot.enemy_sectors:
        if row.count < 4 or not row.type or row.type in present:
            continue
        sector = row.sector % SECTORS
        dist = radii[1] * 0.5
        angle = sector * (math.pi / 4.0)
        x = player.x + math.sin(angle) * dist
        y = player.y + math.cos(angle) * dist
        band_name = perception.bands.get(row.type, "unknown")
        dangerous = band_name in {"sturdy", "tanky", "unknown"}
        stance = _fight_stance(snapshot, dangerous)
        outlook = (
            "they die fast to our weapons"
            if band_name == "frail"
            else "they take a while to kill"
            if band_name == "sturdy"
            else "they survive our weapons"
            if band_name == "tanky"
            else "toughness unknown"
        )
        ident = f"sector_{_slug(row.type)}_{sector}"
        out.append(
            Option(
                id=ident,
                kind="enemies",
                stance=stance,
                x=x,
                y=y,
                aim_x=x,
                aim_y=y,
                facts=_join(
                    f"{count_bucket(row.count).capitalize()} {_pretty(row.type)} {direction_name(x - player.x, y - player.y)}, {distance_band(dist, radii)}",
                    outlook,
                ),
                value="low" if dangerous else "medium",
                danger="heavy" if band_name == "tanky" else "light" if dangerous else "clear",
                distance=distance_band(dist, radii),
                hold=stance in {AURA, KEEP},
            )
        )
    return out


def _open_option(snapshot: GameState, perception: Perception, radii: tuple[float, float, float]) -> Option | None:
    player = snapshot.player
    assert player is not None
    best_sector = 0
    best_mass = float("inf")
    for sector in range(SECTORS):
        mass = 0.0
        for ring, weight in enumerate((1.0, 0.6, 0.25)):
            mass += snapshot.polar.enemy[ring * SECTORS + sector] * weight
            if snapshot.polar.wall is not None:
                mass += snapshot.polar.wall[ring * SECTORS + sector] * weight
        if mass < best_mass:
            best_mass = mass
            best_sector = sector
    dist = radii[0] * 0.85
    angle = best_sector * (math.pi / 4.0)
    x = player.x + math.sin(angle) * dist
    y = player.y + math.cos(angle) * dist
    direction = direction_name(x - player.x, y - player.y)
    empty = best_mass < 0.5
    return Option(
        id=f"open_{best_sector}",
        kind="open",
        stance=ESCAPE,
        x=x,
        y=y,
        aim_x=x,
        aim_y=y,
        facts=f"Open space {direction}, {'nothing there' if empty else 'the emptiest way out'}",
        value="low",
        danger="clear",
        distance=distance_band(dist, radii),
    )


def _clusters(bodies: list[Body]) -> list[list[Body]]:
    remaining = list(bodies)
    groups: list[list[Body]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        changed = True
        while changed:
            changed = False
            still: list[Body] = []
            for body in remaining:
                same = (not seed.type and not body.type) or body.type == seed.type
                close = any(math.hypot(body.x - other.x, body.y - other.y) <= 3.0 for other in group)
                if same and close and body.boss == seed.boss:
                    group.append(body)
                    changed = True
                else:
                    still.append(body)
            remaining = still
        groups.append(group)
    return groups


def _route(snapshot: GameState, perception: Perception, x1: float, y1: float) -> Route:
    player = snapshot.player
    assert player is not None
    x0, y0 = player.x, player.y

    def blocking(body: Body) -> bool:
        return _in_front(x0, y0, x1, y1, body.x, body.y, ROUTE_PAD)

    bodies = perception.bodies
    dangerous = [body for body in bodies if body.dangerous and blocking(body)]
    killable = any((not body.dangerous) and blocking(body) for body in bodies)
    if any(body.boss or body.outlook == SURVIVES or body.band == "tanky" for body in dangerous):
        return Route("heavy", killable, "something that survives our weapons is on the way")
    crowd = _crowd_on_way(snapshot, perception, x1 - x0, y1 - y0)
    if crowd >= CROWD_HEAVY:
        return Route("heavy", killable, f"{_enemies(crowd)} on the way")
    if dangerous and crowd < CROWD_LIGHT and all(body.outlook == SLOW for body in dangerous):
        verb = "takes" if len(dangerous) == 1 else "take"
        return Route("light", killable, f"{_enemies(len(dangerous))} on the way that {verb} a while to kill")
    if dangerous or crowd >= CROWD_LIGHT:
        return Route("light", killable, f"{_enemies(max(len(dangerous), crowd))} on the way")
    return Route("clear", killable, "nothing dangerous on the way")


def _crowd_on_way(snapshot: GameState, perception: Perception, dx: float, dy: float) -> int:
    """Enemies in the polar cells between us and the target, minus the ones we know die fast.

    A straight line from the player stays inside one sector. The target's own ring
    counts half, because the bin cannot say whether those enemies are short of the
    target or past it.
    """
    player = snapshot.player
    assert player is not None
    radii = snapshot.polar.radii
    sector = sector_index(dx, dy)
    last = ring_index(math.hypot(dx, dy), radii)
    total = 0.0
    for ring in range(last + 1):
        weight = 0.5 if ring == last else 1.0
        total += snapshot.polar.enemy[ring * SECTORS + sector] * weight
    for body in perception.bodies:
        if body.dangerous:
            continue
        bx = body.x - player.x
        by = body.y - player.y
        if sector_index(bx, by) == sector and ring_index(math.hypot(bx, by), radii) <= last:
            total -= 1.0
    return max(0, int(round(total)))


def _enemies(count: int) -> str:
    bucket = count_bucket(count)
    if bucket == "one":
        return "one enemy"
    if bucket == "a few":
        return "a few enemies"
    return f"{bucket} of enemies"


def _in_front(x0: float, y0: float, x1: float, y1: float, px: float, py: float, pad: float) -> bool:
    """True when a body sits between the player and the target, not merely somewhere nearby."""
    dx = x1 - x0
    dy = y1 - y0
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return math.hypot(px - x0, py - y0) <= pad
    ux, uy = dx / dist, dy / dist
    along = (px - x0) * ux + (py - y0) * uy
    if along < 0.3 or along > dist:
        return False
    lateral = abs((px - x0) * uy - (py - y0) * ux)
    return lateral <= pad


def _travel_stance(snapshot: GameState, killable_on_way: bool) -> str:
    weapons = snapshot.player.weapons if snapshot.player else []
    classes = {aim_class(weapon.type) for weapon in weapons}
    if killable_on_way and AIM_FACING in classes:
        return STRIKE
    if killable_on_way and AIM_MOVE in classes:
        return WALK
    return APPROACH


def _fight_stance(snapshot: GameState, dangerous: bool) -> str:
    weapons = snapshot.player.weapons if snapshot.player else []
    if dangerous:
        return KEEP
    if has_aura(weapons):
        return AURA
    classes = {aim_class(weapon.type) for weapon in weapons}
    if AIM_FACING in classes:
        return STRIKE
    if AIM_MOVE in classes:
        return WALK
    return APPROACH


def _travel_aim(px: float, py: float, x: float, y: float, stance: str, facing_x: int) -> tuple[float, float]:
    if stance == WALK:
        return _beyond(px, py, x, y, 3.0)
    if stance == STRIKE:
        dx = x - px
        dy = y - py
        if abs(dx) < 0.8 and abs(dy) > abs(dx):
            side = 1.0 if facing_x >= 0 else -1.0
            return x + side * 1.5, y
    return x, y


def _fight_aim(
    px: float,
    py: float,
    cx: float,
    cy: float,
    members: list[Body],
    stance: str,
    snapshot: GameState,
) -> tuple[float, float]:
    weapons = snapshot.player.weapons if snapshot.player else []
    if stance == AURA:
        return _standoff(px, py, cx, cy, members, aura_reach(weapons) or 2.0)
    if stance == KEEP:
        return _standoff(px, py, cx, cy, members, 3.2)
    return _travel_aim(px, py, cx, cy, stance, snapshot.player.facing_x if snapshot.player else 1)


def _standoff(px: float, py: float, cx: float, cy: float, members: list[Body], reach: float) -> tuple[float, float]:
    edge = 0.0
    for body in members:
        edge = max(edge, math.hypot(body.x - cx, body.y - cy))
    desired = edge + reach * 0.85
    dx = cx - px
    dy = cy - py
    dist = math.hypot(dx, dy)
    if dist < 0.2:
        ux, uy = 1.0, 0.0
    else:
        ux, uy = dx / dist, dy / dist
    return cx - ux * desired, cy - uy * desired


def _beyond(px: float, py: float, x: float, y: float, extra: float) -> tuple[float, float]:
    dx = x - px
    dy = y - py
    dist = math.hypot(dx, dy) or 1.0
    return x + dx / dist * extra, y + dy / dist * extra


def _group_outlook(members: list[Body]) -> str:
    if any(body.outlook == SURVIVES for body in members):
        return "they survive our weapons"
    if any(body.outlook == "slow" for body in members):
        return "they take a while to kill"
    if any(body.outlook == "killable" for body in members):
        return "they die fast to our weapons"
    return "toughness unknown"


def _enemy_facts(type_name: str, count: int, direction: str, band: str, stance: str, outlook: str, snapshot: GameState) -> str:
    weapons = snapshot.player.weapons if snapshot.player else []
    bits = [f"{count_bucket(count).capitalize()} {_pretty(type_name)} {direction}, {band}"]
    if stance == STRIKE:
        bits.append("on the whip side")
    elif stance == WALK:
        bits.append("on the way we walk")
    elif stance == AURA and has_aura(weapons):
        bits.append("garlic reaches them")
    bits.append(outlook)
    return "; ".join(bits)


def _killable_clause(killable: bool) -> str:
    if not killable:
        return ""
    return "killable enemies on the way"


def _join(*parts: str) -> str:
    return ", ".join(part for part in parts if part)


def _slug(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "thing"


def _pretty(name: str) -> str:
    if not name or name == "enemies":
        return "enemies"
    return name.replace("_", " ").lower()
