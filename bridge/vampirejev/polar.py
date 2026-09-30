"""Polar occupancy helpers. Must match C# PolarGrid: sector 0 is +Y (north / W)."""

from __future__ import annotations

import math
from typing import Sequence

RINGS = 3
SECTORS = 8
CELLS = RINGS * SECTORS
SECTOR_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
HEADINGS = (
    (0.0, 1.0),
    (1.0, 1.0),
    (1.0, 0.0),
    (1.0, -1.0),
    (0.0, -1.0),
    (-1.0, -1.0),
    (-1.0, 0.0),
    (-1.0, 1.0),
)
DEFAULT_RADII = (6.0, 16.0, 40.0)


def sector_index(dx: float, dy: float) -> int:
    if dx * dx + dy * dy < 1e-8:
        return 0
    angle = math.atan2(dx, dy)
    angle += math.pi / 8.0
    two_pi = math.pi * 2.0
    if angle < 0.0:
        angle += two_pi
    if angle >= two_pi:
        angle -= two_pi
    sector = int(angle / two_pi * SECTORS)
    if sector < 0 or sector >= SECTORS:
        return 0
    return sector


def ring_index(dist: float, radii: Sequence[float] = DEFAULT_RADII) -> int:
    r0, r1, r2 = radii[0], radii[1], radii[2]
    if dist < r0:
        return 0
    if dist < r1:
        return 1
    return 2


def cell_index(dx: float, dy: float, radii: Sequence[float] = DEFAULT_RADII) -> int:
    dist = math.hypot(dx, dy)
    return ring_index(dist, radii) * SECTORS + sector_index(dx, dy)


def heading_unit(index: int) -> tuple[float, float]:
    hx, hy = HEADINGS[index % SECTORS]
    mag = math.hypot(hx, hy)
    return (hx / mag, hy / mag)


def neighbors(index: int) -> tuple[int, int]:
    return ((index - 1) % SECTORS, (index + 1) % SECTORS)


def sector_mass(bins: Sequence[float], sector: int, ring_weights: Sequence[float]) -> float:
    total = 0.0
    for ring, weight in enumerate(ring_weights[:RINGS]):
        total += bins[ring * SECTORS + sector] * weight
    return total


def center_of_mass_dir(bins: Sequence[float], ring_weights: Sequence[float]) -> tuple[float, float, float]:
    """Unit direction toward the weighted enemy mass and the total weight. (0,0,0) when empty."""
    sx = 0.0
    sy = 0.0
    total = 0.0
    for ring, weight in enumerate(ring_weights[:RINGS]):
        for sector in range(SECTORS):
            mass = bins[ring * SECTORS + sector] * weight
            if mass <= 0.0:
                continue
            ux, uy = heading_unit(sector)
            sx += ux * mass
            sy += uy * mass
            total += mass
    mag = math.hypot(sx, sy)
    if mag < 1e-9 or total <= 0.0:
        return (0.0, 0.0, total)
    return (sx / mag, sy / mag, total)


def hottest_xp_sector(xp: Sequence[float]) -> str:
    best = -1
    best_val = 0.0
    for i, value in enumerate(xp):
        if value > best_val:
            best_val = value
            best = i
    if best < 0:
        return "—"
    return SECTOR_NAMES[best % SECTORS]


def inner_enemy_mass(enemy: Sequence[float]) -> float:
    return float(sum(enemy[:SECTORS]))


def empty_bins() -> list[float]:
    return [0.0] * CELLS
