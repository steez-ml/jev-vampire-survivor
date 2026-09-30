from __future__ import annotations

import unittest

from vampirejev.polar import cell_index, hottest_xp_sector, sector_index


class PolarIndexTests(unittest.TestCase):
    def test_plus_y_is_sector_zero(self) -> None:
        self.assertEqual(sector_index(0.0, 10.0), 0)
        self.assertEqual(cell_index(0.0, 3.0), 0)

    def test_plus_x_is_east(self) -> None:
        self.assertEqual(sector_index(10.0, 0.0), 2)
        self.assertEqual(cell_index(3.0, 0.0), 2)

    def test_mid_ring_east(self) -> None:
        self.assertEqual(cell_index(10.0, 0.0), 8 + 2)

    def test_outer_ring_north(self) -> None:
        self.assertEqual(cell_index(0.0, 30.0), 16 + 0)

    def test_beyond_outer_still_ring_two(self) -> None:
        self.assertEqual(cell_index(0.0, 80.0), 16)

    def test_hottest_xp_sector_name(self) -> None:
        xp = [0.0] * 24
        xp[2] = 4.0
        xp[10] = 12.0
        self.assertEqual(hottest_xp_sector(xp), "E")


if __name__ == "__main__":
    unittest.main()
