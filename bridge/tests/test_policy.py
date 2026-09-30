from __future__ import annotations

import unittest

from vampirejev.polar import SECTOR_NAMES, empty_bins
from vampirejev.policy import Context, decide, decide_ex, phase_of
from vampirejev.snapshot import Bounds, Counts, Entity, GameState, PlayerState, Polar, RunState, TypedPin, WeaponState
from vampirejev.wasd import heading_to_keys


def _state(
    *,
    hp: float = 100.0,
    hp_max: float = 100.0,
    xp: list[float] | None = None,
    enemy: list[float] | None = None,
    wall: list[float] | None = None,
    enemies: list[Entity] | None = None,
    bosses: list[Entity] | None = None,
    chests: list[Entity] | None = None,
    bounds: Bounds | None = None,
    survived: float = 8.0,
    enemies_stage: int = 0,
    weapons: list[WeaponState] | None = None,
    facing_x: int = 1,
    xp_frac: float = 0.0,
    pickups: list[TypedPin] | None = None,
    destructibles: list[TypedPin] | None = None,
) -> GameState:
    return GameState(
        run=RunState(running=True, paused=False, level_up=False, survived_seconds=survived),
        player=PlayerState(
            x=0.0,
            y=0.0,
            hp=hp,
            hp_max=hp_max,
            weapons=weapons or [],
            facing_x=facing_x,
            xp=xp_frac * 10.0,
            xp_next=10.0 if xp_frac > 0 else 0.0,
        ),
        bounds=bounds,
        polar=Polar(
            enemy=enemy if enemy is not None else empty_bins(),
            xp=xp if xp is not None else empty_bins(),
            wall=wall,
        ),
        enemies=enemies or [],
        bosses=bosses or [],
        chests=chests or [],
        pickups=pickups or [],
        destructibles=destructibles or [],
        counts=Counts(enemies_stage=enemies_stage),
    )


class PolicyTests(unittest.TestCase):
    def test_xp_only_east_presses_d(self) -> None:
        xp = empty_bins()
        xp[2] = 12.0
        command = decide(_state(xp=xp))
        self.assertEqual(command.heading, "E")
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset({"D"}))

    def test_small_free_xp_beats_a_far_blob(self) -> None:
        # The ignore-XP bug: a handful of gems due east, a crowd on the far south ring.
        xp = empty_bins()
        xp[2] = 3.0
        enemy = empty_bins()
        enemy[16 + 4] = 10.0
        command = decide(_state(xp=xp, enemy=enemy))
        self.assertEqual(command.heading, "E")

    def test_inner_enemy_north_does_not_walk_north(self) -> None:
        enemy = empty_bins()
        enemy[0] = 4.0
        command = decide(_state(enemy=enemy, enemies=[Entity(x=0.0, y=2.0)]))
        self.assertNotEqual(command.heading, "N")
        self.assertNotEqual(heading_to_keys(command.dx, command.dy), frozenset({"W"}))

    def test_low_hp_prefers_flee_over_chest(self) -> None:
        enemy = empty_bins()
        enemy[10] = 2.0
        chest = [Entity(x=20.0, y=0.0)]
        brave = decide(_state(hp=100.0, enemy=enemy, chests=chest))
        scared = decide(_state(hp=8.0, enemy=enemy, chests=chest))
        self.assertEqual(brave.heading, "E")
        self.assertNotEqual(scared.heading, "E")

    def test_nudge_still_wins(self) -> None:
        xp = empty_bins()
        xp[2] = 20.0
        command = decide(_state(xp=xp), nudge="N")
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset({"W"}))

    def test_empty_world_is_idle(self) -> None:
        command = decide(_state())
        self.assertTrue(command.is_idle)

    def test_missing_snapshot_is_idle(self) -> None:
        self.assertTrue(decide(None).is_idle)


class PricedContactTests(unittest.TestCase):
    def test_one_bat_on_a_pile_is_worth_it_early(self) -> None:
        xp = empty_bins()
        xp[2] = 30.0
        enemy = empty_bins()
        enemy[2] = 1.0
        command = decide(_state(xp=xp, enemy=enemy, enemies=[Entity(x=2.0, y=0.0)]))
        self.assertEqual(command.heading, "E")

    def test_same_pile_late_and_dense_is_declined(self) -> None:
        xp = empty_bins()
        xp[2] = 30.0
        enemy = empty_bins()
        enemy[2] = 3.0
        pins = [Entity(x=2.0, y=0.0), Entity(x=2.2, y=0.4), Entity(x=2.2, y=-0.4)]
        early = decide(_state(xp=xp, enemy=enemy, enemies=pins))
        late = decide(_state(xp=xp, enemy=enemy, enemies=pins, survived=850.0, enemies_stage=160))
        self.assertEqual(early.heading, "E")
        self.assertNotEqual(late.heading, "E")

    def test_phase_dial(self) -> None:
        self.assertAlmostEqual(phase_of(_state(survived=0.0)), 0.0)
        self.assertGreater(phase_of(_state(survived=600.0)), 0.3)
        self.assertEqual(phase_of(_state(survived=900.0, enemies_stage=150)), 1.0)

    def test_two_contacts_early_are_priced_not_forbidden(self) -> None:
        enemy = empty_bins()
        enemy[2] = 2.0
        pins = [Entity(x=1.5, y=0.3), Entity(x=1.6, y=-0.3)]
        decision = decide_ex(_state(enemy=enemy, enemies=pins))
        self.assertFalse(decision.vetoed[2], "early game, two bats ahead is priced, not forbidden")
        self.assertGreater(decision.contacts[2], decision.contacts[6], "walking at them is a contact, walking away is not")
        self.assertLess(decision.scores[2], decision.scores[6])
        self.assertFalse(decision.command.is_idle)

    def test_walking_into_an_approaching_enemy_counts_before_it_arrives(self) -> None:
        # 2.5 units away, outside personal space (3.0 in the test radii) once our own step is ignored
        # ... but we close ~2 units in 0.3 s, so heading straight at it is a predicted contact.
        pins = [Entity(x=0.0, y=4.5, vx=0.0, vy=-1.0)]
        decision = decide_ex(_state(enemies=pins))
        self.assertGreaterEqual(decision.contacts[0], 1.0)
        self.assertEqual(decision.contacts[4], 0.0)

    def test_surrounded_still_moves(self) -> None:
        # Corner (all four cardinals are walls) plus a boss on every diagonal: nothing is allowed.
        bosses = [Entity(x=5.0 * dx, y=5.0 * dy) for dx, dy in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
        decision = decide_ex(_state(bosses=bosses), context=Context(blocked_live=frozenset({"N", "E", "S", "W"})))
        self.assertTrue(all(decision.vetoed))
        self.assertFalse(decision.command.is_idle)
        self.assertEqual(decision.reason, "all-vetoed")

    def test_boss_nearby_is_a_hard_veto(self) -> None:
        xp = empty_bins()
        xp[0] = 40.0
        decision = decide_ex(_state(xp=xp, bosses=[Entity(x=0.0, y=5.0)]))
        self.assertTrue(decision.vetoed[0])
        self.assertNotEqual(decision.command.heading, "N")


class WallTests(unittest.TestCase):
    def test_live_blocked_cardinal_is_vetoed(self) -> None:
        xp = empty_bins()
        xp[0] = 20.0
        decision = decide_ex(_state(xp=xp), context=Context(blocked_live=frozenset({"N"})))
        self.assertTrue(decision.vetoed[0])
        self.assertIn(decision.command.heading, ("NE", "NW", "E", "W"))

    def test_wall_bins_steer_away_from_the_wall(self) -> None:
        xp = empty_bins()
        xp[0] = 6.0
        xp[2] = 5.0
        wall = empty_bins()
        wall[0] = 1.0  # ring 0 north is solid
        wall[8] = 1.0
        without = decide(_state(xp=xp))
        with_wall = decide(_state(xp=xp, wall=wall))
        self.assertEqual(without.heading, "N")
        self.assertEqual(with_wall.heading, "E")

    def test_recent_walls_form_a_corridor_prior(self) -> None:
        enemy = empty_bins()
        enemy[SECTOR_NAMES.index("S") + 8] = 6.0  # blob to the south, mid ring
        context = Context(recent_walls={"N": 1.0, "S": 1.0})
        decision = decide_ex(_state(enemy=enemy), context=context)
        self.assertIn(decision.command.heading, ("E", "W"))

    def test_memory_penalty_is_soft(self) -> None:
        xp = empty_bins()
        xp[0] = 60.0  # a huge pile north outweighs a remembered wall
        decision = decide_ex(_state(xp=xp), context=Context(blocked_memory=frozenset({"N"})))
        self.assertFalse(decision.vetoed[0])
        self.assertIn(decision.command.heading, ("N", "NE", "NW"))


class ModeAndWeaponTests(unittest.TestCase):
    def test_modes(self) -> None:
        self.assertEqual(decide_ex(_state()).mode, "farm")
        self.assertEqual(decide_ex(_state(hp=20.0)).mode, "flee")
        dense = [3.0] * 8 + [0.0] * 16
        self.assertEqual(decide_ex(_state(enemy=dense)).mode, "kite")
        self.assertEqual(decide_ex(_state(chests=[Entity(x=30.0, y=0.0)])).mode, "chest")

    def test_hunger_near_level_up_raises_xp_weight(self) -> None:
        xp = empty_bins()
        xp[2] = 8.0
        enemy = empty_bins()
        enemy[2] = 2.0
        calm = decide_ex(_state(xp=xp, enemy=enemy))
        hungry = decide_ex(_state(xp=xp, enemy=enemy, xp_frac=0.95))
        self.assertGreater(hungry.scores[2], calm.scores[2])

    def test_whip_turns_toward_thin_killable_mass(self) -> None:
        enemy = empty_bins()
        enemy[8 + 2] = 2.0  # two enemies mid ring east
        plain = decide_ex(_state(enemy=enemy, facing_x=-1))
        whip = decide_ex(_state(enemy=enemy, facing_x=-1, weapons=[WeaponState("WHIP", 1)]))
        self.assertGreater(whip.scores[2] - plain.scores[2], 0.0)

    def test_stickiness_breaks_ties(self) -> None:
        xp = empty_bins()
        xp[0] = 5.0
        xp[2] = 5.0
        decision = decide_ex(_state(xp=xp), context=Context(previous=2))
        self.assertEqual(decision.command.heading, "E")


class LootTests(unittest.TestCase):
    def test_low_hp_walks_to_a_clear_roast(self) -> None:
        roast = [TypedPin("ROAST", 8.0, 0.0)]
        decision = decide_ex(_state(hp=20.0, pickups=roast))
        self.assertEqual(decision.mode, "flee")
        self.assertEqual(decision.command.heading, "E")

    def test_low_hp_does_not_walk_through_enemies_for_a_roast(self) -> None:
        roast = [TypedPin("ROAST", 8.0, 0.0)]
        enemy = empty_bins()
        enemy[2] = 3.0
        pins = [Entity(x=2.0, y=0.3), Entity(x=2.1, y=-0.3)]
        decision = decide_ex(_state(hp=20.0, pickups=roast, enemy=enemy, enemies=pins))
        self.assertNotEqual(decision.command.heading, "E")

    def test_low_hp_walks_to_a_clear_brazier(self) -> None:
        decision = decide_ex(_state(hp=20.0, destructibles=[TypedPin("BRAZIER", 8.0, 0.0)]))
        self.assertEqual(decision.command.heading, "E")

    def test_chest_behind_inner_enemies_is_not_worth_it(self) -> None:
        enemy = empty_bins()
        enemy[2] = 4.0
        pins = [Entity(x=2.0, y=0.4), Entity(x=2.1, y=-0.3)]
        command = decide(_state(chests=[Entity(x=20.0, y=0.0)], enemy=enemy, enemies=pins))
        self.assertNotEqual(command.heading, "E")


if __name__ == "__main__":
    unittest.main()
