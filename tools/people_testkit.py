"""Shared setup for the people tests: a temp workspace holding two tracker
opportunities (Northwind Motors / VP of Engineering, active; Bluefin
Security / Head of Platform, active), and helpers to run the tools in it.
Invented data only."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).parent
sys.path.insert(0, str(TOOLS))
import workspace  # noqa: E402

NW = "northwind_motors/vp_of_engineering"
BF = "bluefin_security/head_of_platform"


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        os.chdir(self.root)
        workspace.init_root(".")
        self.tracker("add", "Northwind Motors", "VP of Engineering", "--stage", "Applied", "--source", "Other")
        self.tracker("add", "Bluefin Security", "Head of Platform", "--stage", "Identified", "--source", "Other")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _run(self, tool, *args):
        return subprocess.run([sys.executable, str(TOOLS / tool), *args], capture_output=True, text=True)

    def tracker(self, *args):
        result = self._run("tracker.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def people(self, *args):
        result = self._run("people.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def people_error(self, *args):
        result = self._run("people.py", *args)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        return result.stderr

    def page(self, slug):
        return (self.root / "people" / f"{slug}.md").read_text()

    def contacts(self, opp):
        return (self.root / "opportunity" / opp / "contacts.md").read_text()

    def events(self):
        path = self.root / "people_events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def set_config(self, **values):
        marker = self.root / workspace.MARKER
        config = json.loads(marker.read_text())
        config.update(values)
        marker.write_text(json.dumps(config))
