"""Read-only Result Viewer notebook contract and session-bound explorer route."""
import json
from pathlib import Path
import tempfile
import unittest

from electro_gui.unit_notes import read_unit_notes


SID = "sub-Test_ses-2026_01_01"
UNITS = [{"id": 1, "quality": "sua", "area": "ACC", "peak_channel": 28},
         {"id": 2, "quality": "mua", "area": "ACC", "peak_channel": 28}]


class UnitNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / f"{SID}.json"

    def write(self, entries, **extra):
        self.path.write_text(json.dumps({"schema": "result-viewer.notebook/1", "session_id": SID,
                                         "units": entries, **extra}), encoding="utf-8")

    def test_notes_tags_and_flags_match_by_id_without_writing_or_channel_remapping(self):
        self.write({"1": {"unit_id": 1, "note": "reward dip", "tags": ["interesting"], "flag": True,
                          "peak_channel": 28, "quality": "SUA", "area": "acc"},
                    "2": {"unit_id": 2, "tags": ["eye"]},
                    "9": {"unit_id": 9, "note": "same channel, absent ID", "peak_channel": 28}})
        before, stat = self.path.read_bytes(), self.path.stat()
        result = read_unit_notes(self.root, SID, UNITS)
        self.assertTrue(result["available"])
        self.assertEqual(set(result["units"]), {"1", "2"})
        self.assertEqual(result["units"]["1"], {"note": "reward dip", "tags": ["interesting"],
                                                "flag": True, "identity_warnings": []})
        self.assertIn("absent", result["notices"][0])
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), (before, stat.st_mtime_ns))
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_snapshot_mismatch_and_invalid_entries_are_visible(self):
        self.write({"1": {"unit_id": 1, "flag": True, "peak_channel": 22, "quality": "noise"},
                    "2": {"unit_id": 1, "note": "wrong key"},
                    "3": {"unit_id": 3, "tags": "not a list"},
                    "4": {"unit_id": 4, "note": "  "}})
        result = read_unit_notes(self.root, SID, UNITS)
        self.assertEqual(set(result["units"]), {"1"})
        self.assertEqual(len(result["units"]["1"]["identity_warnings"]), 2)
        self.assertIn("saved 22, current 28", result["units"]["1"]["identity_warnings"][0])
        self.assertIn("2 invalid", result["notices"][0])

    def test_missing_unavailable_and_corrupt_notebooks_do_not_break_selection(self):
        self.assertEqual(read_unit_notes(self.root, SID, UNITS), {"units": {}, "available": True, "notices": []})
        for folder in (None, self.root / "unmounted"):
            result = read_unit_notes(folder, SID, UNITS)
            self.assertFalse(result["available"])
            self.assertTrue(result["notices"])
        self.assertFalse((self.root / "unmounted").exists())
        self.path.write_bytes(b"\xff")
        self.assertFalse(read_unit_notes(self.root, SID, UNITS)["available"])
        self.path.write_text("{broken")
        self.assertFalse(read_unit_notes(self.root, SID, UNITS)["available"])
        for change in ({"session_id": "other-session"}, {"schema": "unknown/2"}, {"units": []}):
            self.write({"1": {"unit_id": 1, "note": "wrong session"}}, **change)
            result = read_unit_notes(self.root, SID, UNITS)
            self.assertFalse(result["available"])
            self.assertEqual(result["units"], {})
        for bad in ("../outside", "a/b", "..", ""):
            with self.assertRaises(ValueError):
                read_unit_notes(self.root, bad, UNITS)

    def test_each_read_observes_edits_and_deletions(self):
        self.write({"1": {"unit_id": 1, "note": "first"}})
        self.assertEqual(read_unit_notes(self.root, SID, UNITS)["units"]["1"]["note"], "first")
        self.write({"2": {"unit_id": 2, "flag": True}})
        self.assertEqual(set(read_unit_notes(self.root, SID, UNITS)["units"]), {"2"})
        self.path.unlink()
        self.assertEqual(read_unit_notes(self.root, SID, UNITS)["units"], {})
