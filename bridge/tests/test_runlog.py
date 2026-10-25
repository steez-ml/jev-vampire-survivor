from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vampirejev.menu import MenuDriver, MenuExecutor
from vampirejev.runlog import RunLog
from vampirejev.summary import summarize


class RunLogTests(unittest.TestCase):
    def test_summary_reads_levels_damage_and_cause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp), {"controller": "code", "cards": "off", "starter": "Antonio", "model": "", "save_note": "no arcanas"})
            log.begin(0, 1)
            log.event("sample", t=10, hp=100, level=2)
            log.event("sample", t=70, hp=80, level=5)
            log.event("sample", t=310, hp=70, level=11)
            log.event("gate", event="disarm", t=320)
            log.end("hp-zero", 320, 11, 0)
            log.close()
            row = summarize(log.path)
            self.assertEqual(row["starter"], "Antonio")
            self.assertEqual(row["level_m5"], 11)
            self.assertIsNone(row["level_m10"])
            self.assertAlmostEqual(row["hp_lost_per_min"], 30 / (320 / 60), places=3)
            self.assertEqual(row["cause"], "hp-zero")
            self.assertEqual(row["disarms"], 1)
            self.assertFalse(row["hands_off"])
            # The file is plain JSONL and contains no API key.
            text = log.path.read_text(encoding="utf-8")
            json.loads(text.splitlines()[0])
            self.assertNotIn("TYPESAFE", text)


class MenuTests(unittest.TestCase):
    def test_plan_taps_once_per_key_then_stops(self) -> None:
        sent: list[tuple[str, bool]] = []
        driver = MenuDriver(sender=lambda name, down: sent.append((name, down)))
        exe = MenuExecutor(gap_s=0.2)
        self.assertTrue(exe.step(0.0, "screen", ("DOWN", "RETURN"), driver))
        self.assertTrue(exe.step(0.2, "screen", ("DOWN", "RETURN"), driver))
        self.assertFalse(exe.step(0.4, "screen", ("DOWN", "RETURN"), driver))
        self.assertEqual([name for name, down in sent if down], ["DOWN", "RETURN"])


if __name__ == "__main__":
    unittest.main()
