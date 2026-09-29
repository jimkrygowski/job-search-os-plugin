import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import migrate  # noqa: E402
import workspace  # noqa: E402

SCRIPT = str(Path(__file__).parent / "migrate.py")


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name).resolve()
        self.repo = self.tmp / "job-search-os"
        state = self.repo / "state"
        (state / "career" / "resume").mkdir(parents=True)
        (state / "career" / "profile.md").write_text("## Career History\n\nx\n")
        (state / "career" / "resume" / "master_resume.md").write_text("resume")
        (state / "opportunity" / "acme" / "vp").mkdir(parents=True)
        (state / "opportunity" / "acme" / "vp" / "jd.md").write_text("jd")
        (state / "tracker.md").write_text("# Active Opportunities\n")
        (state / ".tracker.lock").write_text("")
        (state / ".DS_Store").write_text("")
        (state / "__pycache__").mkdir()
        (state / "__pycache__" / "x.pyc").write_text("")
        self.dst = self.tmp / "ws"

    def tearDown(self):
        self._tmpdir.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)

    def test_copies_tree_skips_junk_writes_marker(self):
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.dst / "career/resume/master_resume.md").read_text(), "resume")
        self.assertEqual((self.dst / "opportunity/acme/vp/jd.md").read_text(), "jd")
        self.assertTrue((self.dst / "tracker.md").exists())
        self.assertTrue((self.dst / workspace.MARKER).is_file())
        for junk in [".tracker.lock", ".DS_Store", "__pycache__"]:
            self.assertFalse((self.dst / junk).exists(), junk)
        self.assertIn("4 files", r.stdout)

    def test_reports_noncanonical_stages_without_changing_them(self):
        table = (
            "# Active Opportunities\n\n"
            "| Company | Role | Stage | Last Activity | Next Action | Next Action Date |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| Acme | VP | Phone Screen | 2026-08-01 |  |  |\n"
            "| Beta | CTO | Networking | 2026-08-01 |  |  |\n"
            "| Gamma | CTO | Applied | 2026-08-01 |  |  |\n"
        )
        (self.repo / "state" / "tracker.md").write_text(table)
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("'Phone Screen' -> 'Recruiter Screen'", r.stdout)
        self.assertIn("'Networking'", r.stdout)
        self.assertNotIn("'Applied'", r.stdout)
        self.assertEqual((self.dst / "tracker.md").read_text(), table)

    def test_preserves_empty_directories(self):
        (self.repo / "state" / "opportunity" / "acme" / "vp" / "transcripts").mkdir()
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dst / "opportunity/acme/vp/transcripts").is_dir())

    def test_preserves_directory_holding_only_skipped_files(self):
        d = self.repo / "state" / "opportunity" / "acme" / "vp" / "notes_dir"
        d.mkdir()
        (d / ".DS_Store").write_text("")
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dst / "opportunity/acme/vp/notes_dir").is_dir())

    def test_refuses_destination_inside_source_checkout(self):
        for dst in [self.repo, self.repo / "state", self.repo / "state" / "career" / "x",
                    self.repo / "subdir"]:
            before = sorted(p.relative_to(self.repo) for p in self.repo.rglob("*"))
            r = self.run_cli("--from", str(self.repo), "--to", str(dst))
            self.assertEqual(r.returncode, 2, dst)
            self.assertIn("inside the old checkout", r.stderr)
            self.assertEqual(sorted(p.relative_to(self.repo) for p in self.repo.rglob("*")), before)

    def test_refuses_destination_inside_source_when_given_state_dir(self):
        r = self.run_cli("--from", str(self.repo / "state"), "--to", str(self.repo))
        self.assertEqual(r.returncode, 2)

    def test_accepts_state_dir_itself(self):
        r = self.run_cli("--from", str(self.repo / "state"), "--to", str(self.dst))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dst / "tracker.md").exists())

    def test_source_untouched(self):
        before = sorted(p.relative_to(self.repo) for p in self.repo.rglob("*"))
        self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(sorted(p.relative_to(self.repo) for p in self.repo.rglob("*")), before)

    def test_conflict_copies_nothing(self):
        self.dst.mkdir()
        (self.dst / "tracker.md").write_text("mine")
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(r.returncode, 1)
        self.assertIn("tracker.md", r.stdout + r.stderr)
        self.assertEqual((self.dst / "tracker.md").read_text(), "mine")
        self.assertFalse((self.dst / "career").exists())
        self.assertFalse((self.dst / workspace.MARKER).exists())

    def test_dry_run_writes_nothing(self):
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("career/profile.md", r.stdout)
        self.assertFalse(self.dst.exists())

    def test_bad_source_exits_2(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        r = self.run_cli("--from", str(empty), "--to", str(self.dst))
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.dst.exists())

    def test_existing_workspace_without_conflicts_ok(self):
        workspace.init_root(self.dst)
        marker_before = (self.dst / workspace.MARKER).read_text()
        r = self.run_cli("--from", str(self.repo), "--to", str(self.dst))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.dst / workspace.MARKER).read_text(), marker_before)


if __name__ == "__main__":
    unittest.main()
