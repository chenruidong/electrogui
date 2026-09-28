import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electro_gui.data import SessionStore
from imitation_phys.session_file import write_session_file
from tests.synthetic_session import write_synthetic_artefacts


class ElectroGuiDataTests(unittest.TestCase):
    def _store(self, root):
        artefacts = write_synthetic_artefacts(root)
        result = write_session_file(
            session_id=artefacts.session_id, units_path=artefacts.units,
            behavior_path=artefacts.behavior, alignment_path=artefacts.alignment,
            events_path=artefacts.events, stability_path=artefacts.stability,
            stable_trials_path=artefacts.stable_trials,
            stability_summary_path=artefacts.summary, output_dir=artefacts.nwb_dir,
        )
        target = root / artefacts.session_id / "analysis" / "nwb"
        target.mkdir(parents=True)
        path = target / f"{artefacts.session_id}_session.nwb"
        Path(result["path"]).replace(path)
        return artefacts.session_id, path

    def test_catalog_excludes_sidecars_scratch_and_wrong_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sid, path = self._store(root)
            (path.parent / f"._{sid}_session.nwb").write_bytes(b"sidecar")
            scratch = root / "scratch" / "analysis" / "nwb"; scratch.mkdir(parents=True)
            (scratch / f"{sid}_session.nwb").write_bytes(b"wrong")
            entries = SessionStore([root]).catalog()
            self.assertEqual(entries, [{"id": sid, "path": str(path.resolve())}])

    def test_loaded_metadata_rows_spikes_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sid, _ = self._store(root)
            loaded = SessionStore([root], cache_dir=Path(td) / "cache").get(sid)
            self.assertEqual(len(loaded.units), 6)
            self.assertEqual(len(loaded.rows), 32)
            self.assertEqual(loaded.trials[0]["world"], "PP")
            self.assertTrue(all("row_id" in row for row in loaded.rows))
            field_map = {field["key"]: field for field in loaded.fields}
            self.assertIn("joystick_direction", field_map)
            self.assertEqual(field_map["joystick_direction"]["availability"], "unavailable")
            self.assertGreater(len(loaded.spikes(1)), 0)
            self.assertEqual(loaded.eligibility([1], "all_complete")[0], {0, 1, 2, 3, 4, 5, 6})
            self.assertEqual(loaded.metadata()["source"]["sha256"], loaded.session.source_identity()["sha256"])
            by_key = {f["key"]: f for f in loaded.fields}
            self.assertEqual(by_key["trial.success"]["timing"], "full_trial_posthoc")
            self.assertEqual(by_key["previous_role"]["timing"], "resolved_by_anchor")

    def test_stability_does_not_read_legacy_embedded_mask(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); sid, _ = self._store(root)
            loaded = SessionStore([root], cache_dir=Path(td) / "cache").get(sid)
            with patch.object(type(loaded.session), "legacy_stability_table", side_effect=AssertionError("legacy fallback")):
                common, provenance = loaded.eligibility([1], "verified_stable")
            self.assertIsInstance(common, set)
            self.assertEqual(provenance["policy"], "verified_stable")


if __name__ == "__main__":
    unittest.main()
