"""Base toughness for Mad Forest enemy types, used only when a snapshot has no catalog.

The names are VampireSurvivors.Data.EnemyType values read from this install's interop
on 2026-10-24 (see the PlayerPositionProbe doc comment). The health figures are not
from that assembly. EnemyData.maxHp exists, but the numbers live in packed assets,
so each row cites the public wiki and is unchecked against this copy of the game.

Bands use the wiki's base Health, the level-1 pool, before the stage scales it:

- frail: 15 or less, and the page does not say the health grows with the player's level
- sturdy: 16 to 100, same condition
- tanky: above 100, or the page says "HP x Level"

A type that is not listed stays unknown. Unknown stays dangerous.
Source: https://vampire.survivors.wiki/ retrieved 2026-10-24. Unchecked.
"""

from __future__ import annotations

FRAIL = "frail"
STURDY = "sturdy"
TANKY = "tanky"

# type -> (band, source note)
_ROWS: dict[str, tuple[str, str]] = {
    # https://vampire.survivors.wiki/w/Pipeestrello
    "BAT1": (FRAIL, "Pipeestrello 1, base health 1"),
    "BAT2": (FRAIL, "Pipeestrello 2, base health 5"),
    "BAT3": (FRAIL, "Pipeestrello 3, base health 5"),
    "BATSWARM": (FRAIL, "Pipeestrello swarm, base health 1"),
    "BAT4": (TANKY, "Pipeestrello 4, base health 50 and HP x Level"),
    "BAT5": (TANKY, "Pipeestrello 5, base health 50 and HP x Level"),
    # https://vampire.survivors.wiki/w/Zombie
    "ZOMBIE": (FRAIL, "Zombie, base health 10"),
    # https://vampire.survivors.wiki/w/Skeleton
    "SKELETON": (FRAIL, "Skeleton, base health 15"),
    "SKELETON2": (FRAIL, "Skeleton, base health 15"),
    "SKELETON3": (FRAIL, "Skeleton, base health 15"),
    "SKELETON4": (FRAIL, "Skeleton, base health 15"),
    # https://vampire.survivors.wiki/w/Mudman
    "MUDMAN1": (STURDY, "Mudman 1, base health 70"),
    "MUDMAN2": (TANKY, "Mudman 2, base health 150"),
    # https://vampire.survivors.wiki/w/Giant_Bat
    "BOSS_XLBAT": (TANKY, "Giant Bat boss, base health 500 and HP x Level"),
}

MAD_FOREST_BANDS: dict[str, str] = {name: band for name, (band, _note) in _ROWS.items()}
MAD_FOREST_NOTES: dict[str, str] = {name: note for name, (_band, note) in _ROWS.items()}
