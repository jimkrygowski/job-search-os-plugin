import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import guard_send  # noqa: E402
import workspace  # noqa: E402

SCRIPT = str(Path(__file__).parent / "guard_send.py")
SEND = "mcp__claude_ai_Gmail__send_message"


class GuardSendTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name).resolve()

    def tearDown(self):
        self._tmpdir.cleanup()

    def run_hook(self, stdin, project_dir):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
        return subprocess.run([sys.executable, SCRIPT], input=stdin, env=env,
                              cwd=self.tmp, capture_output=True, text=True)

    def assertDenied(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("draft", out["permissionDecisionReason"].lower())

    def test_pattern(self):
        for name in ["mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__reply",
                     "mcp__claude_ai_Gmail__forward", "mcp__plugin_x_Gmail__send_message"]:
            self.assertRegex(name, guard_send.SEND_TOOL)
        for name in ["mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Gmail__get_thread",
                     "mcp__claude_ai_Gmail__reply_all_draft", "Bash"]:
            self.assertNotRegex(name, guard_send.SEND_TOOL)

    def test_denies_inside_workspace(self):
        workspace.init_root(self.tmp)
        self.assertDenied(self.run_hook(json.dumps({"tool_name": SEND}), self.tmp))

    def test_denies_from_workspace_subdir(self):
        workspace.init_root(self.tmp)
        sub = self.tmp / "career"
        sub.mkdir()
        self.assertDenied(self.run_hook(json.dumps({"tool_name": SEND}), sub))

    def test_denies_when_only_stdin_cwd_is_in_workspace(self):
        ws = self.tmp / "ws"
        workspace.init_root(ws)
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        r = self.run_hook(json.dumps({"tool_name": SEND, "cwd": str(ws / "career")}), outside)
        self.assertDenied(r)

    def test_silent_outside_workspace(self):
        r = self.run_hook(json.dumps({"tool_name": SEND}), self.tmp)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_silent_for_non_send_tool_inside_workspace(self):
        workspace.init_root(self.tmp)
        r = self.run_hook(json.dumps({"tool_name": "mcp__claude_ai_Gmail__create_draft"}), self.tmp)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_malformed_input_fails_closed(self):
        self.assertDenied(self.run_hook("not json", self.tmp))


if __name__ == "__main__":
    unittest.main()
