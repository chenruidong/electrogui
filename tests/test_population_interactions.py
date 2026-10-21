"""Run the real explorer event bindings and numerical display helpers in Node."""
from pathlib import Path
import shutil
import subprocess
import unittest


class PopulationInteractionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_population_interactions(self):
        done = subprocess.run(['node', str(Path(__file__).with_name('population_interactions.js'))],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
