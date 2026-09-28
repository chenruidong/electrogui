import unittest

import pandas as pd

from electro_gui.conditions import group_value, select, validate, validate_group
from electro_gui.data import _alignment_metadata, _registry


class ElectroGuiConditionContract(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"event": "object_spawn", "world": "PP", "intention": "NA", "role": "prey", "action": "touch", "outcome": "prey_capture", "bar": False, "t": 1.0, "trial": 1, "reward_tokens": 1},
            {"event": "reward", "world": "PM", "intention": None, "role": None, "action": None, "outcome": None, "bar": None, "t": 2.0, "trial": 2, "reward_tokens": None},
        ]
        self.fields = {f["key"]: f for f in _registry(pd.DataFrame(), self.rows)}

    def test_canonical_values_and_support_counts_keep_zero_support_distinct(self):
        world = self.fields["world"]
        self.assertEqual(world["values"], ["PP", "PM", "MM"])
        self.assertEqual(world["value_counts"], {"PP": 1, "PM": 1, "MM": 0})
        self.assertEqual(world["missing_count"], 0)
        intention = self.fields["intention"]
        self.assertEqual(intention["values"], ["PP", "PM", "MM", "NA"])
        self.assertEqual(intention["value_counts"]["NA"], 1)
        self.assertEqual(intention["missing_count"], 1)

    def test_metadata_has_definitions_categories_units_ranges_and_grouping_policy(self):
        for key in ("world", "t", "reward_tokens"):
            field = self.fields[key]
            for required in ("description", "timing_description", "category", "value_counts", "missing_count", "cardinality", "grouping_eligible"):
                self.assertIn(required, field)
        self.assertEqual(self.fields["t"]["units"], "s")
        self.assertEqual(self.fields["t"]["range"], [1.0, 2.0])
        self.assertFalse(self.fields["t"]["grouping_eligible"])
        unavailable = _registry(pd.DataFrame(), self.rows)[-1]
        self.assertIn("availability", unavailable)

    def test_validation_rejects_typos_and_incompatible_operators_but_accepts_literal_na(self):
        self.assertTrue(validate_group({"mode": "all", "rules": [{"field": "world", "op": "eq", "value": "MM"}]}, "x", self.fields) == [])
        self.assertTrue(validate_group({"mode": "all", "rules": [{"field": "world", "op": "eq", "value": "PMPP"}]}, "x", self.fields))
        self.assertTrue(validate_group({"mode": "all", "rules": [{"field": "world", "op": "gt", "value": 1}]}, "x", self.fields))
        self.assertTrue(validate_group({"mode": "all", "rules": [{"field": "intention", "op": "eq", "value": "NA"}]}, "x", self.fields) == [])
        self.assertTrue(validate_group({"mode": "all", "rules": [{"field": "t", "op": "between", "value": [0.0, 2.0]}]}, "x", self.fields) == [])

    def test_alignment_metadata_is_grouped_and_legacy_alignment_keys_remain(self):
        entries = _alignment_metadata(["object_spawn", "joystick_move_onset", "reward", "sync_pulse"])
        self.assertEqual([e["key"] for e in entries], ["object_spawn", "joystick_move_onset", "reward", "sync_pulse"])
        self.assertEqual([e["category"] for e in entries], ["object", "movement", "reward", "technical"])
        self.assertEqual(set(entries[0]), {"key", "label", "category", "description"})

    def test_numeric_grouping_requires_valid_explicit_bins(self):
        base = {"shared": {"mode": "all", "rules": []}, "cohorts": [{"id": "A", "name": "A", "mode": "all", "rules": [{"field": "world", "op": "eq", "value": "PP"}]}], "facet": "t"}
        self.assertTrue(any("requires explicit group_bins" in error for error in validate(base, type("Loaded", (), {"fields": list(self.fields.values())})())))
        invalid = dict(base, group_bins={"t": [0, 1, 1]})
        self.assertTrue(any("strictly ascending" in error for error in validate(invalid, type("Loaded", (), {"fields": list(self.fields.values())})())))
        valid = dict(base, group_bins={"t": [1, 2]})
        self.assertEqual(validate(valid, type("Loaded", (), {"fields": list(self.fields.values())})()), [])

    def test_numeric_group_boundaries_and_raw_values_are_preserved(self):
        recipe = {"group_bins": {"t": [0, 1, 2]}}
        self.assertEqual(group_value({"t": 0}, "t", recipe), "[0, 1)")
        self.assertEqual(group_value({"t": 1}, "t", recipe), "[1, 2]")
        self.assertIsNone(group_value({"t": 2.1}, "t", recipe))
        loaded = type("Loaded", (), {"fields": list(self.fields.values())})()
        full = dict(recipe, cohorts=[{"id": "A", "name": "A", "mode": "all", "rules": [{"field": "world", "op": "eq", "value": "PP"}]}], facet="t", shared={"mode": "all", "rules": []})
        result = select(self.rows, full, loaded)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["rows"][0]["facet_value"], "[1, 2]")
        self.assertEqual(result["rows"][0]["facet_raw_value"], 1.0)
        self.assertEqual(result["rows"][0]["t"], 1.0)


if __name__ == "__main__":
    unittest.main()
