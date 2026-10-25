"""Tiny deterministic arena for offline checks: walls, chasing enemies, gems, a magnet, contact damage.

It is not Vampire Survivors. It exists so "north wall, blob south" or "gem pile under two enemies"
can be replayed in a unit test in milliseconds and produce the same v4-shaped GameState the real
plugin sends. Player collision is axis-separated like Phaser Arcade (you slide along walls).

    python -m vampirejev.sim corridor      # print a trajectory for the Library-style corridor
    python -m vampirejev.sim pile          # gem pile guarded by two enemies, early game
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .polar import CELLS, SECTORS, cell_index, sector_index
from .snapshot import (
    Bounds,
    Counts,
    EnemyStats,
    Entity,
    GameState,
    Perf,
    PlayerState,
    Polar,
    RunState,
    TypedPin,
    WeaponState,
    XpPile,
)

PLAYER_RADIUS = 0.4
DEFAULT_RADII = (3.0, 8.0, 20.0)


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, x: float, y: float, pad: float = 0.0) -> bool:
        return self.x0 - pad <= x <= self.x1 + pad and self.y0 - pad <= y <= self.y1 + pad


@dataclass
class SimEnemy:
    x: float
    y: float
    speed: float = 2.0
    boss: bool = False
    vx: float = 0.0
    vy: float = 0.0
    type: str = ""
    hp: float = 0.0
    hp_max: float = 0.0
    uid: str = ""


@dataclass
class SimGem:
    x: float
    y: float
    value: float = 1.0


@dataclass
class World:
    walls: list[Rect] = field(default_factory=list)
    enemies: list[SimEnemy] = field(default_factory=list)
    gems: list[SimGem] = field(default_factory=list)
    chests: list[tuple[float, float]] = field(default_factory=list)
    pickups: list[TypedPin] = field(default_factory=list)
    destructibles: list[TypedPin] = field(default_factory=list)
    bounds: Optional[Bounds] = None
    x: float = 0.0
    y: float = 0.0
    hp: float = 100.0
    hp_max: float = 100.0
    player_speed: float = 4.0
    contact_radius: float = 0.7
    contact_dps: float = 8.0
    magnet: float = 1.0
    radii: tuple[float, float, float] = DEFAULT_RADII
    survived: float = 0.0
    enemies_stage: int = 0
    level: int = 1
    xp: float = 0.0
    xp_next: float = 20.0
    weapons: list[WeaponState] = field(default_factory=list)
    catalog: list[EnemyStats] = field(default_factory=list)
    wall_channel: bool = False
    body_flags: bool = False
    facing_x: int = 1
    seq: int = 0
    collected: float = 0.0
    damage: float = 0.0
    healed: float = 0.0
    last_blocked: frozenset[str] = frozenset()

    def step(self, keys: Iterable[str], dt: float = 0.05) -> None:
        keyset = set(keys)
        mx = (1.0 if "D" in keyset else 0.0) - (1.0 if "A" in keyset else 0.0)
        my = (1.0 if "W" in keyset else 0.0) - (1.0 if "S" in keyset else 0.0)
        mag = math.hypot(mx, my)
        blocked = set()
        if mag > 0.0:
            mx = mx / mag * self.player_speed * dt
            my = my / mag * self.player_speed * dt
            if mx > 0:
                self.facing_x = 1
            elif mx < 0:
                self.facing_x = -1
            nx = self.x + mx
            if self._hits_wall(nx, self.y):
                blocked.add("right" if mx > 0 else "left")
                nx = self.x
            ny = self.y + my
            if self._hits_wall(nx, ny):
                blocked.add("up" if my > 0 else "down")
                ny = self.y
            self.x, self.y = nx, ny
        self.last_blocked = frozenset(blocked)

        for enemy in self.enemies:
            dx = self.x - enemy.x
            dy = self.y - enemy.y
            dist = math.hypot(dx, dy)
            if dist > 1e-6 and enemy.speed > 0.0:
                enemy.vx = dx / dist * enemy.speed
                enemy.vy = dy / dist * enemy.speed
                enemy.x += enemy.vx * dt
                enemy.y += enemy.vy * dt
            else:
                enemy.vx = 0.0
                enemy.vy = 0.0
            if dist <= self.contact_radius:
                hit = self.contact_dps * dt
                self.hp = max(0.0, self.hp - hit)
                self.damage += hit

        remaining = []
        for gem in self.gems:
            if math.hypot(gem.x - self.x, gem.y - self.y) <= self.magnet:
                self.collected += gem.value
                self.xp += gem.value
                while self.xp >= self.xp_next:
                    self.xp -= self.xp_next
                    self.level += 1
                    self.xp_next *= 1.2
            else:
                remaining.append(gem)
        self.gems = remaining

        leftover_props = []
        for prop in self.destructibles:
            if math.hypot(prop.x - self.x, prop.y - self.y) <= self.contact_radius * 1.4:
                # Breaking a brazier always drops a chicken in the sim (the lucky case).
                self.pickups.append(TypedPin("ROAST", prop.x, prop.y))
            else:
                leftover_props.append(prop)
        self.destructibles = leftover_props

        leftover_pickups = []
        for pin in self.pickups:
            if math.hypot(pin.x - self.x, pin.y - self.y) <= max(self.magnet, self.contact_radius):
                if pin.type.upper() in {"ROAST", "ALWAYS_ROAST", "LITTLEHEART", "TP_WALL_CHICKEN"}:
                    heal = 0.30 * self.hp_max
                    self.hp = min(self.hp_max, self.hp + heal)
                    self.healed += heal
            else:
                leftover_pickups.append(pin)
        self.pickups = leftover_pickups
        self.survived += dt

    def _hits_wall(self, x: float, y: float) -> bool:
        return any(wall.contains(x, y, PLAYER_RADIUS) for wall in self.walls)

    def wall_at(self, x: float, y: float) -> bool:
        return any(wall.contains(x, y) for wall in self.walls)

    def snapshot(self) -> GameState:
        self.seq += 1
        r0, r1, r2 = self.radii
        enemy_bins = [0.0] * CELLS
        xp_bins = [0.0] * CELLS
        pins: list[tuple[float, Entity]] = []
        bosses: list[Entity] = []
        for enemy in self.enemies:
            dx = enemy.x - self.x
            dy = enemy.y - self.y
            enemy_bins[cell_index(dx, dy, self.radii)] += 1.0
            dist2 = dx * dx + dy * dy
            if enemy.boss:
                bosses.append(Entity(enemy.x, enemy.y, type=enemy.type, hp=enemy.hp or None, hp_max=enemy.hp_max or None, uid=enemy.uid))
            if dist2 < r0 * r0:
                pins.append(
                    (
                        dist2,
                        Entity(
                            enemy.x,
                            enemy.y,
                            enemy.vx,
                            enemy.vy,
                            enemy.type,
                            enemy.hp or None,
                            enemy.hp_max or None,
                            enemy.uid,
                        ),
                    )
                )
        pins.sort(key=lambda item: item[0])
        for gem in self.gems:
            xp_bins[cell_index(gem.x - self.x, gem.y - self.y, self.radii)] += gem.value
        wall_bins = probe_walls(self.x, self.y, self.radii, self.wall_at) if self.wall_channel else None
        player = PlayerState(
            x=self.x,
            y=self.y,
            hp=self.hp,
            hp_max=self.hp_max,
            speed=self.player_speed,
            radius=PLAYER_RADIUS,
            level=self.level,
            xp=self.xp,
            xp_next=self.xp_next,
            magnet=self.magnet,
            facing_x=self.facing_x,
            blocked=self.last_blocked if self.body_flags else frozenset(),
            has_blocked=self.body_flags,
            weapons=list(self.weapons),
        )
        return GameState(
            schema_version=4,
            seq=self.seq,
            t_ms=int(round(self.survived * 1000.0)),
            run=RunState(running=True, paused=False, level_up=False, survived_seconds=self.survived),
            player=player,
            bounds=self.bounds,
            polar=Polar(radii=self.radii, enemy=enemy_bins, xp=xp_bins, wall=wall_bins),
            enemies=[pin for _d, pin in pins[:8]],
            bosses=bosses[:4],
            chests=[Entity(x, y) for x, y in self.chests[:8]],
            pickups=list(self.pickups[:8]),
            destructibles=list(self.destructibles[:8]),
            xp_piles=_cluster_gems(self.gems),
            enemy_catalog=list(self.catalog),
            counts=Counts(
                enemies_stage=max(self.enemies_stage, len(self.enemies)),
                enemies_published=min(8, len(pins)),
                gems_stage=len(self.gems),
                gems_published=len(self.gems),
                chests_stage=len(self.chests),
                chests_published=min(8, len(self.chests)),
                bosses_published=len(bosses[:4]),
                tilemaps=1 if self.wall_channel else 0,
                pickups_stage=len(self.pickups),
                pickups_published=min(8, len(self.pickups)),
                destructibles_stage=len(self.destructibles),
                destructibles_published=min(8, len(self.destructibles)),
            ),
            perf=Perf(),
        )


def _cluster_gems(gems: list[SimGem], radius: float = 2.5) -> list[XpPile]:
    piles: list[XpPile] = []
    for gem in gems:
        placed = False
        for pile in piles:
            if math.hypot(pile.x - gem.x, pile.y - gem.y) <= radius:
                total = pile.value + gem.value
                if total > 0:
                    pile.x = (pile.x * pile.value + gem.x * gem.value) / total
                    pile.y = (pile.y * pile.value + gem.y * gem.value) / total
                pile.value = total
                placed = True
                break
        if not placed:
            piles.append(XpPile(gem.x, gem.y, gem.value))
    piles.sort(key=lambda pile: -pile.value)
    return piles[:8]


def probe_walls(px: float, py: float, radii: tuple[float, float, float], wall_at) -> list[float]:
    """Same sampling geometry as the C# ProbeCell: 6 / 3 / 1 samples per ring."""
    r0, r1, r2 = radii
    bins = [0.0] * CELLS
    for sector in range(SECTORS):
        center = sector * (math.pi / 4.0)
        bins[sector] = _probe_cell(px, py, center, 0.0, r0, 6, wall_at)
        bins[SECTORS + sector] = _probe_cell(px, py, center, r0, r1, 3, wall_at)
        bins[2 * SECTORS + sector] = _probe_cell(px, py, center, r1, r2, 1, wall_at)
    return bins


def _probe_cell(px: float, py: float, center: float, r_lo: float, r_hi: float, samples: int, wall_at) -> float:
    span = r_hi - r_lo
    if span <= 0.01:
        return 0.0
    angles = 3 if samples >= 3 else 1
    radii = 2 if samples >= 6 else 1
    hits = 0
    total = 0
    for ai in range(angles):
        angle = center + ((ai - 1) * (math.pi / 12.0) if angles == 3 else 0.0)
        dir_x = math.sin(angle)
        dir_y = math.cos(angle)
        for ri in range(radii):
            frac = (0.4 if ri == 0 else 0.85) if radii == 2 else 0.5
            radius = r_lo + span * frac
            total += 1
            if wall_at(px + dir_x * radius, py + dir_y * radius):
                hits += 1
    return hits / total if total else 0.0


# --- ready-made scenarios -------------------------------------------------------------------------


def corridor(wall_channel: bool = False, body_flags: bool = False, enemies: int = 12) -> World:
    """Library-style: open east-west, walls just north and south, a slow blob coming from the south."""
    world = World(
        walls=[Rect(-200.0, 3.0, 200.0, 40.0), Rect(-200.0, -40.0, 200.0, -3.0)],
        wall_channel=wall_channel,
        body_flags=body_flags,
        enemies_stage=40,
    )
    for i in range(enemies):
        fx = -3.0 + 6.0 * (i / max(1, enemies - 1))
        world.enemies.append(SimEnemy(fx, -2.4 - 0.4 * (i % 3), speed=1.6))
    world.survived = 60.0
    return world


def pile(hp: float = 100.0, guards: int = 2, survived: float = 30.0, enemies_stage: int = 20, value: float = 40.0) -> World:
    """A juicy gem pile a few units east, with a couple of enemies standing on it."""
    world = World(hp=hp, enemies_stage=enemies_stage, survived=survived)
    world.gems.append(SimGem(4.5, 0.0, value))
    for i in range(guards):
        world.enemies.append(SimEnemy(4.2 + 0.6 * (i % 2), 0.5 - 1.0 * (i % 2), speed=0.0))
    return world


def roast(hp: float = 20.0, guards: int = 0) -> World:
    """A chicken on the ground to the east. Optional guards standing on it."""
    world = World(hp=hp, survived=40.0, enemies_stage=max(8, guards * 4))
    world.pickups.append(TypedPin("ROAST", 4.5, 0.0))
    for i in range(guards):
        world.enemies.append(SimEnemy(4.2 + 0.6 * (i % 2), 0.5 - 1.0 * (i % 2), speed=0.0))
    return world


def altar(hp: float = 20.0, guards: int = 0) -> World:
    """A Mad Forest brazier to the east. Breaking it drops a chicken in this sim."""
    world = World(hp=hp, survived=40.0, enemies_stage=max(8, guards * 4))
    world.destructibles.append(TypedPin("BRAZIER", 4.5, 0.0))
    for i in range(guards):
        world.enemies.append(SimEnemy(4.2 + 0.6 * (i % 2), 0.5 - 1.0 * (i % 2), speed=0.0))
    return world


def run_mind(world: World, seconds: float, dt: float = 0.05, controller: str = "code", trace: bool = False):
    """Drive the world with the new motor. Returns (mind, rows)."""
    from .mind import Mind
    from .wasd import heading_to_keys

    mind = Mind(controller=controller, sync=True)
    keys: frozenset[str] = frozenset()
    rows = []
    steps = int(round(seconds / dt))
    try:
        for i in range(steps):
            snapshot = world.snapshot()
            out = mind.step(snapshot, keys, i * dt)
            keys = heading_to_keys(out.command.dx, out.command.dy)
            rows.append((world.survived, world.x, world.y, world.hp, out.command.heading, out.decider, out.option_id))
            if trace and i % int(round(0.25 / dt)) == 0:
                t, x, y, hp, heading, decider, option = rows[-1]
                print(f"t={t:6.2f} x={x:7.2f} y={y:6.2f} hp={hp:5.1f} heading={heading:<2} {decider:<6} {option}")
            world.step(keys, dt)
    finally:
        mind.close()
    return mind, rows


def _stage(**kwargs) -> World:
    """Mad Forest sized rings, plus a tiny enemy table so frail and tanky are different."""
    world = World(radii=(6.0, 16.0, 40.0), magnet=1.2, **kwargs)
    world.catalog = [EnemyStats("BAT", 8, 1.5), EnemyStats("TANK", 500, 0.8)]
    return world


def open_gem() -> World:
    """An unguarded gem pile two steps to the east."""
    world = _stage()
    world.gems.append(SimGem(2.2, 0.0, 12))
    return world


def clear_xp() -> World:
    """Low HP, a blob to the south, and a gem pile sitting in the clear to the east."""
    world = _stage(hp=20, survived=40, enemies_stage=12)
    world.gems.append(SimGem(5.0, 0.4, 30))
    for i in range(4):
        world.enemies.append(SimEnemy(-0.4 + 0.3 * i, -3.2, speed=0.6, type="TANK", hp=500, hp_max=500, uid=f"tank{i}"))
    return world


def whip_line(heavy: bool = False) -> World:
    """Gems to the east. A line of bats on the way, or one tank in that same spot."""
    world = _stage(weapons=[WeaponState("WHIP", 2)])
    world.gems.append(SimGem(8.0, 0.0, 40))
    if heavy:
        world.enemies.append(SimEnemy(3.0, 0.0, speed=0.0, type="TANK", hp=500, hp_max=500, uid="tank"))
    else:
        for i in range(3):
            world.enemies.append(SimEnemy(2.4 + 0.7 * i, 0.3 - 0.3 * i, speed=0.0, type="BAT", hp=8, hp_max=8, uid=f"bat{i}"))
    return world


def garlic_swarm(boss: bool = False) -> World:
    """Bats held at garlic range, or a boss in the same place, which is not a place to stand."""
    world = _stage(weapons=[WeaponState("GARLIC", 2)])
    if boss:
        world.enemies.append(SimEnemy(3.2, 0.0, speed=0.0, boss=True, type="BOSS", hp=1000, hp_max=1000, uid="boss"))
    else:
        for i in range(6):
            world.enemies.append(
                SimEnemy(3.6 + (i % 3) * 0.6, -0.8 + (i // 3) * 1.6, speed=0.0, type="BAT", hp=8, hp_max=8, uid=f"bat{i}")
            )
    return world


def low_chicken() -> World:
    world = _stage(hp=20, survived=50, enemies_stage=8)
    world.pickups.append(TypedPin("ROAST", 4.5, 0.0))
    return world


def low_brazier() -> World:
    world = _stage(hp=20, survived=50, enemies_stage=8)
    world.destructibles.append(TypedPin("BRAZIER", 4.5, 0.0))
    return world


def run(world: World, seconds: float, dt: float = 0.05, mode_lock: Optional[str] = None, trace: bool = False):
    """Drive the world with a Pilot. Returns (pilot, trace rows)."""
    from .pilot import Pilot
    from .wasd import heading_to_keys

    pilot = Pilot(mode_lock=mode_lock)
    keys: frozenset[str] = frozenset()
    rows = []
    steps = int(round(seconds / dt))
    for i in range(steps):
        snapshot = world.snapshot()
        out = pilot.step(snapshot, keys, i * dt)
        keys = heading_to_keys(out.command.dx, out.command.dy)
        rows.append((world.survived, world.x, world.y, world.hp, out.command.heading, out.mode, "".join(sorted(out.blocked))))
        if trace and i % int(round(0.25 / dt)) == 0:
            t, x, y, hp, heading, mode, blocked = rows[-1]
            print(f"t={t:6.2f} x={x:7.2f} y={y:6.2f} hp={hp:5.1f} heading={heading:<2} mode={mode:<5} blocked={blocked or '-'}")
        world.step(keys, dt)
    return pilot, rows


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    scenario = args[0] if args else "corridor"
    if scenario == "corridor":
        world = corridor(wall_channel="--walls" in args, body_flags="--body" in args)
        seconds = 6.0
    elif scenario == "pile":
        world = pile(hp=20.0 if "--lowhp" in args else 100.0)
        seconds = 4.0
    elif scenario == "roast":
        world = roast(hp=20.0, guards=3 if "--guards" in args else 0)
        seconds = 4.0
    elif scenario == "altar":
        world = altar(hp=20.0, guards=3 if "--guards" in args else 0)
        seconds = 4.0
        pilot, _rows = run(world, seconds, trace=True)
        print(
            f"done: x={world.x:.2f} y={world.y:.2f} hp={world.hp:.1f} collected={world.collected:.0f} "
            f"healed={world.healed:.1f} stuck_events={pilot.tracker.events} walls_remembered={len(pilot.memory)}"
        )
        return 0
    elif scenario in {"open-gem", "clear-xp", "whip", "whip-heavy", "garlic", "garlic-boss", "chicken", "brazier"}:
        world = {
            "open-gem": open_gem,
            "clear-xp": clear_xp,
            "whip": whip_line,
            "whip-heavy": lambda: whip_line(True),
            "garlic": garlic_swarm,
            "garlic-boss": lambda: garlic_swarm(True),
            "chicken": low_chicken,
            "brazier": low_brazier,
        }[scenario]()
        _mind, _rows = run_mind(world, 3.0, trace=True)
        print(f"done: x={world.x:.2f} y={world.y:.2f} hp={world.hp:.1f} collected={world.collected:.0f} healed={world.healed:.1f}")
        return 0
    else:
        print(
            "scenarios: corridor [--walls] [--body], pile [--lowhp], roast [--guards], altar [--guards], "
            "open-gem, clear-xp, whip, whip-heavy, garlic, garlic-boss, chicken, brazier",
            file=sys.stderr,
        )
        return 2
    pilot, _rows = run(world, seconds, trace=True)
    print(
        f"done: x={world.x:.2f} y={world.y:.2f} hp={world.hp:.1f} collected={world.collected:.0f} "
        f"healed={world.healed:.1f} stuck_events={pilot.tracker.events} walls_remembered={len(pilot.memory)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
