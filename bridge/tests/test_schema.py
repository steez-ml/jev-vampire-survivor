from __future__ import annotations

import json
import unittest
from pathlib import Path

from vampirejev.snapshot import GameState

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "game-state.v3.schema.json"
EXAMPLE_PATH = ROOT / "contracts" / "game-state.v3.example.json"
SCHEMA_V4_PATH = ROOT / "contracts" / "game-state.v4.schema.json"
EXAMPLE_V4_PATH = ROOT / "contracts" / "game-state.v4.example.json"
SCHEMA_V5_PATH = ROOT / "contracts" / "game-state.v5.schema.json"
EXAMPLE_V5_PATH = ROOT / "contracts" / "game-state.v5.example.json"


def _validate(instance: object, schema: dict, defs: dict | None = None) -> None:
    defs = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        ref = schema["$ref"]
        key = ref.split("/")[-1]
        _validate(instance, defs[key], defs)
        return
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(instance, dict):
            raise AssertionError(f"expected object, got {type(instance)}")
        for key in schema.get("required", []):
            if key not in instance:
                raise AssertionError(f"missing required key {key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(props)
            if extra:
                raise AssertionError(f"unexpected keys {sorted(extra)}")
        for key, value in instance.items():
            if key in props:
                _validate(value, props[key], defs)
        if "const" in schema and instance != schema["const"]:
            raise AssertionError(f"expected const {schema['const']}")
        return
    if expected == "array":
        if not isinstance(instance, list):
            raise AssertionError("expected array")
        max_items = schema.get("maxItems")
        if max_items is not None and len(instance) > max_items:
            raise AssertionError("array too long")
        min_items = schema.get("minItems")
        if min_items is not None and len(instance) < min_items:
            raise AssertionError("array too short")
        item_schema = schema.get("items")
        if item_schema:
            for item in instance:
                _validate(item, item_schema, defs)
        return
    if "const" in schema and instance != schema["const"]:
        raise AssertionError(f"expected const {schema['const']}")
    if "enum" in schema and instance not in schema["enum"]:
        raise AssertionError(f"{instance!r} not in enum {schema['enum']}")
    if expected == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise AssertionError("expected integer")
        if "minimum" in schema and instance < schema["minimum"]:
            raise AssertionError("integer below minimum")
        return
    if expected == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            raise AssertionError("expected number")
        if "minimum" in schema and instance < schema["minimum"]:
            raise AssertionError("number below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise AssertionError("number above maximum")
        return
    if expected == "string" and not isinstance(instance, str):
        raise AssertionError("expected string")
    if expected == "boolean" and not isinstance(instance, bool):
        raise AssertionError("expected boolean")


class SchemaTests(unittest.TestCase):
    def test_example_matches_v3(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        _validate(example, schema)
        self.assertEqual(example["source"], "bepinex")
        self.assertEqual(example["schema_version"], 3)
        self.assertNotIn("gems", example)

    def test_example_parses_to_dataclass(self) -> None:
        snapshot = GameState.from_json(EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(snapshot.seq, 42)
        self.assertEqual(snapshot.source, "bepinex")
        self.assertTrue(snapshot.run.running)
        self.assertIsNotNone(snapshot.player)
        self.assertEqual(len(snapshot.polar.xp), 24)
        self.assertEqual(len(snapshot.enemies), 1)
        self.assertEqual(len(snapshot.bosses), 1)
        self.assertEqual(snapshot.counts.enemies_published, 1)
        # v3 producer: every v4 field reads as unknown.
        self.assertIsNone(snapshot.player.level)
        self.assertFalse(snapshot.player.has_blocked)
        self.assertEqual(snapshot.player.weapons, [])
        self.assertIsNone(snapshot.polar.wall)

    def test_v4_example_matches_schema_and_parses(self) -> None:
        schema = json.loads(SCHEMA_V4_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_V4_PATH.read_text(encoding="utf-8"))
        _validate(example, schema)
        self.assertEqual(example["schema_version"], 4)
        snapshot = GameState.from_json(EXAMPLE_V4_PATH.read_text(encoding="utf-8"))
        player = snapshot.player
        self.assertEqual(player.level, 3)
        self.assertAlmostEqual(player.xp_frac, 0.7)
        self.assertAlmostEqual(player.magnet, 2.6)
        self.assertEqual(player.facing_x, 1)
        self.assertEqual(player.move_dir, (1.0, 0.0))
        self.assertTrue(player.has_blocked)
        self.assertEqual(player.blocked, frozenset({"up"}))
        self.assertEqual([w.type for w in player.weapons], ["WHIP", "MAGIC_MISSILE"])
        self.assertEqual(player.weapons[0].level, 2)
        self.assertEqual(len(snapshot.polar.wall), 24)
        self.assertEqual(snapshot.polar.wall[0], 1.0)
        self.assertEqual(snapshot.counts.tilemaps, 2)
        self.assertEqual(snapshot.pickups[0].type, "ROAST")
        self.assertEqual(snapshot.destructibles[0].type, "BRAZIER")
        self.assertEqual(snapshot.counts.pickups_published, 1)
        self.assertEqual(snapshot.counts.destructibles_published, 1)

    def test_v5_example_matches_schema_and_parses(self) -> None:
        schema = json.loads(SCHEMA_V5_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_V5_PATH.read_text(encoding="utf-8"))
        _validate(example, schema)
        snapshot = GameState.from_json(EXAMPLE_V5_PATH.read_text(encoding="utf-8"))
        self.assertEqual(snapshot.schema_version, 5)
        self.assertEqual(snapshot.enemies[0].type, "BAT")
        self.assertEqual(snapshot.enemies[0].uid, "e1")
        self.assertAlmostEqual(snapshot.enemies[0].hp or 0, 6)
        self.assertEqual(snapshot.xp_piles[0].value, 40)
        self.assertEqual(snapshot.enemy_catalog[1].type, "TANK")
        self.assertEqual(snapshot.enemy_sectors[0].count, 12)
        assert snapshot.card_screen is not None
        self.assertEqual(snapshot.card_screen.kind, "level_up")
        self.assertEqual(snapshot.card_screen.offers[1].type, "PASSIVE_EXAMPLE")
        self.assertEqual(snapshot.evolutions[0].result, "VAMPIRICA")
        self.assertEqual(snapshot.player.passives[0].type, "PASSIVE_EXAMPLE")
        self.assertAlmostEqual(snapshot.player.weapons[0].area or 0, 1.5)

    def test_v4_shape_is_valid_v5_without_new_fields(self) -> None:
        schema = json.loads(SCHEMA_V5_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_V4_PATH.read_text(encoding="utf-8"))
        example["schema_version"] = 5
        _validate(example, schema)
        snapshot = GameState.from_dict(example)
        self.assertEqual(snapshot.xp_piles, [])
        self.assertIsNone(snapshot.card_screen)


if __name__ == "__main__":
    unittest.main()
