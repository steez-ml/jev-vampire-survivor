"""Weapon aim classes: how movement steers each weapon. Not DPS — just *where it will hit*.

Keys are VampireSurvivors.Data.WeaponType enum names as published in player.weapons[].type
(read from this install's interop on 2026-09-19). Anything not listed is AIM_AUTO: the game aims it
(nearest enemy, random, orbit, aura), so our heading does not change where it lands.

- AIM_FACING: hits the horizontal side the sprite faces (whip family). Facing follows the last
  horizontal input, so any heading with an east/west component re-aims it.
- AIM_MOVE: fires along the last movement direction (knife family). The heading *is* the aim.
"""

from __future__ import annotations

from typing import Sequence

from .polar import HEADINGS, SECTORS, neighbors
from .snapshot import WeaponState

AIM_AUTO = "auto"
AIM_FACING = "facing"
AIM_MOVE = "move"

AIM_CLASS: dict[str, str] = {
    "WHIP": AIM_FACING,
    "VAMPIRICA": AIM_FACING,  # Bloody Tear (whip evolution)
    "KNIFE": AIM_MOVE,
    "THOUSAND": AIM_MOVE,  # Thousand Edge (knife evolution)
}

EAST_SECTORS = (1, 2, 3)
WEST_SECTORS = (5, 6, 7)
KILL_RING_WEIGHTS = (1.0, 0.6, 0.0)
AIM_MASS_SCALE = 6.0


def aim_class(weapon_type: str) -> str:
    return AIM_CLASS.get((weapon_type or "").upper(), AIM_AUTO)


def steerable_weapons(weapons: Sequence[WeaponState]) -> list[tuple[str, WeaponState]]:
    out = []
    for weapon in weapons:
        cls = aim_class(weapon.type)
        if cls != AIM_AUTO:
            out.append((cls, weapon))
    return out


def aim_bonus(
    weapons: Sequence[WeaponState],
    enemy_bins: Sequence[float],
    facing_x: int,
) -> list[float]:
    """Per-heading bonus in [0, 1]: how much killable mass this heading points our weapons at.

    Only the inner two rings count (that is what an early whip or knife actually reaches).
    Returns all zeros when no equipped weapon is steerable.
    """
    steerable = steerable_weapons(weapons)
    bonus = [0.0] * SECTORS
    if not steerable:
        return bonus

    side_mass = {1: _side_mass(enemy_bins, EAST_SECTORS), -1: _side_mass(enemy_bins, WEST_SECTORS)}
    for index, (hx, _hy) in enumerate(HEADINGS):
        total = 0.0
        for cls, _weapon in steerable:
            if cls == AIM_FACING:
                side = 1 if hx > 0 else -1 if hx < 0 else facing_x
                if side == 0:
                    continue
                total += _squash(side_mass[side])
            elif cls == AIM_MOVE:
                left, right = neighbors(index)
                mass = _sector_kill_mass(enemy_bins, index) + 0.5 * (
                    _sector_kill_mass(enemy_bins, left) + _sector_kill_mass(enemy_bins, right)
                )
                total += _squash(mass)
        bonus[index] = min(1.0, total / len(steerable))
    return bonus


def _sector_kill_mass(bins: Sequence[float], sector: int) -> float:
    total = 0.0
    for ring, weight in enumerate(KILL_RING_WEIGHTS):
        if weight <= 0.0:
            continue
        total += bins[ring * SECTORS + sector] * weight
    return total


def _side_mass(bins: Sequence[float], sectors: Sequence[int]) -> float:
    return sum(_sector_kill_mass(bins, s) for s in sectors)


def _squash(mass: float) -> float:
    if mass <= 0.0:
        return 0.0
    return min(1.0, mass / AIM_MASS_SCALE)
