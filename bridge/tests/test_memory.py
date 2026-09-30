from __future__ import annotations

import unittest

from vampirejev.memory import MotionTracker, WallMemory

R0 = 3.0


def _feed(tracker: MotionTracker, keys: set[str], steps: int, dx: float, dy: float, start_t: float = 0.0, dt: float = 0.05):
    x = y = 0.0
    t = start_t
    blocked = frozenset()
    for _ in range(steps):
        blocked = tracker.observe(t, x, y, frozenset(keys), R0)
        x += dx
        y += dy
        t += dt
    return blocked


class MotionTrackerTests(unittest.TestCase):
    def test_holding_w_without_moving_flags_north(self) -> None:
        tracker = MotionTracker()
        blocked = _feed(tracker, {"W"}, steps=8, dx=0.0, dy=0.0)
        self.assertEqual(blocked, frozenset({"N"}))
        self.assertGreaterEqual(tracker.events, 1)

    def test_free_movement_is_not_flagged(self) -> None:
        tracker = MotionTracker()
        blocked = _feed(tracker, {"W"}, steps=8, dx=0.0, dy=0.2)
        self.assertEqual(blocked, frozenset())

    def test_sliding_along_a_north_wall_flags_only_north(self) -> None:
        tracker = MotionTracker()
        blocked = _feed(tracker, {"W", "D"}, steps=8, dx=0.15, dy=0.0)
        self.assertEqual(blocked, frozenset({"N"}))

    def test_flag_expires_after_release(self) -> None:
        tracker = MotionTracker()
        _feed(tracker, {"W"}, steps=8, dx=0.0, dy=0.0)
        self.assertEqual(tracker.blocked(0.4), frozenset({"N"}))
        self.assertEqual(tracker.blocked(2.0), frozenset())

    def test_short_hold_is_not_enough(self) -> None:
        tracker = MotionTracker()
        blocked = _feed(tracker, {"W"}, steps=3, dx=0.0, dy=0.0)
        self.assertEqual(blocked, frozenset())

    def test_learned_free_speed_raises_the_bar(self) -> None:
        tracker = MotionTracker()
        # Move fast and free for a while: free speed is learned at ~4 units/s.
        _feed(tracker, {"D"}, steps=20, dx=0.2, dy=0.0)
        self.assertGreater(tracker.free_speed, 3.0)
        # Now crawl at 10% of that with W held: below stuck_ratio -> flagged.
        blocked = _feed(tracker, {"W"}, steps=8, dx=0.0, dy=0.02, start_t=1.0)
        self.assertIn("N", blocked)


class WallMemoryTests(unittest.TestCase):
    def test_mark_read_and_expire(self) -> None:
        memory = WallMemory(cell=2.0, ttl_s=10.0)
        memory.mark(1.0, 1.0, {"N"}, t=0.0)
        self.assertEqual(memory.blocked_at(1.5, 0.5, t=1.0), frozenset({"N"}))
        self.assertEqual(memory.blocked_at(5.0, 5.0, t=1.0), frozenset())
        self.assertEqual(memory.blocked_at(1.5, 0.5, t=11.0), frozenset())
        memory.prune(11.0)
        self.assertEqual(len(memory), 0)

    def test_recent_freshness_decays(self) -> None:
        memory = WallMemory(recent_ttl_s=8.0)
        memory.mark(0.0, 0.0, {"N"}, t=0.0)
        memory.mark(0.0, 0.0, {"S"}, t=2.0)
        recent = memory.recent(4.0)
        self.assertAlmostEqual(recent["N"], 0.5)
        self.assertAlmostEqual(recent["S"], 0.75)
        self.assertEqual(memory.recent(20.0), {})

    def test_cell_size_change_clears(self) -> None:
        memory = WallMemory(cell=2.0)
        memory.mark(0.0, 0.0, {"E"}, t=0.0)
        memory.set_cell_size(3.0)
        self.assertEqual(len(memory), 0)


if __name__ == "__main__":
    unittest.main()
