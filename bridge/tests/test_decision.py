"""Offline checks for the navigator: words, options, the code picker, the motor, Jev's arbiter, cards."""

from __future__ import annotations

import json
import math
import random
import unittest

from vampirejev import probe
from vampirejev.arbiter import HOLD_S, accept_choice
from vampirejev.cards import decide_cards
from vampirejev.jevclient import CARD_TIMEOUT_S, FakeJevClient, JevResult, MissingApiKey, require_api_key
from vampirejev.mind import NO_PROGRESS_S, Mind
from vampirejev.motor import choose_heading
from vampirejev.navigator import movement_request
from vampirejev.options import build_options
from vampirejev.perception import FRAIL, KILLABLE, SURVIVES, PerceptionMemory, STURDY, TANKY, durability_bands, perceive
from vampirejev.picker import CodePicker
from vampirejev.snapshot import (
    CardOffer,
    CardScreen,
    EnemyStats,
    Entity,
    EvolutionPair,
    GameState,
    PassiveState,
    PlayerState,
    Polar,
    RunState,
    WeaponState,
    XpPile,
)
from vampirejev.sim import SimEnemy, SimGem, clear_xp, garlic_swarm, horde_gem, low_brazier, low_chicken, open_gem, pile, run_mind, whip_line
from vampirejev.wasd import heading_to_keys
from vampirejev.words import has_raw_measurement


def _player(**kwargs) -> PlayerState:
    base = dict(x=0.0, y=0.0, hp=100.0, hp_max=100.0, speed=4.0, radius=0.4, level=4, xp=4, xp_next=20, magnet=1.2, facing_x=1)
    base.update(kwargs)
    return PlayerState(**base)


def _running(player: PlayerState, **kwargs) -> GameState:
    polar = kwargs.pop("polar", None) or Polar(radii=(6.0, 16.0, 40.0))
    return GameState(
        schema_version=5,
        seq=1,
        t_ms=1000,
        run=RunState(running=True, survived_seconds=30),
        player=player,
        polar=polar,
        **kwargs,
    )


class PerceptionTests(unittest.TestCase):
    def test_catalog_sorts_into_three_bands(self) -> None:
        bands = durability_bands(
            [
                EnemyStats("BAT", 8, 1),
                EnemyStats("SKEL", 40, 1),
                EnemyStats("TANK", 400, 1),
            ]
        )
        self.assertEqual(bands["BAT"], FRAIL)
        self.assertEqual(bands["SKEL"], STURDY)
        self.assertEqual(bands["TANK"], TANKY)

    def test_one_type_is_not_called_frail(self) -> None:
        bands = durability_bands([EnemyStats("BAT", 8, 1)])
        self.assertEqual(bands["BAT"], STURDY)

    def test_boss_is_dangerous_and_a_frail_bat_is_not(self) -> None:
        snapshot = _running(
            _player(weapons=[WeaponState("WHIP", 1)]),
            enemies=[Entity(3, 0, 0, 0, "BAT", 8, 8, "bat1")],
            bosses=[Entity(20, 0, type="BOSS", uid="boss")],
            enemy_catalog=[EnemyStats("BAT", 8, 1), EnemyStats("TANK", 400, 1)],
        )
        seen = perceive(snapshot)
        bat = next(body for body in seen.bodies if body.type == "BAT")
        boss = next(body for body in seen.bodies if body.boss)
        self.assertEqual(bat.outlook, KILLABLE)
        self.assertFalse(bat.dangerous)
        self.assertTrue(boss.dangerous)

    def test_fast_hp_loss_marks_the_type_killable(self) -> None:
        memory = PerceptionMemory()
        player = _player()
        for second, hp in ((0.0, 8.0), (0.8, 1.0)):
            snapshot = _running(
                player,
                enemies=[Entity(1, 0, 0, 0, "TANK", hp, 8, "tank1")],
                enemy_catalog=[EnemyStats("TANK", 400, 1), EnemyStats("BAT", 8, 1)],
            )
            snapshot.run.survived_seconds = second
            perceive(snapshot, memory)
        again = _running(
            player,
            enemies=[Entity(1, 0, 0, 0, "TANK", 1, 8, "tank1")],
            enemy_catalog=[EnemyStats("TANK", 400, 1), EnemyStats("BAT", 8, 1)],
        )
        again.run.survived_seconds = 1.0
        seen = perceive(again, memory)
        tank = next(body for body in seen.bodies if body.type == "TANK")
        self.assertEqual(tank.outlook, KILLABLE)

    def test_a_type_that_keeps_its_hp_near_us_is_learned_as_surviving(self) -> None:
        memory = PerceptionMemory()
        catalog = [EnemyStats("BAT", 8, 1), EnemyStats("SKEL", 40, 1), EnemyStats("TANK", 400, 1)]
        seen = None
        for tick in range(41):  # two seconds at 20 Hz, HP never moves
            snapshot = _running(_player(), enemies=[Entity(1, 0, 0, 0, "SKEL", 40, 40, "s1")], enemy_catalog=catalog)
            snapshot.run.survived_seconds = tick * 0.05
            seen = perceive(snapshot, memory)
        assert seen is not None
        self.assertEqual(seen.bodies[0].outlook, SURVIVES)

    def test_enemies_without_an_id_are_not_tracked_and_old_ids_are_forgotten(self) -> None:
        memory = PerceptionMemory()
        for tick in range(10):
            snapshot = _running(_player(), enemies=[Entity(1 + tick * 0.1, 0, 0, 0, "BAT", 8, 8, "")])
            snapshot.run.survived_seconds = tick * 0.05
            perceive(snapshot, memory)
        self.assertEqual(memory._hp, {})
        first = _running(_player(), enemies=[Entity(1, 0, 0, 0, "BAT", 8, 8, "b1")])
        first.run.survived_seconds = 30.0
        perceive(first, memory)
        self.assertIn("b1", memory._hp)
        later = _running(_player(), enemies=[])
        later.run.survived_seconds = 33.0
        perceive(later, memory)
        self.assertIn("b1", memory._hp)
        later.run.survived_seconds = 36.0
        perceive(later, memory)
        self.assertNotIn("b1", memory._hp)

    def test_a_pooled_id_back_at_full_hp_starts_a_new_history(self) -> None:
        memory = PerceptionMemory()
        for second, hp in ((0.0, 8.0), (0.5, 2.0), (0.6, 8.0)):
            snapshot = _running(_player(), enemies=[Entity(1, 0, 0, 0, "BAT", hp, 8, "b1")])
            snapshot.run.survived_seconds = second
            perceive(snapshot, memory)
        self.assertEqual(len(memory._hp["b1"]), 1)


class OptionTests(unittest.TestCase):
    def test_facts_have_no_coordinates(self) -> None:
        snapshot = _running(
            _player(weapons=[WeaponState("WHIP", 2)]),
            xp_piles=[],
            enemies=[Entity(3, 0, 0, 0, "BAT", 8, 8, "b")],
            enemy_catalog=[EnemyStats("BAT", 8, 1), EnemyStats("TANK", 400, 1)],
        )
        from vampirejev.snapshot import XpPile

        snapshot.xp_piles = [XpPile(8, 0, 30)]
        options = build_options(snapshot, perceive(snapshot))
        blob = json.dumps([item.facts for item in options])
        self.assertFalse(has_raw_measurement(blob))
        self.assertTrue(any(item.kind == "gems" for item in options))
        self.assertTrue(any("east" in item.facts for item in options))

    def test_same_pile_keeps_its_id(self) -> None:
        from vampirejev.snapshot import XpPile

        def snap(px: float) -> GameState:
            return _running(_player(x=px), xp_piles=[XpPile(8, 0, 30)])

        first = build_options(snap(0), perceive(snap(0)))
        second = build_options(snap(1), perceive(snap(1)))
        gem_a = next(item.id for item in first if item.kind == "gems")
        gem_b = next(item.id for item in second if item.kind == "gems")
        self.assertEqual(gem_a, gem_b)

    def test_polar_bins_still_make_a_gem_option(self) -> None:
        xp = [0.0] * 24
        xp[2] = 30  # inner ring, east
        snapshot = _running(_player(), polar=Polar(radii=(6, 16, 40), xp=xp))
        options = build_options(snapshot, perceive(snapshot))
        self.assertTrue(any(item.kind == "gems" and "east" in item.facts for item in options))

    def test_a_crowd_past_the_listed_bodies_makes_the_way_heavy(self) -> None:
        enemy = [0.0] * 24
        enemy[8 + 2] = 12  # middle ring, east: nothing the snapshot lists by position
        snapshot = _running(_player(), polar=Polar(radii=(6, 16, 40), enemy=enemy), xp_piles=[XpPile(24, 0, 40)])
        gem = next(item for item in build_options(snapshot, perceive(snapshot)) if item.kind == "gems")
        self.assertEqual(gem.danger, "heavy")
        self.assertIn("a large group of enemies on the way", gem.facts)
        self.assertFalse(has_raw_measurement(gem.facts))

    def test_enemies_of_unknown_toughness_are_not_called_slow(self) -> None:
        snapshot = _running(_player(), enemies=[Entity(3, 0, 0, 0, "", None, None, "")], xp_piles=[XpPile(8, 0, 30)])
        gem = next(item for item in build_options(snapshot, perceive(snapshot)) if item.kind == "gems")
        self.assertEqual(gem.danger, "light")
        self.assertIn("one enemy on the way", gem.facts)
        self.assertNotIn("a while to kill", gem.facts)


class PickerTests(unittest.TestCase):
    def test_small_lead_does_not_switch(self) -> None:
        from vampirejev.options import Option

        def opt(ident: str, value: str) -> Option:
            return Option(ident, "gems", "approach", 0, 0, 0, 0, ident, value, "clear", "close")

        picker = CodePicker()
        first = picker.choose([opt("a", "medium"), opt("b", "medium")])
        assert first is not None
        # "high" beats "medium" by 1.0, which is past the margin, so use a tie instead.
        again = picker.choose([opt("a", "medium"), opt("b", "low")])
        self.assertEqual(again.id if again else "", first.id)

    def test_a_clear_win_does_switch(self) -> None:
        from vampirejev.options import Option

        def opt(ident: str, value: str, danger: str) -> Option:
            return Option(ident, "gems", "approach", 0, 0, 0, 0, ident, value, danger, "close")

        picker = CodePicker()
        picker.choose([opt("a", "low", "clear")])
        switched = picker.choose([opt("a", "low", "clear"), opt("b", "high", "clear")])
        self.assertEqual(switched.id if switched else "", "b")


class MotorTests(unittest.TestCase):
    def test_reflex_sidesteps_a_dangerous_enemy(self) -> None:
        from vampirejev.perception import Body

        threat = Body("TANK", 1.0, 0, 0, 0, "t", 100, 100, False, TANKY, "survives")
        index, reflex = choose_heading(0, 0, 4, _east_option(), [threat], frozenset(), [], None, False)
        self.assertTrue(reflex)
        self.assertNotEqual(index, 2)  # not due east

    def test_killable_contact_is_allowed(self) -> None:
        from vampirejev.perception import Body

        bat = Body("BAT", 1.0, 0, 0, 0, "b", 8, 8, False, FRAIL, KILLABLE)
        index, reflex = choose_heading(0, 0, 4, _east_option(), [bat], frozenset(), [], None, False)
        self.assertFalse(reflex)
        self.assertEqual(index, 2)

    def test_a_live_wall_is_a_veto(self) -> None:
        from vampirejev.options import Option

        north = Option("open_0", "open", "escape", 0, 6, 0, 6, "Open space north", "low", "clear", "close")
        index, _reflex = choose_heading(0, 0, 4, north, [], frozenset({"N"}), [], None, False)
        self.assertNotEqual(index, 0)


class ArbiterTests(unittest.TestCase):
    def test_fresh_confident_pick_is_kept(self) -> None:
        result = _result("gems_0_0", 0.8, built=10.0)
        self.assertEqual(accept_choice(result, {"gems_0_0"}, 10.4), "gems_0_0")

    def test_stale_or_unsure_or_missing_is_dropped(self) -> None:
        self.assertIsNone(accept_choice(_result("gems_0_0", 0.8, built=10.0), {"gems_0_0"}, 11.2))
        self.assertIsNone(accept_choice(_result("gems_0_0", 0.2, built=10.0), {"gems_0_0"}, 10.2))
        self.assertIsNone(accept_choice(_result("gone", 0.9, built=10.0), {"gems_0_0"}, 10.2))


class CardTests(unittest.TestCase):
    def test_evolution_wins_before_jev(self) -> None:
        screen = CardScreen(
            "level_up",
            [
                CardOffer(0, "Empty Tome", "passive", "EMPTY_TOME", 1, True, "Cooldown."),
                CardOffer(1, "Hollow Heart", "passive", "HOLLOW", 1, True, "The other half."),
            ],
        )
        decision = decide_cards(
            screen,
            [WeaponState("WHIP", 4)],
            [],
            [EvolutionPair("WHIP", "HOLLOW", "VAMPIRICA")],
            use_jev=True,
            jev_choice="card_0_empty_tome",
            jev_confidence=0.99,
        )
        assert decision is not None
        self.assertEqual(decision.name, "Hollow Heart")
        self.assertIn("evolution", decision.reason)

    def test_rules_fill_an_empty_weapon_slot(self) -> None:
        screen = CardScreen(
            "level_up",
            [
                CardOffer(0, "Armor", "passive", "ARMOR", 1, True, "Defense."),
                CardOffer(1, "Knife", "weapon", "KNIFE", 1, True, "Fires the way you walk."),
            ],
        )
        decision = decide_cards(screen, [WeaponState("WHIP", 1)], [], [], use_jev=False)
        assert decision is not None
        self.assertEqual(decision.type if hasattr(decision, "type") else decision.name, "Knife")
        self.assertEqual(decision.keys, ("DOWN", "RETURN"))

    def test_low_confidence_uses_the_rule(self) -> None:
        screen = CardScreen("level_up", [CardOffer(0, "Armor", "passive", "ARMOR", 1, True, "")])
        decision = decide_cards(
            screen,
            [],
            [PassiveState("HOLLOW", 1)],
            [],
            use_jev=True,
            jev_choice="card_0_armor",
            jev_confidence=0.2,
        )
        assert decision is not None
        self.assertNotEqual(decision.reason, "jev")


class JevRequestTests(unittest.TestCase):
    def test_shuffle_and_no_decimals(self) -> None:
        world = open_gem()
        snapshot = world.snapshot()
        options = build_options(snapshot, perceive(snapshot))
        orders = []
        for seed in range(12):
            request = movement_request(snapshot, perceive(snapshot), options, 1.0, random.Random(seed))
            orders.append(tuple(request.option_order))
            blob = json.dumps({"state": request.state, "criteria": request.criteria})
            self.assertFalse(has_raw_measurement(blob))
            self.assertNotIn('"x"', blob)
        self.assertGreater(len(set(orders)), 1)

    def test_missing_key_is_refused(self) -> None:
        with self.assertRaises(MissingApiKey):
            require_api_key({})

    def test_fake_client_never_touches_the_network(self) -> None:
        import asyncio

        world = open_gem()
        snapshot = world.snapshot()
        seen = perceive(snapshot)
        options = build_options(snapshot, seen)
        gem = next(item.id for item in options if item.kind == "gems")
        client = FakeJevClient(choice=gem, confidence=0.91, play_safe=0.7)
        request = movement_request(snapshot, seen, options, 2.0, random.Random(1))
        result = asyncio.run(client.ask(request))
        self.assertTrue(result.ok)
        self.assertEqual(result.choice, gem)
        self.assertEqual(result.model, "fake")
        self.assertAlmostEqual(result.play_safe or 0, 0.7)

    def test_a_rejected_answer_does_not_drop_the_commitment(self) -> None:
        world = open_gem()
        snapshot = world.snapshot()
        options = build_options(snapshot, perceive(snapshot))
        gem = next(item.id for item in options if item.kind == "gems")
        client = FakeJevClient(choice=gem, confidence=0.95)
        mind = Mind(controller="jev", cards="off", client=client, sync=True)
        try:
            first = mind.step(snapshot, [], 1.0)
            self.assertEqual(first.decider, "jev")
            self.assertEqual(first.option_id, gem)
            client.confidence = 0.1
            client.choice = "not-an-option"
            second = mind.step(snapshot, [], 1.2)
            self.assertEqual(second.option_id, gem)
            self.assertEqual(second.decider, "jev")
        finally:
            mind.close()


class _SilentBackground:
    """A background caller whose answer never arrives. No thread, no network."""

    disabled = False

    def submit(self, request) -> None:
        del request

    def latest(self, kind: str):
        del kind
        return None

    def close(self) -> None:
        pass


class MindTests(unittest.TestCase):
    def test_a_jev_pick_expires_when_answers_stop(self) -> None:
        world = open_gem()
        world.gems[0] = SimGem(20.0, 0.0, 40)  # far enough that walking toward it never arrives
        snapshot = world.snapshot()
        gem = next(item.id for item in build_options(snapshot, perceive(snapshot)) if item.kind == "gems")
        client = FakeJevClient(choice=gem, confidence=0.95)
        mind = Mind(controller="jev", client=client, sync=True)
        keys: frozenset[str] = frozenset()
        seen: list[tuple[float, str]] = []
        try:
            for i in range(int(round((HOLD_S + 0.5) / 0.05))):
                now = 1.0 + i * 0.05
                out = mind.step(world.snapshot(), keys, now)
                seen.append((now, out.decider))
                client.fail = RuntimeError("down")
                keys = heading_to_keys(out.command.dx, out.command.dy)
                world.step(keys, 0.05)
        finally:
            mind.close()
        self.assertTrue(all(who == "jev" for now, who in seen if now <= 1.0 + HOLD_S - 0.05))
        self.assertEqual(seen[-1][1], "code")

    def test_a_jev_pick_is_dropped_when_the_way_gets_worse(self) -> None:
        world = open_gem()
        snapshot = world.snapshot()
        gem = next(item.id for item in build_options(snapshot, perceive(snapshot)) if item.kind == "gems")
        client = FakeJevClient(choice=gem, confidence=0.95)
        mind = Mind(controller="jev", client=client, sync=True)
        try:
            mind.step(snapshot, [], 1.0)
            self.assertEqual(mind.commit_source, "jev")
            client.fail = RuntimeError("down")
            world.enemies.append(SimEnemy(1.4, 0.0, speed=0.0, type="TANK", hp=500, hp_max=500, uid="t"))
            mind.step(world.snapshot(), [], 1.1)
            self.assertEqual(mind.commit_source, "code")
        finally:
            mind.close()

    def test_fallback_share_is_only_reported_for_jev(self) -> None:
        snapshot = open_gem().snapshot()
        mind = Mind(controller="code", sync=True)
        try:
            self.assertIsNone(mind.step(snapshot, [], 1.0).fallback_share)
        finally:
            mind.close()

    def test_jev_cards_wait_for_the_answer_then_fall_back(self) -> None:
        screen = CardScreen(
            "level_up",
            [CardOffer(0, "Armor", "passive", "ARMOR", 1, True, ""), CardOffer(1, "Knife", "weapon", "KNIFE", 1, True, "")],
        )
        snapshot = _running(_player(weapons=[WeaponState("WHIP", 1)]), card_screen=screen)
        snapshot.run.level_up = True
        mind = Mind(controller="code", cards="jev", client=FakeJevClient())
        assert mind.background is not None
        mind.background.close()
        mind.background = _SilentBackground()  # type: ignore[assignment]
        try:
            waiting = mind.step(snapshot, [], 10.0)
            self.assertFalse(waiting.card_ready)
            self.assertTrue(waiting.card_signature)
            late = mind.step(snapshot, [], 10.0 + CARD_TIMEOUT_S + 0.05)
            self.assertTrue(late.card_ready)
            self.assertEqual(late.card_signature, waiting.card_signature)
            self.assertEqual(late.card_keys, ("DOWN", "RETURN"))
        finally:
            mind.close()


class ProbeTests(unittest.TestCase):
    def test_late_answers_count_and_position_bias_shows(self) -> None:
        rows = [
            {"ok": True, "choice": "a", "order": ["a", "b", "c"], "latency_s": 0.1, "input_tokens": 300, "error": ""},
            {"ok": True, "choice": "b", "order": ["b", "a", "c"], "latency_s": 0.2, "input_tokens": 300, "error": ""},
            {"ok": True, "choice": "a", "order": ["c", "a", "b"], "latency_s": 1.4, "input_tokens": 300, "error": ""},
            {"ok": False, "choice": "", "order": ["a", "b", "c"], "latency_s": 5.0, "input_tokens": None, "error": "timeout"},
        ]
        stats = probe.summarize_rows(rows)
        self.assertEqual(stats["ok"], 3)
        self.assertAlmostEqual(stats["late"], 0.5)
        self.assertAlmostEqual(stats["agree"], 2 / 3)
        self.assertAlmostEqual(stats["first_slot"], 2 / 3)
        self.assertEqual(stats["top"], "a")

    def test_probe_runs_offline_with_the_fake_client(self) -> None:
        import asyncio

        lines: list[str] = []
        asyncio.run(probe.run_probe(models=("fake",), make_client=lambda model: FakeJevClient(), out=lines.append))
        self.assertTrue(lines[0].startswith("model,"))
        self.assertTrue(any(",crowded,8," in line for line in lines))
        self.assertFalse(any("FAILED" in line for line in lines))


class ScenarioTests(unittest.TestCase):
    def test_open_gem_is_taken(self) -> None:
        world = open_gem()
        run_mind(world, 2.5)
        self.assertGreater(world.collected, 0)

    def test_clear_xp_is_taken_while_hp_is_low(self) -> None:
        world = clear_xp()
        run_mind(world, 3.0)
        self.assertGreater(world.collected, 0)
        self.assertGreater(world.x, 2.0)

    def test_whip_walks_through_bats_but_not_a_tank(self) -> None:
        bats = whip_line(False)
        run_mind(bats, 3.5)
        self.assertGreater(bats.collected, 0)

        tank = whip_line(True)
        _mind, rows = run_mind(tank, 2.5)
        self.assertEqual(tank.collected, 0)
        self.assertFalse(rows[0][6].startswith("gems"))
        nearest = min(math.hypot(x - 3.0, y) for _t, x, y, *_rest in rows)
        nearest = min(nearest, math.hypot(tank.x - 3.0, tank.y))
        self.assertGreater(nearest, 1.0)

    def test_garlic_holds_bats_and_leaves_a_boss(self) -> None:
        bats = garlic_swarm(False)
        run_mind(bats, 2.5)
        self.assertGreater(bats.x, 0.6)
        self.assertLess(bats.x, 2.8)

        boss = garlic_swarm(True)
        start = 3.2
        run_mind(boss, 2.0)
        dist = ((boss.x - 3.2) ** 2 + boss.y**2) ** 0.5
        self.assertGreater(dist, start)

    def test_low_hp_takes_a_chicken_and_a_brazier(self) -> None:
        chicken = low_chicken()
        run_mind(chicken, 3.0)
        self.assertGreater(chicken.healed, 0)

        brazier = low_brazier()
        run_mind(brazier, 3.5)
        self.assertGreater(brazier.healed, 0)

    def test_untyped_crowd_in_the_middle_ring_is_not_walked_into(self) -> None:
        world = horde_gem()
        _mind, rows = run_mind(world, 6.0)
        self.assertFalse(rows[0][6].startswith("gems"))
        self.assertEqual(world.damage, 0.0)

    def test_untyped_guards_on_a_pile_do_not_freeze_the_bot(self) -> None:
        world = pile()
        _mind, rows = run_mind(world, 6.0)
        self.assertLess(_longest_still(rows), NO_PROGRESS_S + 0.5)
        self.assertTrue(any(not row[6].startswith("gems") for row in rows))


def _longest_still(rows, radius: float = 0.25) -> float:
    best = 0.0
    start = 0
    for i, row in enumerate(rows):
        while math.hypot(row[1] - rows[start][1], row[2] - rows[start][2]) > radius:
            start += 1
        best = max(best, row[0] - rows[start][0])
    return best


def _east_option():
    from vampirejev.options import Option

    return Option("gems_2_0", "gems", "approach", 10, 0, 10, 0, "Gem pile east", "high", "clear", "medium")


def _result(choice: str, confidence: float, built: float) -> JevResult:
    return JevResult(ok=True, kind="movement", choice=choice, confidence=confidence, built_mono=built, probabilities={choice: confidence})


if __name__ == "__main__":
    unittest.main()
