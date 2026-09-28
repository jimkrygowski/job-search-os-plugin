import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import session_start  # noqa: E402
import workspace  # noqa: E402

SCRIPT = str(Path(__file__).parent / "session_start.py")
PLUGIN_ROOT = str(Path(__file__).parent.parent.resolve())


class SessionStartTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name).resolve()

    def tearDown(self):
        self._tmpdir.cleanup()

    def run_hook(self, stdin, project_dir=None, cwd=None):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["CLAUDE_PLUGIN_ROOT"] = PLUGIN_ROOT
        if project_dir is not None:
            env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        return subprocess.run([sys.executable, SCRIPT], input=stdin, env=env,
                              cwd=cwd or self.tmp, capture_output=True, text=True)

    def test_outside_workspace_silent(self):
        r = self.run_hook(json.dumps({"cwd": str(self.tmp)}), project_dir=self.tmp)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_inside_workspace_injects_persona_and_note(self):
        workspace.init_root(self.tmp)
        r = self.run_hook(json.dumps({"cwd": str(self.tmp)}), project_dir=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("Never invent experience", out["additionalContext"])
        self.assertIn("career/profile.md does not exist", out["additionalContext"])
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", out["additionalContext"])
        self.assertIn(PLUGIN_ROOT + "/tools/tracker.py", out["additionalContext"])

    def test_project_dir_is_workspace_subdir(self):
        workspace.init_root(self.tmp)
        sub = self.tmp / "opportunity"
        sub.mkdir()
        r = self.run_hook("{}", project_dir=sub)
        self.assertIn("Never invent experience", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_malformed_stdin_falls_back_to_cwd(self):
        workspace.init_root(self.tmp)
        r = self.run_hook("not json", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Never invent experience", r.stdout)

    def test_empty_stdin_uses_stdin_cwd_field_absent(self):
        r = self.run_hook("", cwd=self.tmp)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
