"""Targeted dimensionality reduction in electro_gui's population fit."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from electro_gui import explorer, tdr
from electro_gui.data import SessionStore
from tests.synthetic_session import default_spikes, write_synthetic_session_file

UNITS = [1, 2, 3]
PRE, POST, BIN = -0.5, 1.0, 0.05


def body(loaded, **extra):
    rows = explorer.alignment_rows(loaded, "object_outcome")
    spans = explorer.population_spans(loaded, "object_outcome", UNITS, "all_complete")["span"]
    groups = {}
    for row, span in zip(rows, spans):
        if span and PRE - 0.4 >= span[0] - 1e-9 and POST + 0.4 <= span[1] + 1e-9:
            groups.setdefault((row["world"], row["action"]), []).append(int(row["row_id"]))
    req = {"unit_ids": UNITS, "alignment": "object_outcome", "policy": "all_complete", "pre": PRE, "post": POST,
           "bin": BIN, "sigma": 0, "weight": "event", "method": "tdr", "scaling": "zscore", "components": 3,
           "groups": [{"key": f"{w}|{a}", "label": f"{w} {a}", "row_ids": ids} for (w, a), ids in sorted(groups.items())]}
    req.update(extra)
    return req


class TDRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        path = write_synthetic_session_file(Path(cls.temp.name), spikes=default_spikes(), locations={u: "ACC" for u in default_spikes()})
        cls.loaded = SessionStore([], [path], Path(cls.temp.name) / "cache").get(path.name.removesuffix("_session.nwb"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def factor_rows(self):
        return [r for r in explorer.alignment_rows(self.loaded, "object_outcome") if r.get("joystick_direction")]

    def test_joystick_direction_is_a_field(self):
        field = next(f for f in self.loaded.fields if f["key"] == "joystick_direction")
        self.assertEqual(field["availability"], "available")
        self.assertTrue(self.factor_rows())
        self.assertLessEqual({r["joystick_direction"] for r in self.factor_rows()}, {"left", "right"})

    def test_axes_are_orthonormal_and_probe_matches_trajectories(self):
        req = body(self.loaded, factors=["world", "action"], components=2)
        fit = explorer.population_fit(self.loaded, req)
        self.assertEqual(fit["method"], "tdr")
        self.assertEqual(fit["axis_names"], ["Task world", "Object action"])
        q = np.array(fit["loadings"])
        np.testing.assert_allclose(q.T @ q, np.eye(2), atol=1e-5)
        self.assertEqual(fit["tdr"]["window"], [PRE, POST])
        # The projection is x @ Q; the probe must reproduce each group's trajectory centroid.
        req["probe_times"] = [0.25]
        probe = explorer.population_probe(self.loaded, req)["probes"][0]
        j = probe["bin_index"]
        for g, pg in zip(fit["groups"], probe["groups"]):
            self.assertEqual(g["key"], pg["key"])
            np.testing.assert_allclose(np.mean(pg["points"], axis=0), g["coords"][j], atol=1e-4)

    def test_default_factors_are_world_action_joystick(self):
        self.assertEqual(explorer.TDR_DEFAULT_FACTORS, ("world", "action", "joystick_direction"))
        with self.assertRaisesRegex(ValueError, "single level|Fewer than 4"):
            explorer.population_fit(self.loaded, body(self.loaded))   # the fixture has one direction

    def test_planted_axes_are_recovered(self):
        rng = np.random.default_rng(0)
        n_units, n_bins, n_events = 12, 10, 240
        world = rng.choice(["PP", "PM", "MM"], n_events)
        action = rng.choice(["touch", "avoid"], n_events)
        direction = rng.choice(["left", "right"], n_events)
        planted = np.linalg.qr(rng.normal(size=(n_units, 3)))[0]
        rows = [{"world": w, "action": a, "joystick_direction": d} for w, a, d in zip(world, action, direction)]
        registry = {"world": {"values": ["PP", "PM", "MM"]}, "action": {}, "joystick_direction": {}}
        X, keep, described = tdr.design(rows, ["world", "action", "joystick_direction"], registry)
        self.assertEqual(X.shape, (n_events, 1 + 1 + 1 + 1))          # world is one ordinal column
        np.testing.assert_array_equal(X[:, 1], np.select([world == "PP", world == "PM"], [-1., 0.], 1.))
        # Each factor acts on its own axis in its own time bin (world 2, action 5, direction 8).
        signal = np.stack([(world == "PP") * 1.0 - (world == "MM"), (action == "touch") * 2.0 - 1, (direction == "left") * 2.0 - 1])
        rates = rng.normal(0, .1, (n_events, n_bins, n_units))
        for f, t in enumerate((2, 5, 8)):
            rates[:, t, :] += np.outer(signal[f], planted[:, f]) * 3
        means = rates.reshape(n_events, n_bins, n_units)[:8]     # any (groups, times, units) array of the same units
        fit = tdr.fit_axes(means, list(range(n_units)), rates, X, described, np.arange(n_bins), "center")
        q = fit["loadings"]
        np.testing.assert_allclose(q.T @ q, np.eye(3), atol=1e-10)
        self.assertEqual([f["peak_bin"] for f in fit["tdr"]["factors"]], [2, 5, 8])
        for k in range(3):
            self.assertGreater(abs(float(q[:, k] @ planted[:, k])), .9)

    def test_stepwise_world_coding_gives_pp_pm_and_pm_mm_coefficients(self):
        rng = np.random.default_rng(1)
        world = rng.choice(["PP", "PM", "MM"], 300)
        rows = [{"world": w, "action": a} for w, a in zip(world, rng.choice(["touch", "avoid"], 300))]
        registry = {"world": {"values": ["PP", "PM", "MM"], "label": "Task world"}, "action": {}}
        X, _, described = tdr.design(rows, ["world", "action"], registry, "steps")
        self.assertEqual([d["label"] for d in described], ["Task world PP→PM", "Task world PM→MM", "action"])
        y = np.select([world == "PP", world == "PM"], [1., 4.], 6.)        # PM - PP = 3, MM - PM = 2
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        np.testing.assert_allclose(beta[[1, 2]], [3., 2.], atol=1e-9)
        with self.assertRaisesRegex(ValueError, "all present"):
            tdr.design([r for r in rows if r["world"] != "MM"], ["world", "action"], registry, "steps")

    def test_window_and_factor_choices_are_honoured_and_validated(self):
        fit = explorer.population_fit(self.loaded, body(self.loaded, factors=["world", "action"], tdr_window=[0.0, 0.5], components=2))
        self.assertEqual(fit["components"], 2)
        self.assertEqual(fit["tdr"]["window"], [0.0, 0.5])
        for f in fit["tdr"]["factors"]:
            self.assertTrue(0.0 - 1e-9 <= f["peak_time"] <= 0.5 + 1e-9)
        with self.assertRaisesRegex(ValueError, "TDR window"):
            explorer.population_fit(self.loaded, body(self.loaded, factors=["world", "action"], tdr_window=[0.5, 2.0]))
        with self.assertRaisesRegex(ValueError, "not available"):
            explorer.population_fit(self.loaded, body(self.loaded, factors=["world", "gaze_direction"]))
        with self.assertRaisesRegex(ValueError, "2-10"):
            explorer.population_fit(self.loaded, body(self.loaded, factors=["world"]))


if __name__ == "__main__":
    unittest.main()
