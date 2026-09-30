from __future__ import annotations

import unittest

from vampirejev.polar import SECTORS, empty_bins
from vampirejev.snapshot import WeaponState
from vampirejev.weapons import AIM_AUTO, AIM_FACING, AIM_MOVE, aim_bonus, aim_class


class WeaponAimTests(unittest.TestCase):
    def test_aim_classes_from_enum_names(self) -> None:
        self.assertEqual(aim_class("WHIP"), AIM_FACING)
        self.assertEqual(aim_class("KNIFE"), AIM_MOVE)
        self.assertEqual(aim_class("MAGIC_MISSILE"), AIM_AUTO)
        self.assertEqual(aim_class("SOMETHING_NEW"), AIM_AUTO)

    def test_whip_prefers_headings_that_face_the_enemies(self) -> None:
        enemy = empty_bins()
        enemy[2] = 4.0  # ring 0, east
        bonus = aim_bonus([WeaponState("WHIP", 1)], enemy, facing_x=-1)
        self.assertGreater(bonus[2], bonus[6])  # E beats W
        self.assertGreater(bonus[1], 0.0)  # NE also turns us east
        self.assertEqual(bonus[0], 0.0)  # pure N keeps facing west: nothing there

    def test_knife_prefers_the_enemy_sector(self) -> None:
        enemy = empty_bins()
        enemy[SECTORS + 4] = 5.0  # ring 1, south
        bonus = aim_bonus([WeaponState("KNIFE", 1)], enemy, facing_x=1)
        self.assertGreater(bonus[4], bonus[0])
        self.assertGreater(bonus[4], bonus[3])

    def test_auto_weapons_add_nothing(self) -> None:
        enemy = empty_bins()
        enemy[2] = 4.0
        bonus = aim_bonus([WeaponState("MAGIC_MISSILE", 3), WeaponState("GARLIC", 2)], enemy, facing_x=1)
        self.assertEqual(bonus, [0.0] * SECTORS)


if __name__ == "__main__":
    unittest.main()
