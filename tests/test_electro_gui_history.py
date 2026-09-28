import unittest
from types import SimpleNamespace

import pandas as pd

from electro_gui.data import _enrich, _registry
from electro_gui.analysis import prepare_rows


def _events(rows):
    base = {
        "t_ephys_s": 0.0,
        "trial_index": 0,
        "object_uid": None,
        "kind": None,
        "info": {},
        "within_ephys_recording": True,
        "within_sync_fit_window": True,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


def _trials(**overrides):
    row = {
        "start_time": 0.0,
        "stop_time": 10.0,
        "block_type": "PP",
        "complete": True,
        "success": 1.0,
        "preset_block_id": 4,
    }
    row.update(overrides)
    return pd.DataFrame([row], index=pd.Index([0], name="trial_index"))


class ElectroGuiHistoryTests(unittest.TestCase):
    def test_lifecycle_rows_do_not_become_objects_and_original_rows_survive(self):
        events = _events([
            {"event": "gaze_target", "t_ephys_s": 0.5, "object_uid": "target", "kind": "gaze", "info": {"agent": "predator", "starting_point": 1}},
            {"event": "object_visible_onset", "t_ephys_s": 1.0, "object_uid": "prey-1", "kind": "+", "info": {"is_bar": False, "ordinal": 1, "image_id": "squarequalum_1"}},
            {"event": "prey_capture", "t_ephys_s": 2.0, "object_uid": "prey-1", "kind": "+", "info": {"is_bar": False, "ordinal": 1, "image_id": "squarequalum_1"}},
        ])
        _, rows = _enrich(_trials(), events, classify=lambda row, include_bars=False: "PP")
        gaze = rows[0]
        self.assertEqual(gaze["row_id"], 0)
        self.assertIsNone(gaze["role"])
        self.assertEqual(rows[2]["row_id"], 2)
        self.assertEqual(rows[2]["outcome"], "prey_capture")

    def test_previous_and_next_outcomes_use_actual_timestamps_and_ordinal_history(self):
        events = _events([
            {"event": "object_visible_onset", "t_ephys_s": 1.0, "object_uid": "prey-1", "kind": "+", "info": {"is_bar": False, "ordinal": 1}},
            {"event": "object_visible_onset", "t_ephys_s": 1.5, "object_uid": "prey-2", "kind": "+", "info": {"is_bar": False, "ordinal": 2}},
            {"event": "prey_capture", "t_ephys_s": 4.0, "object_uid": "prey-1", "kind": "+", "info": {"is_bar": False, "ordinal": 1}},
            {"event": "prey_miss", "t_ephys_s": 6.0, "object_uid": "prey-2", "kind": "+", "info": {"is_bar": False, "ordinal": 2}},
            {"event": "trial_initiation", "t_ephys_s": 3.0},
            {"event": "trial_status", "t_ephys_s": 5.0},
        ])
        _, rows = _enrich(_trials(), events, classify=lambda row, include_bars=False: "PP")
        first = next(row for row in rows if row["event"] == "prey_capture")
        second = next(row for row in rows if row["event"] == "prey_miss")
        anchor = next(row for row in rows if row["event"] == "trial_initiation")
        later = next(row for row in rows if row["event"] == "trial_status")
        self.assertIsNone(first["previous_outcome"])
        self.assertEqual(first["next_outcome"], "prey_miss")
        self.assertEqual(first["next_outcome_t"], 6.0)
        self.assertEqual(second["previous_outcome"], "prey_capture")
        self.assertIsNone(second["next_outcome"])
        self.assertIsNone(anchor["previous_outcome"])
        self.assertEqual(anchor["next_outcome_t"], 4.0)
        self.assertEqual(later["previous_outcome"], "prey_capture")

    def test_trial_initiation_next_role_survives_condition_selection(self):
        events = _events([
            {"event": "trial_initiation", "t_ephys_s": 2.0},
            {"event": "object_visible_onset", "t_ephys_s": 3.0, "object_uid": "first", "kind": "-", "info": {"is_bar": False, "ordinal": 1}},
            {"event": "predator_avoid", "t_ephys_s": 4.0, "object_uid": "first", "kind": "-", "info": {"is_bar": False, "ordinal": 1}},
            {"event": "object_visible_onset", "t_ephys_s": 5.0, "object_uid": "second", "kind": "+", "info": {"is_bar": False, "ordinal": 2}},
            {"event": "prey_capture", "t_ephys_s": 6.0, "object_uid": "second", "kind": "+", "info": {"is_bar": False, "ordinal": 2}},
            # Real task pre-spawns every object before trial initiation, in a
            # different order from visibility. Spawn time cannot choose next.
            {"event": "object_spawn", "t_ephys_s": 0.0, "object_uid": "second", "kind": "+", "info": {"is_bar": False, "ordinal": 2}},
            {"event": "object_spawn", "t_ephys_s": 0.0, "object_uid": "first", "kind": "-", "info": {"is_bar": False, "ordinal": 1}},
        ])
        trials, rows = _enrich(_trials(), events)
        self.assertIsNone(rows[0]["role"])
        self.assertEqual(rows[0]["next_role"], "predator")
        self.assertEqual(rows[0]["next_action"], "avoid")
        self.assertEqual(rows[0]["next_outcome"], "predator_avoid")
        self.assertEqual(rows[2]["next_role"], "prey")
        loaded = SimpleNamespace(trials=trials, rows=rows, fields=_registry(_trials(), rows),
                                 alignments=["trial_initiation"], duration_s=10.,
                                 eligibility=lambda ids, policy: ({0}, {"policy": policy}))
        request = {"alignment": "trial_initiation", "pre": -.5, "post": .5, "bin": .05,
                   "sigma": 0, "count_window": [0, .5], "stability": "all_complete",
                   "recipe": {"enabled": True, "shared": {"mode": "all", "rules": []},
                              "cohorts": [{"id": "next_predator", "name": "Next predator", "mode": "all",
                                           "rules": [{"field": "next_role", "op": "eq", "value": "predator"}]}],
                              "overlap": "exclude", "group_by": "cohort", "split_by": "none", "facet": "none"}}
        selected, support, _ = prepare_rows(loaded, request, [1])
        self.assertEqual([r["event"] for r in selected], ["trial_initiation"])
        self.assertEqual(support["selected_trials"], 1)

    def test_non_object_next_uses_onset_and_never_skips_unknown_or_crosses_trials(self):
        events = _events([
            {"event": "trial_initiation", "t_ephys_s": 1.0},
            {"event": "object_visible_onset", "t_ephys_s": 1.0, "object_uid": "unresolved", "info": {"is_bar": False, "ordinal": 1}},
            {"event": "trial_status", "t_ephys_s": 2.0},
            {"event": "object_visible_onset", "t_ephys_s": 3.0, "object_uid": "prey", "kind": "+", "info": {"is_bar": False, "ordinal": 2}},
            {"event": "trial_status", "t_ephys_s": 4.0},
            {"event": "trial_status", "t_ephys_s": float("nan")},
            {"event": "object_visible_onset", "trial_index": 1, "t_ephys_s": 5.0, "object_uid": "other-trial", "kind": "-", "info": {"is_bar": False, "ordinal": 1}},
        ])
        _, rows = _enrich(_trials(), events)
        self.assertIsNone(rows[0]["next_role"])  # Actual next object's role is unknown.
        self.assertEqual(rows[2]["next_role"], "prey")  # Recorded role needs no outcome.
        self.assertIsNone(rows[2]["next_action"])
        self.assertIsNone(rows[2]["next_outcome"])
        self.assertIsNone(rows[4]["next_role"])  # No fallback to the next trial.
        self.assertIsNone(rows[5]["next_role"])

    def test_bar_only_or_unresolved_trials_have_unknown_error_free_and_intention(self):
        events = _events([
            {"event": "object_visible_onset", "t_ephys_s": 1.0, "object_uid": "bar", "kind": "+", "info": {"is_bar": True, "ordinal": 1}},
        ])
        trials, rows = _enrich(_trials(), events, classify=lambda row, include_bars=False: "PP")
        self.assertIsNone(trials[0]["trial_error_free"])
        self.assertIsNone(trials[0]["intention"])
        self.assertIsNone(rows[0]["trial_error_free"])
        self.assertIsInstance(rows[0]["success"], bool)


if __name__ == "__main__":
    unittest.main()
