"""The GUI's population export is what world-axis-projection reproduces.

world-axis-projection (analysis_imitation's ``imitation_phys.world_axis_projection``)
takes an electro_gui Population settings export and refuses to go on unless it
can recompute the export's explained-variance ratios and group counts.  The
stage's own tests build their export from ``explorer_core``; this test builds it
the way the browser does, with ``explorer.population_fit``, so a change on
either side that breaks the hand-off fails here.  Unit 1 carries a planted world
signal at the probe time (MM > PM > PP), so the axis also has a known answer.
"""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from electro_gui import explorer
from imitation_phys import explorer_core
from imitation_phys import world_axis_projection as wap
from imitation_phys.session_store import SessionStore
from imitation_phys.synthetic_session import default_events, default_spikes, write_synthetic_session_file

UNITS = [1, 2, 3]
PRE, POST, BIN, SIGMA, PROBE = -0.5, 1.0, 0.05, 0.05, 0.5
PLANT = {"PP": 0, "PM": 15, "MM": 30}          # extra unit-1 spikes in [probe - 0.1, probe + 0.1) s
WORLDS = ["PP", "PP", "PM", "PM", "MM", "MM", "PP", "PP"]


def _session(root: Path) -> Path:
    events = default_events()
    outcomes = events[events["event"].isin(explorer_core.OUTCOMES)]
    rng = np.random.default_rng(3)
    spikes = default_spikes()
    extra = [float(t) + PROBE + rng.uniform(-0.1, 0.1, PLANT[WORLDS[int(i)]])
             for i, t in zip(outcomes["trial_index"], outcomes["t_ephys_s"])]
    spikes[1] = np.sort(np.concatenate([spikes[1], *extra]))
    return write_synthetic_session_file(root, spikes=spikes, locations={u: "ACC" for u in spikes})


def _gui_export(loaded, path: Path) -> dict:
    """The Population view's export for role in {predator, prey} coloured by world, fitted by the GUI."""
    rows = explorer_core.alignment_rows(loaded, "object_outcome")
    spans = explorer_core.population_spans(loaded, "object_outcome", UNITS, "verified_stable")["span"]
    groups = {}
    for row, span in zip(rows, spans):
        if span and PRE - 0.4 >= span[0] - 1e-9 and POST + 0.4 <= span[1] + 1e-9 and row.get("role") in ("predator", "prey"):
            groups.setdefault(row["world"], []).append(int(row["row_id"]))
    body = {"unit_ids": UNITS, "alignment": "object_outcome", "policy": "verified_stable", "pre": PRE, "post": POST,
            "bin": BIN, "sigma": SIGMA, "weight": "event", "method": "pca", "scaling": "center", "components": 2,
            "groups": [{"key": f"{w}␟␟", "label": w, "row_ids": groups[w]} for w in ("PP", "PM", "MM")]}
    fit = explorer.population_fit(loaded, body)
    return {
        "tool": "electro_gui 0.2 explorer · population", "session_id": loaded.session_id,
        "source": {"path": str(path), "sha256": loaded.metadata()["source"].get("sha256")},
        "alignment": "object_outcome", "policy": "verified_stable", "unit_ids": UNITS,
        "active_unit_ids": fit["active_unit_ids"], "method": "pca", "scaling": "center", "components": 2,
        "explained_variance_ratio": fit["explained_variance_ratio"], "window": [PRE, POST], "bin": BIN,
        "sigma": SIGMA, "common_trials": fit["common_trials"],
        "groups": [{"key": g["key"], "label": g["label"], "events": g["events"], "trials": g["trials"]}
                   for g in fit["groups"]],
        "state": {"mode": "population", "filters": [{"k": "role", "v": ["predator", "prey"]}], "color": "world",
                  "style": None, "weight": "event"},
    }


class WorldAxisContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        path = _session(Path(cls.temp.name))
        sid = path.name.removesuffix("_session.nwb")
        cls.loaded = SessionStore([], [path], Path(cls.temp.name) / "cache").get(sid)
        cls.result = wap.score(cls.loaded, _gui_export(cls.loaded, path), PROBE)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_stage_reproduces_the_gui_export(self):
        self.assertTrue(self.result["checks"])
        for check in self.result["checks"]:
            self.assertTrue(check["ok"], check)

    def test_the_axis_finds_the_planted_world_signal(self):
        axis = self.result["axis"]
        self.assertEqual(int(np.argmax(np.abs(axis))), UNITS.index(1))
        proj = [g["projection"] for g in self.result["groups"]]
        self.assertEqual([g["label"] for g in self.result["groups"]], ["PP", "PM", "MM"])
        self.assertLess(proj[0], proj[1])
        self.assertLess(proj[1], proj[2])


if __name__ == "__main__":
    unittest.main()
