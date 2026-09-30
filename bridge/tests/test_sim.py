"""Behavioural checks on the tiny arena: the scenarios that motivated v1."""

from __future__ import annotations

import unittest

from vampirejev import sim


class CorridorTests(unittest.TestCase):
    def test_v3_only_corridor_escapes_sideways_without_damage(self) -> None:
        world = sim.corridor(wall_channel=False)
        pilot, rows = sim.run(world, seconds=6.0)
        self.assertGreater(abs(world.x), 8.0, "should travel along the corridor, not pin against a wall")
        self.assertGreater(world.hp, 80.0)
        self.assertGreaterEqual(pilot.tracker.events, 1, "the stuck detector should have fired at least once")
        # After the walls are learned the heading settles on pure E or W.
        tail = [heading for _t, _x, _y, _hp, heading, _m, _b in rows[-20:]]
        self.assertTrue(all(h in ("E", "W") for h in tail), tail)

    def test_wall_channel_corridor_never_bumps(self) -> None:
        world = sim.corridor(wall_channel=True)
        pilot, rows = sim.run(world, seconds=6.0)
        self.assertGreater(abs(world.x), 15.0)
        self.assertEqual(pilot.tracker.events, 0, "with the wall channel it should never need to bump")
        self.assertTrue(all(heading in ("E", "W") for _t, _x, _y, _hp, heading, _m, _b in rows[4:]))

    def test_body_flags_calibrate_and_help(self) -> None:
        world = sim.corridor(wall_channel=False, body_flags=True)
        pilot, _rows = sim.run(world, seconds=6.0)
        self.assertGreater(abs(world.x), 8.0)
        # The arena reports Phaser-style "up" for +Y, so calibration must conclude "not flipped".
        self.assertIn(pilot.body_y_flipped, (False, None))


class AggressionTests(unittest.TestCase):
    def test_takes_a_guarded_pile_early_at_full_hp(self) -> None:
        world = sim.pile(hp=100.0, guards=2)
        sim.run(world, seconds=3.0)
        self.assertGreaterEqual(world.collected, 40.0)
        self.assertGreater(world.hp, 85.0)

    def test_walks_to_free_xp_with_no_enemies(self) -> None:
        world = sim.pile(hp=100.0, guards=0)
        sim.run(world, seconds=3.0)
        self.assertGreaterEqual(world.collected, 40.0)

    def test_leaves_the_pile_alone_at_low_hp(self) -> None:
        world = sim.pile(hp=20.0, guards=2)
        pilot, rows = sim.run(world, seconds=3.0)
        self.assertEqual(world.collected, 0.0)
        self.assertTrue(any(mode == "flee" for *_rest, mode, _b in rows))

    def test_late_dense_run_declines_what_early_takes(self) -> None:
        early = sim.pile(hp=100.0, guards=3, survived=30.0, enemies_stage=20)
        sim.run(early, seconds=4.0)
        late = sim.pile(hp=100.0, guards=3, survived=800.0, enemies_stage=150)
        sim.run(late, seconds=4.0)
        self.assertGreaterEqual(early.collected, 40.0, "early: three guards on a 40-XP pile are worth it")
        self.assertEqual(late.collected, 0.0, "late: the same pile is not worth it")
        self.assertGreater(late.hp, 95.0)

    def test_early_run_is_brave_against_chasing_guards(self) -> None:
        world = sim.pile(hp=100.0, guards=3, survived=30.0, enemies_stage=20)
        for guard in world.enemies:
            guard.speed = 1.5
        sim.run(world, seconds=4.0)
        self.assertGreaterEqual(world.collected, 40.0)
        self.assertLess(world.damage, 15.0, "walks in for the pile but does not linger in contact")


class KitingTests(unittest.TestCase):
    def test_kite_mode_moves_perpendicular_to_the_blob(self) -> None:
        world = sim.World(enemies_stage=80, survived=200.0)
        for i in range(30):
            world.enemies.append(sim.SimEnemy(-4.0 + 8.0 * (i / 29.0), -7.0 - (i % 4), speed=1.0))
        pilot, rows = sim.run(world, seconds=1.0, mode_lock="kite")
        first = rows[0][4]
        self.assertIn(first, ("E", "W", "NE", "NW"), first)

    def test_auto_mode_never_walks_into_the_blob(self) -> None:
        world = sim.World(enemies_stage=80, survived=200.0)
        for i in range(30):
            world.enemies.append(sim.SimEnemy(-4.0 + 8.0 * (i / 29.0), -7.0 - (i % 4), speed=1.0))
        _pilot, rows = sim.run(world, seconds=2.0)
        self.assertTrue(all(h not in ("S", "SE", "SW") for _t, _x, _y, _hp, h, _m, _b in rows), [r[4] for r in rows])
        self.assertGreater(world.hp, 95.0)


class HealTests(unittest.TestCase):
    def test_low_hp_picks_up_a_clear_chicken(self) -> None:
        world = sim.roast(hp=20.0, guards=0)
        sim.run(world, seconds=3.0)
        self.assertGreater(world.healed, 0.0)
        self.assertGreater(world.hp, 40.0)

    def test_low_hp_leaves_a_guarded_chicken(self) -> None:
        world = sim.roast(hp=20.0, guards=3)
        sim.run(world, seconds=3.0)
        self.assertEqual(world.healed, 0.0)
        self.assertGreater(world.hp, 15.0)

    def test_low_hp_breaks_a_clear_brazier(self) -> None:
        world = sim.altar(hp=20.0, guards=0)
        sim.run(world, seconds=3.0)
        self.assertGreater(world.healed, 0.0)

    def test_low_hp_leaves_a_guarded_brazier(self) -> None:
        world = sim.altar(hp=20.0, guards=3)
        sim.run(world, seconds=3.0)
        self.assertEqual(world.healed, 0.0)
        self.assertGreater(world.hp, 15.0)


if __name__ == "__main__":
    unittest.main()
