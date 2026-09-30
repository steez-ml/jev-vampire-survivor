from __future__ import annotations

import unittest

from vampirejev.gate import should_send, snapshot_playable, user_wasd_override
from vampirejev.snapshot import GameState, RunState
from vampirejev.wasd import WasdDriver, heading_to_keys


def _state(*, running: bool = True, paused: bool = False, level_up: bool = False) -> GameState:
    return GameState(run=RunState(running=running, paused=paused, level_up=level_up, survived_seconds=3.0))


class GateTests(unittest.TestCase):
    def test_paused_is_not_playable(self) -> None:
        snap = _state(paused=True)
        self.assertFalse(snapshot_playable(snap))
        self.assertFalse(should_send(True, True, snap))

    def test_level_up_is_not_playable(self) -> None:
        snap = _state(level_up=True)
        self.assertFalse(should_send(True, True, snap))

    def test_not_running_blocks(self) -> None:
        self.assertFalse(should_send(True, True, _state(running=False)))

    def test_disarmed_blocks(self) -> None:
        self.assertFalse(should_send(False, True, _state()))

    def test_unfocused_blocks(self) -> None:
        self.assertFalse(should_send(True, False, _state()))

    def test_armed_focused_running_allows(self) -> None:
        self.assertTrue(should_send(True, True, _state()))

    def test_none_snapshot_blocks(self) -> None:
        self.assertFalse(should_send(True, True, None))

    def test_paused_driver_goes_all_up(self) -> None:
        sent: list[tuple[str, bool]] = []
        driver = WasdDriver(sender=lambda name, down: sent.append((name, down)))
        driver.apply(0.0, 1.0)
        self.assertEqual(driver.down, frozenset({"W"}))
        if not should_send(True, True, _state(paused=True)):
            driver.all_up()
        self.assertEqual(driver.down, frozenset())
        self.assertIn(("W", False), sent)

    def test_user_wasd_override_disarms(self) -> None:
        wanted = heading_to_keys(0.0, 0.0)
        self.assertTrue(user_wasd_override(wanted, frozenset({"W"})))
        self.assertFalse(user_wasd_override(frozenset({"W"}), frozenset({"W"})))

    def test_injected_keys_are_not_a_player_override(self) -> None:
        wanted = heading_to_keys(0.0, 0.0)
        ours = frozenset({"W"})
        self.assertFalse(user_wasd_override(wanted, frozenset({"W"}), ours))
        self.assertTrue(user_wasd_override(wanted, frozenset({"W", "A"}), ours))


if __name__ == "__main__":
    unittest.main()
