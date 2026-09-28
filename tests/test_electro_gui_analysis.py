import unittest

import numpy as np

from electro_gui.analysis import compute_unit, prepare_rows
from electro_gui.conditions import default_recipe, select, validate


class Loaded:
    session_id = "synthetic"
    duration_s = 10.0
    units = [{"id": 1, "area": "ACC", "quality": "good", "n_spikes": 8}]
    trials = [
        {"id": 1, "start": 0.0, "stop": 2.0, "complete": True, "world": "PP", "intention": "PP", "block_id": 10},
        {"id": 2, "start": 2.0, "stop": 4.0, "complete": True, "world": "PM", "intention": "NA", "block_id": 10},
        {"id": 3, "start": 4.0, "stop": 6.0, "complete": True, "world": "MM", "intention": "MM", "block_id": 11},
    ]
    rows = [
        {"row_id": 1, "t": 1.0, "trial": 1, "event": "prey_capture", "role": "prey", "outcome": "prey_capture", "next_outcome_t": 1.8, "trial_end_t": 2.0},
        {"row_id": 2, "t": 1.5, "trial": 1, "event": "prey_capture", "role": "prey", "outcome": "prey_capture", "next_outcome_t": None, "trial_end_t": 2.0},
        {"row_id": 3, "t": 3.0, "trial": 2, "event": "predator_avoid", "role": "predator", "outcome": "predator_avoid", "next_outcome_t": 3.9, "trial_end_t": 4.0},
        {"row_id": 4, "t": 5.0, "trial": 3, "event": "predator_contact", "role": "predator", "outcome": "predator_contact", "next_outcome_t": None, "trial_end_t": 6.0},
    ]
    fields = [
        {"key": "world", "type": "category", "values": ["PP", "PM", "MM", "NA"]},
        {"key": "intention", "type": "category", "values": ["PP", "PM", "MM", "NA"]},
        {"key": "role", "type": "category", "values": ["prey", "predator"]},
        {"key": "correct", "type": "boolean"},
    ]

    def eligibility(self, unit_ids, policy):
        return {1, 2, 3}, {"policy": policy, "source": "synthetic"}

    def spikes(self, unit_id):
        return np.array([1.0, 1.1, 1.5, 3.0, 3.25, 5.0, 5.5, 5.75])


class ElectroAnalysisTests(unittest.TestCase):
    def test_half_open_count_and_equal_trial_weight(self):
        request = {"unit_id": 1, "alignment": "object_outcome", "pre": -.5, "post": .5, "bin": .1, "sigma": 0, "count_window": [0, .5], "stability": "all_complete", "recipe": {"enabled": False}, "test": "none"}
        result = compute_unit(Loaded(), request)
        self.assertEqual([r["count"] for r in result["rows"]], [2, 1, 2, 1])
        self.assertEqual(result["groups"][0]["trials"], 3)

    def test_missing_is_distinct_from_literal_na_and_history_gate(self):
        recipe = {"shared": {"mode": "all", "rules": [{"field": "intention", "op": "eq", "value": "NA"}]}, "cohorts": [{"id": "a", "name": "a", "mode": "all", "rules": [{"field": "world", "op": "eq", "value": "PM"}]}], "gate": "before_next_outcome", "window": [0, .5], "overlap": "exclude", "strata": "none", "facet": "none", "group_by": "cohort", "split_by": "none"}
        rows = [dict(Loaded.rows[2], world="PM", intention="NA"), dict(Loaded.rows[2], world="PM", intention=None)]
        out = select(rows, recipe, Loaded())
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["row_id"], 3)

    def test_overlap_is_excluded_and_invalid_tests_are_rejected(self):
        recipe = {"shared": {"mode": "all", "rules": []}, "cohorts": [{"id": "a", "name": "a", "mode": "all", "rules": [{"field": "world", "op": "in", "value": ["PP", "PM"]}]}, {"id": "b", "name": "b", "mode": "all", "rules": [{"field": "world", "op": "in", "value": ["PM", "MM"]}]}], "overlap": "exclude", "strata": "none", "facet": "none", "group_by": "cohort", "split_by": "none", "gate": "none"}
        out = select([dict(Loaded.rows[2], world="PM")], recipe, Loaded())
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["summary"]["overlap_excluded"], 1)
        self.assertIn("unknown", validate({"shared": {"mode": "all", "rules": [{"field": "nope", "op": "eq", "value": "x"}]}, "cohorts": []}, Loaded())[0])

    def test_default_recipe_and_deterministic_block_null(self):
        self.assertEqual(len(default_recipe()["cohorts"]), 3)
        request = {"unit_id": 1, "alignment": "object_outcome", "pre": -.5, "post": .5, "bin": .1, "sigma": 0, "count_window": [0, .5], "stability": "all_complete", "recipe": {"enabled": False}, "test": "bogus"}
        with self.assertRaises(ValueError): compute_unit(Loaded(), request)


if __name__ == "__main__":
    unittest.main()
