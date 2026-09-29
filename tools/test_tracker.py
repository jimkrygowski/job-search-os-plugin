import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tracker  # noqa: E402
import workspace  # noqa: E402


class TrackerLibTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        workspace.init_root(".")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_read_table_missing_file_returns_no_rows(self):
        self.assertEqual(tracker.read_table(tracker.active_path()), [])

    def test_write_then_read_round_trip(self):
        rows = [{
            "Company": "Acme", "Role": "VP Engineering", "Stage": "Screen",
            "Last Activity": "2026-08-19", "Next Action": "Follow up",
            "Next Action Date": "2026-08-26", "Source": "Referral",
        }]
        tracker.write_table(tracker.active_path(), rows, tracker.ACTIVE_TITLE)
        self.assertEqual(tracker.read_table(tracker.active_path()), rows)

    def test_round_trip_survives_pipe_and_comma_in_cell(self):
        rows = [{
            "Company": "Bed | Bath & Beyond, Inc.", "Role": "CTO",
            "Stage": "Identified", "Last Activity": "2026-08-20",
            "Next Action": "", "Next Action Date": "", "Source": "",
        }]
        tracker.write_table(tracker.active_path(), rows, tracker.ACTIVE_TITLE)
        self.assertEqual(tracker.read_table(tracker.active_path()), rows)

    def test_no_column_alignment_padding(self):
        rows = [
            {"Company": "A", "Role": "Short", "Stage": "S",
             "Last Activity": "2026-01-01", "Next Action": "",
             "Next Action Date": ""},
            {"Company": "A Very Long Company Name Inc",
             "Role": "Longer Role Title", "Stage": "S",
             "Last Activity": "2026-01-01", "Next Action": "",
             "Next Action Date": ""},
        ]
        text = tracker.serialize_table(rows, tracker.ACTIVE_TITLE)
        short_row_line = [l for l in text.splitlines() if l.startswith("| A |")]
        self.assertEqual(short_row_line, ["| A | Short | S | 2026-01-01 |  |  |  |"])


class TrackerCLITest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        workspace.init_root(".")
        self.tracker_py = str(Path(__file__).parent / "tracker.py")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, self.tracker_py, *args],
            capture_output=True, text=True,
        )

    def test_add_then_list_shows_new_row(self):
        result = self.run_cli(
            "add", "Acme", "VP Engineering",
            "--stage", "Identified", "--source", "Other", "--next-action-date", "2026-08-26",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("list")
        self.assertIn("Acme", result.stdout)
        self.assertIn("VP Engineering", result.stdout)

    def test_add_duplicate_fails(self):
        self.run_cli("add", "Acme", "VP Engineering", "--stage", "Identified", "--source", "Other")
        result = self.run_cli("add", "Acme", "VP Engineering", "--stage", "Identified", "--source", "Other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_add_duplicate_fails_on_slug_collision_not_just_exact_match(self):
        # "VP Engineering" and "VP  Engineering" resolve to the identical
        # opportunity folder (opportunity_path collapses the whitespace),
        # so they must be rejected as the same opportunity here too —
        # otherwise the tracker ends up with two active rows pointing at
        # one folder.
        self.run_cli("add", "Acme", "VP Engineering", "--stage", "Identified", "--source", "Other")
        result = self.run_cli("add", "Acme", "VP  Engineering", "--stage", "Identified", "--source", "Other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_update_status_on_missing_row_fails(self):
        result = self.run_cli("update-status", "Nope", "Nowhere", "--stage", "Applied")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)

    def test_update_status_changes_stage_and_next_action(self):
        self.run_cli("add", "Acme", "VP Engineering", "--stage", "Identified", "--source", "Other")
        self.run_cli(
            "update-status", "Acme", "VP Engineering",
            "--stage", "Screen", "--next-action", "Call",
            "--next-action-date", "2026-09-01",
        )
        result = self.run_cli("list")
        self.assertIn("Screen", result.stdout)
        self.assertIn("Call", result.stdout)

    def test_record_event_updates_next_action_without_changing_stage(self):
        self.run_cli("add", "Acme", "VP Engineering", "--stage", "Screen", "--source", "Other")
        self.run_cli(
            "record-event", "Acme", "VP Engineering",
            "--event", "Onsite interview", "--date", "2026-09-05",
        )
        result = self.run_cli("list")
        self.assertIn("Screen", result.stdout)
        self.assertIn("Onsite interview", result.stdout)

    def test_close_moves_row_to_closed_and_writes_notes(self):
        self.run_cli("add", "Acme", "VP Engineering", "--stage", "Screen", "--source", "Other")
        result = self.run_cli(
            "close", "Acme", "VP Engineering",
            "--reason", "Role was put on hold", "--outcome", "Withdrew",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        active = self.run_cli("list")
        self.assertNotIn("Acme", active.stdout)

        closed = self.run_cli("list", "--closed")
        self.assertIn("Acme", closed.stdout)

        notes = Path("opportunity/acme/vp_engineering/notes.md").read_text()
        self.assertIn("Role was put on hold", notes)

    def test_close_missing_row_fails(self):
        result = self.run_cli("close", "Nope", "Nowhere", "--reason", "n/a", "--outcome", "Rejected")
        self.assertNotEqual(result.returncode, 0)


class TrackerLockingTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        workspace.init_root(".")
        self.tracker_py = str(Path(__file__).parent / "tracker.py")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, self.tracker_py, *args],
            capture_output=True, text=True,
        )

    def test_concurrent_record_event_calls_do_not_clobber_each_other(self):
        # Reproduces the race a reviewer flagged: morning-scan runs tiers in
        # parallel and can call record-event once per calendar event found.
        # Without locking, concurrent read-modify-write cycles on tracker.md
        # silently drop all but the last writer's update.
        companies = [f"Company{i}" for i in range(8)]
        for c in companies:
            result = self.run_cli("add", c, "Role", "--stage", "Screen", "--source", "Other")
            self.assertEqual(result.returncode, 0, result.stderr)

        def record(c):
            return subprocess.run(
                [sys.executable, self.tracker_py, "record-event", c, "Role",
                 "--event", f"Interview for {c}", "--date", "2026-09-01"],
                capture_output=True, text=True,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(companies)) as pool:
            results = list(pool.map(record, companies))

        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)

        rows = tracker.read_table(tracker.active_path())
        self.assertEqual(len(rows), len(companies))
        for c in companies:
            row = tracker.find_row(rows, c, "Role")
            self.assertIsNotNone(row, f"{c} missing from tracker.md after concurrent writes")
            self.assertEqual(row["Next Action"], f"Interview for {c}")

    def test_lock_file_does_not_leak_after_normal_operation(self):
        self.run_cli("add", "Acme", "VP Engineering", "--stage", "Screen", "--source", "Other")
        self.assertFalse(tracker.lock_path().exists())

    def test_locked_times_out_when_lock_file_already_held(self):
        tracker.lock_path().parent.mkdir(parents=True, exist_ok=True)
        tracker.lock_path().touch()
        with self.assertRaises(SystemExit):
            with tracker.locked(timeout=0.2):
                pass


class SlugifyTest(unittest.TestCase):
    def test_lowercases_and_replaces_spaces(self):
        self.assertEqual(tracker.slugify("VP Engineering"), "vp_engineering")

    def test_collapses_runs_of_punctuation_and_whitespace(self):
        self.assertEqual(tracker.slugify("VP,  Engineering!!"), "vp_engineering")

    def test_inconsistent_spacing_and_casing_collide_on_purpose(self):
        # This is the whole point: two skills typing the same role
        # differently must still land in the same folder.
        self.assertEqual(tracker.slugify("VP Engineering"), tracker.slugify("VP  Engineering"))
        self.assertEqual(tracker.slugify("VP Engineering"), tracker.slugify("vp engineering"))

    def test_strips_leading_and_trailing_punctuation(self):
        self.assertEqual(tracker.slugify("  Acme, Inc.  "), "acme_inc")

    def test_empty_or_all_punctuation_falls_back_to_unnamed(self):
        self.assertEqual(tracker.slugify("   "), "unnamed")
        self.assertEqual(tracker.slugify("---"), "unnamed")


class OpportunityPathTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        workspace.init_root(".")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_combines_slugified_company_and_role_under_workspace(self):
        self.assertEqual(
            tracker.opportunity_path("Bed | Bath & Beyond, Inc.", "VP Engineering"),
            Path("opportunity/bed_bath_beyond_inc/vp_engineering").resolve(),
        )

    def test_cli_prints_the_same_path_the_library_function_computes(self):
        tmpdir = tempfile.TemporaryDirectory()
        cwd = os.getcwd()
        os.chdir(tmpdir.name)
        workspace.init_root(".")
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "tracker.py"),
                 "opportunity-path", "Ledgerline", "VP Engineering"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(tracker.opportunity_path("Ledgerline", "VP Engineering")),
            )
        finally:
            os.chdir(cwd)
            tmpdir.cleanup()


class WorkspaceResolutionTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve() / "my search"
        workspace.init_root(self.root)
        self.script = str(Path(__file__).parent / "tracker.py")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def run_cli(self, cwd, *args):
        return subprocess.run([sys.executable, self.script, *args],
                              cwd=cwd, capture_output=True, text=True)

    def test_add_from_nested_subdir_writes_workspace_root_tracker(self):
        nested = self.root / "opportunity" / "acme" / "vp"
        nested.mkdir(parents=True)
        r = self.run_cli(nested, "add", "Acme", "VP", "--stage", "Identified", "--source", "Other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "tracker.md").exists())
        self.assertFalse((nested / "tracker.md").exists())

    def test_outside_workspace_exits_2_and_writes_nothing(self):
        outside = Path(self._tmpdir.name).resolve() / "elsewhere"
        outside.mkdir()
        r = self.run_cli(outside, "add", "Acme", "VP", "--stage", "Identified", "--source", "Other")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not inside a job-search-os workspace", r.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_opportunity_path_is_absolute_under_root(self):
        r = self.run_cli(self.root, "opportunity-path", "Acme Inc.", "VP Eng")
        self.assertEqual(Path(r.stdout.strip()), self.root / "opportunity" / "acme_inc" / "vp_eng")


class _CLIBase(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        workspace.init_root(".")
        self.tracker_py = str(Path(__file__).parent / "tracker.py")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, self.tracker_py, *args],
            capture_output=True, text=True,
        )

    def ok(self, *args):
        r = self.run_cli(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def events(self):
        path = Path("tracker_events.jsonl")
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class StageValidationTest(_CLIBase):
    def test_legacy_stage_is_stored_as_canonical(self):
        self.ok("add", "Acme", "VP", "--stage", "Screen", "--source", "Referral")
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual(row["Stage"], "Recruiter Screen")

    def test_canonical_stage_matching_ignores_case(self):
        self.ok("add", "Acme", "VP", "--stage", "interview loop", "--source", "Referral")
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual(row["Stage"], "Interview Loop")

    def test_unknown_stage_is_rejected_with_valid_list(self):
        r = self.run_cli("add", "Acme", "VP", "--stage", "Vibes", "--source", "Referral")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Recruiter Screen", r.stderr)
        self.assertFalse(Path("tracker.md").exists())

    def test_add_requires_source(self):
        r = self.run_cli("add", "Acme", "VP", "--stage", "Applied")
        self.assertNotEqual(r.returncode, 0)

    def test_add_rejects_unknown_source(self):
        r = self.run_cli("add", "Acme", "VP", "--stage", "Applied", "--source", "Carrier pigeon")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Warm Intro", r.stderr)

    def test_update_status_rejects_outcome_and_points_to_close(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        r = self.run_cli("update-status", "Acme", "VP", "--stage", "Rejected")
        self.assertEqual(r.returncode, 1)
        self.assertIn("close", r.stderr)

    def test_close_requires_valid_outcome(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        r = self.run_cli("close", "Acme", "VP", "--reason", "x", "--outcome", "Sad")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Ghosted", r.stderr)
        r = self.run_cli("close", "Acme", "VP", "--reason", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_close_records_outcome_column(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        self.ok("close", "Acme", "VP", "--reason", "no reply", "--outcome", "ghosted")
        rows = tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)
        self.assertEqual(rows[0]["Outcome"], "Ghosted")
        self.assertEqual(rows[0]["Stage"], "Applied")


class LegacyTableTest(_CLIBase):
    V01_ACTIVE = (
        "# Active Opportunities\n\n"
        "| Company | Role | Stage | Last Activity | Next Action | Next Action Date |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Acme | VP | Applied | 2026-08-01 |  |  |\n"
    )
    V01_CLOSED = (
        "# Closed Opportunities\n\n"
        "| Company | Role | Stage | Last Activity | Next Action | Next Action Date |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Old | CTO | Screen | 2026-07-01 |  |  |\n"
    )

    def test_v01_table_loads_with_blank_source(self):
        Path("tracker.md").write_text(self.V01_ACTIVE)
        rows = tracker.read_table(tracker.active_path())
        self.assertEqual(rows[0]["Source"], "")
        self.assertEqual(rows[0]["Stage"], "Applied")

    def test_v01_table_gains_source_column_on_next_write(self):
        Path("tracker.md").write_text(self.V01_ACTIVE)
        self.ok("update-status", "Acme", "VP", "--stage", "Recruiter Screen")
        header = [l for l in Path("tracker.md").read_text().splitlines() if l.startswith("|")][0]
        self.assertIn("| Source |", header)

    def test_v01_closed_table_upgraded_by_close(self):
        Path("tracker.md").write_text(self.V01_ACTIVE)
        Path("tracker_closed.md").write_text(self.V01_CLOSED)
        self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", "Rejected")
        rows = tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)
        self.assertEqual([r["Company"] for r in rows], ["Old", "Acme"])
        self.assertEqual(rows[0]["Outcome"], "")
        self.assertEqual(rows[1]["Outcome"], "Rejected")

    def test_row_with_wrong_column_count_is_still_an_error(self):
        Path("tracker.md").write_text(self.V01_ACTIVE + "| Only | three | cells |\n")
        with self.assertRaises(ValueError):
            tracker.read_table(tracker.active_path())


class EventLogTest(_CLIBase):
    def test_add_logs_add_event(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        [e] = self.events()
        self.assertEqual(e["type"], "add")
        self.assertEqual(e["to"], "Applied")
        self.assertEqual(e["source"], "Referral")
        self.assertIs(e["inferred"], False)
        self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_stage_change_logs_from_and_to(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        self.ok("update-status", "Acme", "VP", "--stage", "Hiring Manager")
        e = self.events()[-1]
        self.assertEqual((e["type"], e["from"], e["to"]), ("stage", "Applied", "Hiring Manager"))

    def test_unchanged_stage_and_record_event_log_nothing(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        self.ok("update-status", "Acme", "VP", "--stage", "Applied", "--next-action", "wait")
        self.ok("record-event", "Acme", "VP", "--event", "Call", "--date", "2026-10-01")
        self.assertEqual(len(self.events()), 1)

    def test_close_logs_last_stage_and_outcome(self):
        self.ok("add", "Acme", "VP", "--stage", "Offer", "--source", "Referral")
        self.ok("close", "Acme", "VP", "--reason", "took it", "--outcome", "Accepted")
        e = self.events()[-1]
        self.assertEqual((e["type"], e["from"], e["outcome"]), ("close", "Offer", "Accepted"))

    def test_set_source_updates_row_and_logs(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Other")
        self.ok("set-source", "Acme", "VP", "--source", "Warm Intro")
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual(row["Source"], "Warm Intro")
        e = self.events()[-1]
        self.assertEqual((e["type"], e["source"]), ("source", "Warm Intro"))

    def test_set_source_works_on_closed_rows(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Other")
        self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", "Rejected")
        self.ok("set-source", "Acme", "VP", "--source", "Job Alert")
        rows = tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)
        self.assertEqual(rows[0]["Source"], "Job Alert")

    def test_awkward_names_round_trip_through_log(self):
        name = 'Bed | Bath, "Inc" \u00e9'
        self.ok("add", name, "VP", "--stage", "Applied", "--source", "Other")
        self.assertEqual(self.events()[0]["company"], name)

    def test_failed_command_logs_nothing(self):
        self.run_cli("add", "Acme", "VP", "--stage", "Nope", "--source", "Other")
        self.run_cli("update-status", "Ghost", "Co", "--stage", "Applied")
        self.assertEqual(self.events(), [])


class ExportTest(_CLIBase):
    def export(self):
        r = self.ok("export", "--json")
        return json.loads(r.stdout)

    def test_export_shape_and_vocabulary(self):
        self.ok("add", "Acme Inc.", "VP Eng", "--stage", "Applied", "--source", "Referral",
                "--next-action", "ping", "--next-action-date", "2026-10-01")
        data = self.export()
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["stages"], tracker.STAGES)
        self.assertEqual(data["outcomes"], tracker.OUTCOMES)
        self.assertEqual(data["sources"], tracker.SOURCES)
        [row] = data["active"]
        self.assertEqual(row, {
            "company": "Acme Inc.", "role": "VP Eng", "slug": "acme_inc/vp_eng",
            "stage": "Applied", "source": "Referral", "last_activity": tracker.today(),
            "next_action": "ping", "next_action_date": "2026-10-01",
        })
        self.assertEqual(data["closed"], [])
        self.assertEqual([e["type"] for e in data["events"]], ["add"])
        self.assertEqual(data["warnings"], [])

    def test_closed_rows_carry_outcome(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", "Rejected")
        [row] = self.export()["closed"]
        self.assertEqual(row["outcome"], "Rejected")

    def test_legacy_stage_exported_as_canonical_and_unmapped_warned(self):
        Path("tracker.md").write_text(LegacyTableTest.V01_ACTIVE.replace(
            "| Acme | VP | Applied |", "| Acme | VP | Phone Screen |"
        ) + "| Beta | CTO | Networking | 2026-08-02 |  |  |\n")
        data = self.export()
        self.assertEqual([r["stage"] for r in data["active"]], ["Recruiter Screen", "Networking"])
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("Networking", data["warnings"][0])

    def test_malformed_event_lines_are_warnings_not_errors(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Referral")
        with Path("tracker_events.jsonl").open("a") as f:
            f.write("{not json\n")
            f.write('{"ts": "2026-01-01T00:00:00"}\n')
        data = self.export()
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(len(data["warnings"]), 2)
        self.assertIn("line 2", data["warnings"][0])

    def test_malformed_table_is_a_hard_error(self):
        Path("tracker.md").write_text(LegacyTableTest.V01_ACTIVE + "| a | b |\n")
        r = self.run_cli("export", "--json")
        self.assertNotEqual(r.returncode, 0)


FIXTURE = Path(__file__).parent.parent / "dashboard" / "fixtures"


class ExportFixtureContractTest(unittest.TestCase):
    """dashboard/fixtures/export.json is the contract the TypeScript tests
    also read: if export's output changes, both sides must be updated."""

    def test_fixture_export_matches_golden(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            shutil.copytree(FIXTURE / "workspace", ws)
            workspace.init_root(ws)
            r = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "tracker.py"), "export", "--json"],
                cwd=ws, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), json.loads((FIXTURE / "export.json").read_text()))


class BackfillTest(_CLIBase):
    def backfill(self, entries):
        Path("bf.json").write_text(json.dumps(entries))
        return self.run_cli("backfill", "--events-file", "bf.json")

    def setUp(self):
        super().setUp()
        Path("tracker.md").write_text(LegacyTableTest.V01_ACTIVE)

    ENTRIES = [
        {"company": "Acme", "role": "VP", "type": "add", "ts": "2026-07-01T09:00:00", "to": "Identified"},
        {"company": "Acme", "role": "VP", "type": "stage", "ts": "2026-07-03T09:00:00",
         "from": "Identified", "to": "Applied"},
        {"company": "Acme", "role": "VP", "type": "source", "ts": "2026-07-01T09:00:00", "source": "Job Alert"},
    ]

    def test_backfill_writes_inferred_events(self):
        r = self.backfill(self.ENTRIES)
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self.events()
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e["inferred"] is True for e in events))
        self.assertEqual(events[1]["ts"], "2026-07-03T09:00:00")

    def test_backfill_is_idempotent(self):
        self.backfill(self.ENTRIES)
        r = self.backfill(self.ENTRIES)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.events()), 3)
        self.assertIn("0 added", r.stdout)

    def test_backfill_dedups_against_same_day_real_event(self):
        self.ok("update-status", "Acme", "VP", "--stage", "Recruiter Screen")
        today = tracker.today()
        r = self.backfill([{"company": "Acme", "role": "VP", "type": "stage",
                            "ts": today + "T23:59:00", "from": "Applied", "to": "Recruiter Screen"}])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.events()), 1)

    def test_source_fills_blank_but_never_overwrites(self):
        self.backfill(self.ENTRIES)
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual(row["Source"], "Job Alert")
        self.ok("set-source", "Acme", "VP", "--source", "Referral")
        self.backfill([{"company": "Acme", "role": "VP", "type": "source",
                        "ts": "2026-07-02T00:00:00", "source": "Other"}])
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual(row["Source"], "Referral")

    def test_invalid_entry_rejects_whole_batch(self):
        bad = self.ENTRIES + [{"company": "Acme", "role": "VP", "type": "stage",
                               "ts": "2026-07-05T00:00:00", "from": "Applied", "to": "Vibes"}]
        r = self.backfill(bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Vibes", r.stderr)
        self.assertEqual(self.events(), [])

    def test_unknown_opportunity_rejects_batch(self):
        r = self.backfill([{"company": "Nobody", "role": "X", "type": "add",
                            "ts": "2026-07-01T00:00:00", "to": "Applied"}])
        self.assertEqual(r.returncode, 1)
        self.assertIn("Nobody", r.stderr)

    def test_bad_timestamp_rejects_batch(self):
        r = self.backfill([{"company": "Acme", "role": "VP", "type": "add",
                            "ts": "sometime in July", "to": "Applied"}])
        self.assertEqual(r.returncode, 1)

    def test_close_entry_needs_valid_outcome(self):
        r = self.backfill([{"company": "Acme", "role": "VP", "type": "close",
                            "ts": "2026-07-09T00:00:00", "from": "Applied", "outcome": "Meh"}])
        self.assertEqual(r.returncode, 1)


class LegacyStageEventTest(_CLIBase):
    def setUp(self):
        super().setUp()
        Path("tracker.md").write_text(LegacyTableTest.V01_ACTIVE.replace(
            "| Acme | VP | Applied |", "| Acme | VP | Screen |"))

    def test_normalizing_a_legacy_stage_is_not_a_stage_change(self):
        self.ok("update-status", "Acme", "VP", "--stage", "Recruiter Screen", "--next-action", "wait")
        self.assertEqual(self.events(), [])

    def test_events_record_canonical_from_stage(self):
        self.ok("update-status", "Acme", "VP", "--stage", "Hiring Manager")
        self.assertEqual(self.events()[-1]["from"], "Recruiter Screen")
        self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", "Rejected")
        self.assertEqual(self.events()[-1]["from"], "Hiring Manager")

    def test_close_logs_canonical_from_for_legacy_row(self):
        self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", "Withdrew")
        self.assertEqual(self.events()[-1]["from"], "Recruiter Screen")


class WorkspaceSourcesTest(_CLIBase):
    CUSTOM = ["Referral", "LinkedIn Job Alert", "ZenSearch Job Alert", "Other"]

    def configure(self, sources):
        marker = Path(workspace.MARKER)
        cfg = json.loads(marker.read_text())
        cfg["sources"] = sources
        marker.write_text(json.dumps(cfg))

    def test_default_sources_without_config(self):
        self.assertEqual(json.loads(self.ok("export", "--json").stdout)["sources"], tracker.SOURCES)

    def test_workspace_sources_are_exported_and_enforced(self):
        self.configure(self.CUSTOM)
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "linkedin job alert")
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual(row["Source"], "LinkedIn Job Alert")
        r = self.run_cli("add", "Beta", "VP", "--stage", "Applied", "--source", "Job Alert")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ZenSearch Job Alert", r.stderr)
        self.assertEqual(json.loads(self.ok("export", "--json").stdout)["sources"], self.CUSTOM)

    def test_set_source_and_backfill_use_workspace_sources(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Other")
        self.configure(self.CUSTOM)
        self.ok("set-source", "Acme", "VP", "--source", "ZenSearch Job Alert")
        Path("bf.json").write_text(json.dumps([{"company": "Acme", "role": "VP", "type": "source",
                                                 "ts": "2026-07-01T00:00:00", "source": "Job Alert"}]))
        self.assertEqual(self.run_cli("backfill", "--events-file", "bf.json").returncode, 1)

    def test_rows_with_sources_outside_the_list_are_warned(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Job Alert")
        self.configure(self.CUSTOM)
        warnings = json.loads(self.ok("export", "--json").stdout)["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Job Alert", warnings[0])

    def test_invalid_sources_config_is_an_error(self):
        for bad in ([], ["A", "a"], ["A", ""], "LinkedIn", [1, 2]):
            self.configure(bad)
            r = self.run_cli("export", "--json")
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("sources", r.stderr)


class AmendClosedTest(_CLIBase):
    def setUp(self):
        super().setUp()
        Path("tracker_closed.md").write_text(LegacyTableTest.V01_CLOSED)

    def closed(self):
        return tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)

    def test_sets_stage_and_outcome(self):
        self.ok("amend-closed", "Old", "CTO", "--stage", "hiring manager", "--outcome", "Withdrew")
        [row] = self.closed()
        self.assertEqual((row["Stage"], row["Outcome"]), ("Hiring Manager", "Withdrew"))
        self.assertEqual(row["Last Activity"], "2026-07-01")

    def test_each_field_is_optional_but_one_is_required(self):
        self.ok("amend-closed", "Old", "CTO", "--outcome", "Rejected")
        self.assertEqual(self.closed()[0]["Stage"], "Screen")
        self.assertNotEqual(self.run_cli("amend-closed", "Old", "CTO").returncode, 0)

    def test_validates_values_and_row(self):
        self.assertEqual(self.run_cli("amend-closed", "Old", "CTO", "--stage", "Vibes").returncode, 1)
        self.assertEqual(self.run_cli("amend-closed", "Old", "CTO", "--outcome", "Meh").returncode, 1)
        self.assertEqual(self.run_cli("amend-closed", "Nope", "X", "--outcome", "Rejected").returncode, 1)
        self.assertEqual(self.closed()[0]["Outcome"], "")

    def test_amends_most_recent_closed_row_for_reopened_opportunities(self):
        self.ok("add", "Old", "CTO", "--stage", "Applied", "--source", "Other")
        self.ok("close", "Old", "CTO", "--reason", "again", "--outcome", "Ghosted")
        self.ok("amend-closed", "Old", "CTO", "--outcome", "Rejected")
        self.assertEqual([r["Outcome"] for r in self.closed()], ["", "Rejected"])

    def test_writes_no_event(self):
        self.ok("amend-closed", "Old", "CTO", "--outcome", "Rejected")
        self.assertEqual(self.events(), [])


class RemoveTest(_CLIBase):
    def test_removes_active_row_notes_reason_and_logs(self):
        self.ok("add", "Rich", "Networking", "--stage", "Identified", "--source", "Other")
        self.ok("remove", "Rich", "Networking", "--reason", "networking contact, moved to networking.md")
        self.assertEqual(tracker.read_table(tracker.active_path()), [])
        self.assertEqual(tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS), [])
        notes = Path("opportunity/rich/networking/notes.md").read_text()
        self.assertIn("Removed from tracker", notes)
        self.assertIn("moved to networking.md", notes)
        self.assertEqual(self.events()[-1]["type"], "remove")

    def test_removed_opportunity_is_not_an_orphan_in_export(self):
        self.ok("add", "Rich", "Networking", "--stage", "Identified", "--source", "Other")
        self.ok("remove", "Rich", "Networking", "--reason", "r")
        self.assertEqual(json.loads(self.ok("export", "--json").stdout)["warnings"], [])

    def test_remove_requires_reason_and_existing_row(self):
        self.assertNotEqual(self.run_cli("remove", "Nope", "X").returncode, 0)
        self.assertEqual(self.run_cli("remove", "Nope", "X", "--reason", "r").returncode, 1)


class RepeatApplicationTest(_CLIBase):
    def test_set_source_edits_the_most_recent_closed_row(self):
        for outcome in ("Rejected", "Ghosted"):
            self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Other")
            self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", outcome)
        self.ok("set-source", "Acme", "VP", "--source", "Referral")
        rows = tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)
        self.assertEqual([(r["Outcome"], r["Source"]) for r in rows],
                         [("Rejected", "Other"), ("Ghosted", "Referral")])

    def test_set_source_prefers_the_active_row(self):
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Other")
        self.ok("close", "Acme", "VP", "--reason", "r", "--outcome", "Rejected")
        self.ok("add", "Acme", "VP", "--stage", "Applied", "--source", "Other")
        self.ok("set-source", "Acme", "VP", "--source", "Referral")
        active = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        closed = tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)
        self.assertEqual((active["Source"], closed[0]["Source"]), ("Referral", "Other"))


class CleanupSupportTest(_CLIBase):
    def test_passed_and_role_filled_are_outcomes(self):
        for outcome in ("Passed", "Role Filled"):
            self.ok("add", outcome, "VP", "--stage", "Identified", "--source", "Other")
            self.ok("close", outcome, "VP", "--reason", "r", "--outcome", outcome.lower())
        rows = tracker.read_table(tracker.closed_path(), tracker.CLOSED_COLUMNS)
        self.assertEqual([r["Outcome"] for r in rows], ["Passed", "Role Filled"])

    def test_correction_fixes_stage_without_event_or_activity_change(self):
        Path("tracker.md").write_text(LegacyTableTest.V01_ACTIVE.replace(
            "| Acme | VP | Applied |", "| Acme | VP | On Hold — waiting on internal candidate |"))
        self.ok("update-status", "Acme", "VP", "--stage", "Recruiter Screen", "--correction")
        row = tracker.find_row(tracker.read_table(tracker.active_path()), "Acme", "VP")
        self.assertEqual((row["Stage"], row["Last Activity"]), ("Recruiter Screen", "2026-08-01"))
        self.assertEqual(self.events(), [])

    def test_close_date_backdates_event_and_note(self):
        self.ok("add", "Acme", "VP", "--stage", "Identified", "--source", "Other")
        self.ok("close", "Acme", "VP", "--reason", "comp", "--outcome", "Passed", "--date", "2026-09-02")
        e = self.events()[-1]
        self.assertEqual((e["type"], e["ts"]), ("close", "2026-09-02T00:00:00"))
        notes = Path("opportunity/acme/vp/notes.md").read_text()
        self.assertIn("**Closed (2026-09-02):** Passed — comp", notes)

    def test_close_date_must_be_a_date(self):
        self.ok("add", "Acme", "VP", "--stage", "Identified", "--source", "Other")
        r = self.run_cli("close", "Acme", "VP", "--reason", "r", "--outcome", "Passed", "--date", "last week")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(tracker.read_table(tracker.active_path())), 1)


if __name__ == "__main__":
    unittest.main()
