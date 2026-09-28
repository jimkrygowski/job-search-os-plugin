import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent


class NoBytecodeInPluginRootTest(unittest.TestCase):
    """Running the tools must not write __pycache__ into the plugin
    directory (${CLAUDE_PLUGIN_ROOT} is never a place for state)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name).resolve()
        self.plugin = self.tmp / "plugin"
        shutil.copytree(REPO / "tools", self.plugin / "tools",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(REPO / "guidance", self.plugin / "guidance")
        self.ws = self.tmp / "ws"
        subprocess.run([sys.executable, str(self.plugin / "tools/workspace.py"), "init", str(self.ws)],
                       check=True, capture_output=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def run_tool(self, name, *args, stdin=""):
        return subprocess.run([sys.executable, str(self.plugin / "tools" / name), *args],
                              input=stdin, cwd=self.ws, capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(self.ws)})

    def test_entry_scripts_leave_no_pycache(self):
        self.run_tool("session_start.py", stdin="{}")
        self.run_tool("guard_send.py", stdin=json.dumps({"tool_name": "x"}))
        self.run_tool("tracker.py", "list")
        self.run_tool("score_table.py", "criteria")
        self.run_tool("check_bootstrap_state.py")
        self.run_tool("migrate.py", "--from", str(self.tmp / "nope"), "--dry-run")
        self.assertEqual(list(self.plugin.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
