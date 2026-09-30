from __future__ import annotations

import unittest

from vampirejev.policy import decide
from vampirejev.wasd import heading_to_keys


class HeadingTests(unittest.TestCase):
    def test_zero_heading_sends_no_keys(self) -> None:
        self.assertEqual(heading_to_keys(0.0, 0.0), frozenset())

    def test_nudge_north_is_w(self) -> None:
        command = decide(None, nudge="N")
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset({"W"}))

    def test_nudge_south_is_s(self) -> None:
        command = decide(None, nudge="S")
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset({"S"}))

    def test_nudge_east_is_d(self) -> None:
        command = decide(None, nudge="E")
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset({"D"}))

    def test_nudge_west_is_a(self) -> None:
        command = decide(None, nudge="W")
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset({"A"}))

    def test_northeast_is_w_and_d(self) -> None:
        self.assertEqual(heading_to_keys(1.0, 1.0), frozenset({"W", "D"}))

    def test_stub_policy_is_idle(self) -> None:
        command = decide(None)
        self.assertTrue(command.is_idle)
        self.assertEqual(heading_to_keys(command.dx, command.dy), frozenset())

    def test_input_struct_matches_win32_x64_size(self) -> None:
        import ctypes

        from vampirejev.wasd import INPUT

        self.assertGreaterEqual(ctypes.sizeof(INPUT), 40)


if __name__ == "__main__":
    unittest.main()
