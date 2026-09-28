import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workspace  # noqa: E402

SCRIPT = str(Path(__file__).parent / "workspace.py")


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name).resolve()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()


class FindRootTest(WorkspaceTestCase):
    def test_none_when_no_marker(self):
        self.assertIsNone(workspace.find_root(self.tmp))

    def test_finds_marker_in_start_dir(self):
        (self.tmp / workspace.MARKER).write_text("{}")
        self.assertEqual(workspace.find_root(self.tmp), self.tmp)

    def test_finds_marker_from_nested_subdir(self):
        (self.tmp / workspace.MARKER).write_text("{}")
        nested = self.tmp / "opportunity" / "acme" / "vp"
        nested.mkdir(parents=True)
        self.assertEqual(workspace.find_root(nested), self.tmp)

    def test_defaults_to_cwd(self):
        (self.tmp / workspace.MARKER).write_text("{}")
        nested = self.tmp / "career"
        nested.mkdir()
        os.chdir(nested)
        self.assertEqual(workspace.find_root(), self.tmp)

    def test_nearest_marker_wins(self):
        (self.tmp / workspace.MARKER).write_text("{}")
        inner = self.tmp / "inner"
        inner.mkdir()
        (inner / workspace.MARKER).write_text("{}")
        self.assertEqual(workspace.find_root(inner), inner)

    def test_marker_directory_is_not_a_marker(self):
        (self.tmp / workspace.MARKER).mkdir()
        self.assertIsNone(workspace.find_root(self.tmp))


class InitRootTest(WorkspaceTestCase):
    def test_creates_marker_with_schema(self):
        root = workspace.init_root(self.tmp / "ws")
        data = json.loads((root / workspace.MARKER).read_text())
        self.assertEqual(data["schema"], 1)
        self.assertRegex(data["created"], r"^\d{4}-\d{2}-\d{2}$")

    def test_idempotent_never_overwrites(self):
        (self.tmp / workspace.MARKER).write_text('{"schema": 1, "created": "2000-01-01"}')
        workspace.init_root(self.tmp)
        self.assertIn("2000-01-01", (self.tmp / workspace.MARKER).read_text())


class CliTest(WorkspaceTestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)

    def test_root_outside_workspace_exits_2_with_message(self):
        r = self.run_cli("root")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not inside a job-search-os workspace", r.stderr)
        self.assertIn("bootstrap", r.stderr)

    def test_init_then_root(self):
        r = self.run_cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(r.stdout.strip()), self.tmp)
        r = self.run_cli("root")
        self.assertEqual(Path(r.stdout.strip()), self.tmp)

    def test_init_with_path_containing_space(self):
        r = self.run_cli("init", str(self.tmp / "my search"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "my search" / workspace.MARKER).is_file())


if __name__ == "__main__":
    unittest.main()
