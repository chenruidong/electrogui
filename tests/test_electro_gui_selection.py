import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from electro_gui.selection import select_stable_population


class _Stability:
    def __init__(self, masks, key="cache-key"):
        self.stable_trials = masks
        self.cache_key = key
        self.summary = {"source_nwb": "/session.nwb", "counts": {"n_stable": len(masks)}}


def _loaded(masks, *, qualities=None, complete=(1, 2, 3, 4, 5)):
    qualities = qualities or {uid: "SUA" for uid in masks}
    units = [{"id": uid, "quality": quality} for uid, quality in qualities.items()]
    trials = [{"id": tid, "complete": tid in complete} for tid in range(1, 7)]
    return SimpleNamespace(
        session=object(), cache_dir=Path(tempfile.gettempdir()), session_id="sub-test",
        units=units, trials=trials, _check=lambda: None,
    )


class StableSelectionTests(unittest.TestCase):
    def test_overlapping_masks_choose_population_and_complete_trials(self):
        loaded = _loaded({1: (1, 2, 3), 2: (2, 3, 4), 3: (4, 5)})
        with patch("electro_gui.selection.get_session_stability", return_value=_Stability({1: (1, 2, 3), 2: (2, 3, 4), 3: (4, 5)})) as provider:
            result = select_stable_population(loaded)
        self.assertEqual(result["unit_ids"], [1, 2])
        self.assertEqual(result["trial_ids"], [2, 3])
        self.assertEqual(result["candidate_units"], 3)
        self.assertEqual(result["candidate_unit_ids"], [1, 2, 3])
        self.assertEqual(result["coverage"], 4)
        provider.assert_called_once_with(loaded.session, cache_root=loaded.cache_dir)

    def test_quality_is_case_insensitive_and_non_sua_mua_is_excluded(self):
        loaded = _loaded({1: (1, 2), 2: (1, 2), 3: (1, 2)}, qualities={1: "sUa", 2: "mUa", 3: "noise"})
        with patch("electro_gui.selection.get_session_stability", return_value=_Stability({1: (1, 2), 2: (1, 2), 3: (1, 2)})):
            result = select_stable_population(loaded)
        self.assertEqual(result["candidate_units"], 2)
        self.assertEqual(result["unit_ids"], [1, 2])

    def test_disjoint_or_zero_masks_return_valid_empty_support(self):
        loaded = _loaded({1: (), 2: (6,)})
        with patch("electro_gui.selection.get_session_stability", return_value=_Stability({1: (), 2: (6,)})):
            result = select_stable_population(loaded)
        self.assertEqual(result["candidate_units"], 2)
        self.assertEqual(result["candidate_unit_ids"], [1, 2])
        self.assertEqual(result["unit_ids"], [])
        self.assertEqual(result["trial_ids"], [])
        self.assertEqual(result["n_units"], 0)
        self.assertEqual(result["n_trials"], 0)

    def test_deterministic_ties_and_tradeoff_avoid_roster_collapse(self):
        # Adding unit 3 would collapse two shared trials to one, so the
        # product-preserving rule keeps the two-unit population.
        loaded = _loaded({1: (1, 2, 3), 2: (1, 2, 3), 3: (1,)})
        with patch("electro_gui.selection.get_session_stability", return_value=_Stability({1: (1, 2, 3), 2: (1, 2, 3), 3: (1,)})):
            first = select_stable_population(loaded)
            second = select_stable_population(loaded)
        self.assertEqual(first, second)
        self.assertEqual(first["unit_ids"], [1, 2])
        self.assertEqual(first["trial_ids"], [1, 2, 3])
        json.dumps(first)


if __name__ == "__main__":
    unittest.main()
