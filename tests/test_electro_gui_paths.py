"""Where the explorer keeps its cache and findings and finds figure configs (electro_gui/paths.py, cli._folders)."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from electro_gui import cli, paths


def _env(**values):
    """os.environ without the three variables the resolver reads, plus ``values``."""
    env = {k: v for k, v in os.environ.items() if k not in ("DROPBOX_ROOT", paths.OUTPUT_ENV, "RESULT_VIEWER_DATA", "HOME")}
    return mock.patch.dict(os.environ, {**env, **values}, clear=True)


class PathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_the_dropbox_root_comes_from_info_json_business_first(self):
        (self.root / ".dropbox").mkdir()
        (self.root / ".dropbox" / "info.json").write_text(json.dumps(
            {"personal": {"path": "/p/Dropbox (Personal)"}, "business": {"path": "/b/MIT Dropbox/Someone"}}))
        with _env(HOME=str(self.root)):
            self.assertEqual(paths.dropbox_root(), Path("/b/MIT Dropbox/Someone"))
            self.assertEqual(paths.output_root(), Path("/b/MIT Dropbox/Someone/projects/electro_gui/output"))
            self.assertEqual(paths.presentation_dir(),
                             Path("/b/MIT Dropbox/Someone/projects/analysis_imitation/data/output/presentation"))

    def test_dropbox_root_and_output_overrides(self):
        with _env(HOME=str(self.root), DROPBOX_ROOT="/d"):
            self.assertEqual(paths.output_root(), Path("/d/projects/electro_gui/output"))
        with _env(HOME=str(self.root), DROPBOX_ROOT="/d", **{paths.OUTPUT_ENV: "/elsewhere/out"}):
            self.assertEqual(paths.output_root(), Path("/elsewhere/out"))
            self.assertEqual(paths.presentation_dir(), Path("/d/projects/analysis_imitation/data/output/presentation"))

    def test_without_dropbox_there_is_no_default(self):
        with _env(HOME=str(self.root)):
            self.assertIsNone(paths.dropbox_root())
            self.assertIsNone(paths.output_root())
            self.assertIsNone(paths.presentation_dir())
            self.assertIsNone(paths.unit_notes_dir())

    def test_result_viewer_notebooks_follow_its_override_or_dropbox(self):
        with _env(HOME=str(self.root), DROPBOX_ROOT="/d"):
            self.assertEqual(paths.unit_notes_dir(), Path("/d/projects/result-viewer/data/notes"))
        with _env(HOME=str(self.root), DROPBOX_ROOT="/d", RESULT_VIEWER_DATA="~/viewer-data"):
            self.assertEqual(paths.unit_notes_dir(), self.root / "viewer-data" / "notes")
        args = cli.add_arguments(argparse.ArgumentParser()).parse_args(["--unit-notes-dir", "/other/notes"])
        self.assertEqual(args.unit_notes_dir, "/other/notes")

    def test_cli_defaults_are_the_dropbox_folders(self):
        args = cli.add_arguments(argparse.ArgumentParser()).parse_args([])
        self.assertIsNone(args.cache_dir)
        self.assertIsNone(args.findings_dir)
        with _env(HOME=str(self.root), DROPBOX_ROOT="/d"):
            cache, findings, configs = cli._folders(args)
        self.assertEqual(cache, Path("/d/projects/electro_gui/output/cache"))
        self.assertEqual(findings, Path("/d/projects/electro_gui/output/findings"))
        self.assertEqual(configs, [Path("/d/projects/analysis_imitation/data/output/presentation")])

    def test_flags_replace_the_defaults_one_folder_each(self):
        args = cli.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--findings-dir", "f", "--config-dir", "c1", "--config-dir", "c2"])
        with _env(HOME=str(self.root), DROPBOX_ROOT="/d"):
            cache, findings, configs = cli._folders(args)
        self.assertEqual(cache, Path("/d/projects/electro_gui/output/cache"))
        self.assertEqual(findings, Path("f"))
        self.assertEqual(configs, ["c1", "c2"])

    def test_without_dropbox_the_cli_asks_for_the_folders(self):
        bare = cli.add_arguments(argparse.ArgumentParser()).parse_args([])
        with _env(HOME=str(self.root)), self.assertRaises(SystemExit) as stop:
            cli._folders(bare)
        self.assertIn(paths.OUTPUT_ENV, str(stop.exception))
        given = cli.add_arguments(argparse.ArgumentParser()).parse_args(["--cache-dir", "c", "--findings-dir", "f"])
        with _env(HOME=str(self.root)):
            self.assertEqual(cli._folders(given), (Path("c"), Path("f"), []))


if __name__ == "__main__":
    unittest.main()
