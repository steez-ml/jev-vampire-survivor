"""Turn positions and counts into the words Jev is allowed to see.

Jev is weak at arithmetic, so every number that means "how much" or "where exactly"
stays in this module. What leaves is a bucket: close, high, a large group.
Small labels such as the minute, the level, and a weapon's level are allowed
through later, on purpose. They are names for a moment, not quantities to add up.
"""

from __future__ import annotations

import math
import re
from typing import Sequence

from .polar import SECTOR_NAMES, sector_index
from .snapshot import WeaponState
from .weapons import AIM_FACING, AIM_MOVE, aim_class

# World-cell size for stable option ids. Coarse on purpose: a pile that sits
# still must keep the same id while the player walks a step toward it.
CELL = 4.0

# Garlic's touch range when the snapshot does not yet publish Equipment.area.
# Open question 6 in the roadmap. This is a stand-in, not a damage formula.
DEFAULT_AURA_REACH = 2.0

# WeaponType names seen in this install's interop strings on 2026-10-24, plus
# the aim table in weapons.py. The clause after the colon is how movement
# interacts with the weapon, which is what an option needs. It is not a DPS note.
_KNOWN_WEAPON = {
    "WHIP": "hits the side you face",
    "VAMPIRICA": "hits the side you face",
    "KNIFE": "fires the way you walk",
    "THOUSAND": "fires the way you walk",
    "GARLIC": "damages enemies that touch you",
    "MAGIC_MISSILE": "aims itself at the nearest enemy",
}

AURA_TYPES = frozenset({"GARLIC"})

_DIRECTION = {
    "N": "north",
    "NE": "northeast",
    "E": "east",
    "SE": "southeast",
    "S": "south",
    "SW": "southwest",
    "W": "west",
    "NW": "northwest",
}

_FLOAT = re.compile(r"\d+\.\d+")


def world_cell(x: float, y: float) -> tuple[int, int]:
    return (math.floor(x / CELL), math.floor(y / CELL))


def option_id(prefix: str, x: float, y: float) -> str:
    cx, cy = world_cell(x, y)
    return f"{prefix}_{cx}_{cy}"


def direction_name(dx: float, dy: float) -> str:
    return _DIRECTION[SECTOR_NAMES[sector_index(dx, dy)]]


def distance_band(dist: float, radii: Sequence[float]) -> str:
    if dist < radii[0]:
        return "close"
    if dist < radii[1]:
        return "medium"
    return "far"


def hp_band(ratio: float) -> str:
    if ratio >= 0.66:
        return "high"
    if ratio >= 0.35:
        return "medium"
    return "low"


def next_level_band(frac: float, known: bool) -> str:
    if not known:
        return "unknown"
    if frac >= 0.8:
        return "almost there"
    if frac >= 0.35:
        return "part way"
    return "early"


def count_bucket(count: int) -> str:
    if count <= 1:
        return "one"
    if count <= 3:
        return "a few"
    if count <= 7:
        return "a group"
    return "a large group"


def weapon_sentence(weapon: WeaponState) -> str:
    name = (weapon.type or "weapon").replace("_", " ").title()
    detail = _KNOWN_WEAPON.get((weapon.type or "").upper())
    if detail is None:
        cls = aim_class(weapon.type)
        if cls == AIM_FACING:
            detail = "hits the side you face"
        elif cls == AIM_MOVE:
            detail = "fires the way you walk"
        else:
            detail = "the game aims this, so walking does not steer it"
    evolved = ", evolved" if weapon.evo else ""
    return f"{name} lv{max(0, weapon.level)}{evolved}: {detail}"


def has_aura(weapons: Sequence[WeaponState]) -> bool:
    return any((weapon.type or "").upper() in AURA_TYPES for weapon in weapons)


def aura_reach(weapons: Sequence[WeaponState]) -> float:
    reaches = [weapon.area for weapon in weapons if weapon.area is not None and weapon.area > 0 and (weapon.type or "").upper() in AURA_TYPES]
    if reaches:
        return max(reaches)
    if has_aura(weapons):
        return DEFAULT_AURA_REACH
    return 0.0


def has_raw_measurement(text: str) -> bool:
    """True when a string contains a decimal. Jev-facing text must stay clear of those."""
    return _FLOAT.search(text) is not None
