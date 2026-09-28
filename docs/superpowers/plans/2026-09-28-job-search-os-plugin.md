# job-search-os Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the job-search-os skills/tools into a self-contained Claude Code plugin whose code never co-resides with user state; state lives in a marker-identified workspace.

**Architecture:** The repo root is the plugin (and its own one-entry marketplace). A new `tools/workspace.py` finds the workspace by walking up from cwd to `.job-search-os.json`; every tool resolves state paths from it. Two exec-form hooks (SessionStart → persona + bootstrap note; PreToolUse → deny Gmail send) act only inside a workspace. Skills call tools via `${CLAUDE_PLUGIN_ROOT}`.

**Tech Stack:** Python 3 stdlib (unittest), Claude Code plugin manifest/hooks, Markdown skills.

**Spec:** `docs/superpowers/specs/2026-09-28-job-search-os-plugin-design.md`

**Source repo (read-only):** `SRC=~/code/job-search-os` at commit `9ef2456`. Never modify it.

## Global Constraints

- Plugin name `job-search-os` (plugin.json `name`, marketplace entry `name`, and marketplace `name`); version `0.1.0`.
- Stdlib only — no pip dependencies, in tools or tests.
- No `bin/` directory.
- Hooks use exec form: `"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/tools/<x>.py"]`.
- Skills/commands/guidance reference tools only as `${CLAUDE_PLUGIN_ROOT}/tools/<x>.py`; never `state/...`.
- Marker file name `.job-search-os.json`, content `{"schema": 1, "created": "<YYYY-MM-DD>"}`.
- Workspace layout is flat: `career/`, `opportunity/`, `tracker.md`, `tracker_closed.md`, `.tracker.lock` at workspace root.
- Tools resolve paths at call time (never at import time).
- Port-only: skill behavior unchanged except items the spec lists.
- License: PolyForm Noncommercial 1.0.0 (copy `$SRC/LICENSE`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push or create the GitHub repo without explicit user confirmation.

## Review Focus

1. Claude has `cd`'d into an opportunity subfolder, then runs `tracker.py` — must still resolve the workspace root, not create a new tracker in the subfolder (test in Task 3).
2. Session started from a subdirectory of a workspace — both hooks must still activate (tests in Tasks 5 and 6).
3. Hook given empty or malformed stdin — SessionStart still works from `CLAUDE_PROJECT_DIR`/cwd; guard_send denies (fail closed) (tests in Tasks 5 and 6).
4. User passes the old repo's `state/` directory itself (not the repo root) to migrate — should work, not error (test in Task 7).
5. Workspace or plugin path containing spaces — tools invoked via subprocess still work (test in Task 3 uses a temp dir with a space).

---

## File Structure

```
.claude-plugin/plugin.json            Task 1
.claude-plugin/marketplace.json       Task 1
LICENSE, .gitignore, CLAUDE.md        Task 1
tools/run_tests.sh                    Task 1 (unit tests), Task 8 (static check)
tools/workspace.py, test_workspace.py Task 2
tools/tracker.py, test_tracker.py     Task 3
tools/score_table.py, check_bootstrap_state.py, gmail_extract.py, option_value.py + tests   Task 4
guidance/persona.md, tools/session_start.py, test_session_start.py   Task 5
hooks/hooks.json, tools/guard_send.py, test_guard_send.py            Task 6
tools/migrate.py, test_migrate.py     Task 7
skills/**, commands/summarize-call.md Task 8
README.md                             Task 9
(verification + tag)                  Task 10
(publish, gated)                      Task 11
```

---

### Task 1: Plugin scaffold

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `LICENSE`, `CLAUDE.md`, `tools/run_tests.sh`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `tools/run_tests.sh` (runs `python3 -m unittest discover -s tools -p 'test_*.py'` from repo root).

- [ ] **Step 1: Write manifests**

`.claude-plugin/plugin.json`:
```json
{
  "name": "job-search-os",
  "version": "0.1.0",
  "description": "An agentic job search system: candidate profile, target-role trajectory, opportunity scoring, resume tailoring, company research, interview prep/review, evidence-graded career coaching, offer negotiation, and a pipeline tracker. State lives in your own workspace folder, never in the plugin.",
  "author": { "name": "Jim Krygowski", "url": "https://linkedin.com/in/jimkrygowski" },
  "homepage": "https://github.com/jimkrygowski/job-search-os-plugin",
  "repository": "https://github.com/jimkrygowski/job-search-os-plugin",
  "license": "PolyForm-Noncommercial-1.0.0",
  "keywords": ["job-search", "career", "resume", "interview", "negotiation"]
}
```

`.claude-plugin/marketplace.json`:
```json
{
  "name": "job-search-os",
  "description": "Marketplace for the job-search-os plugin",
  "owner": { "name": "Jim Krygowski" },
  "plugins": [
    {
      "name": "job-search-os",
      "source": "./",
      "description": "An agentic job search system with state kept in your own workspace."
    }
  ]
}
```

- [ ] **Step 2: License, gitignore, dev CLAUDE.md, test runner**

```bash
cp ~/code/job-search-os/LICENSE LICENSE
```

`.gitignore` (replace):
```
__pycache__/
*.pyc
.DS_Store
.obsidian/
.job-search-os.json
```
(The last line prevents anyone from accidentally turning the plugin repo itself into a workspace.)

`CLAUDE.md`:
```markdown
# Developing job-search-os (the plugin)

This repo is the plugin's code. It must never contain user state.

- Plugin root = repo root. Manifest: `.claude-plugin/plugin.json`; the repo
  is also its own marketplace (`.claude-plugin/marketplace.json`, source `./`).
- User state lives in a *workspace*: any folder with `.job-search-os.json`.
  Tools find it via `tools/workspace.py` (walks up from cwd). Never write
  state anywhere else, and never into `${CLAUDE_PLUGIN_ROOT}`.
- Skills call tools as `python3 "${CLAUDE_PLUGIN_ROOT}/tools/<x>.py"`.
  Never reference `state/...` or bare `tools/...` in skills — `tools/run_tests.sh`
  enforces this.
- The persona/guardrails users see live in `guidance/persona.md`, injected by
  the SessionStart hook (`tools/session_start.py`) only inside a workspace.
- Tools and tests are stdlib only. Run everything with `tools/run_tests.sh`.
- Validate the manifest with `claude plugin validate .`; try it live with
  `claude --plugin-dir /path/to/this/repo` from inside a test workspace.
- `job-search-os` is a public identifier (install id + skill prefix). Don't rename it.
```

`tools/run_tests.sh`:
```sh
#!/bin/sh
set -e
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tools -p 'test_*.py'
```
```bash
chmod +x tools/run_tests.sh
```

- [ ] **Step 3: Validate**

Run: `claude plugin validate .`
Expected: ends with `✔ Validation passed` (warnings about no components are acceptable at this stage; errors are not).

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Scaffold plugin manifest, marketplace, license, dev notes"
```

---

### Task 2: `workspace.py`

**Files:**
- Create: `tools/workspace.py`, `tools/test_workspace.py`

**Interfaces:**
- Produces:
  - `MARKER: str = ".job-search-os.json"`
  - `find_root(start: str | Path | None = None) -> Path | None` — resolved absolute path of nearest ancestor-or-self containing a *file* named MARKER.
  - `require_root() -> Path` — `find_root()` or print error to stderr and `sys.exit(2)`.
  - `init_root(path: str | Path) -> Path` — mkdir -p, write marker if absent, return resolved path.
  - CLI: `workspace.py init [PATH]` (default cwd; prints root), `workspace.py root` (prints root or exits 2).

- [ ] **Step 1: Write failing tests** — `tools/test_workspace.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tools/test_workspace.py -v` — Expected: `ModuleNotFoundError: No module named 'workspace'`.

- [ ] **Step 3: Implement** — `tools/workspace.py`:

```python
#!/usr/bin/env python3
"""Locate (or create) the job-search-os workspace.

A workspace is any directory containing a MARKER file. All personal state
lives there; the plugin's own code never does. Tools find the workspace by
walking up from the current directory, the way git finds .git, so they keep
working if Claude has cd'd into a subfolder such as an opportunity folder.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

MARKER = ".job-search-os.json"
SCHEMA = 1


def find_root(start=None):
    here = Path(start if start is not None else Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / MARKER).is_file():
            return d
    return None


def require_root():
    root = find_root()
    if root is None:
        print(
            f"error: not inside a job-search-os workspace (no {MARKER} found "
            f"from {Path.cwd()} upward). Run the bootstrap skill to create "
            "one, or cd into your workspace.",
            file=sys.stderr,
        )
        sys.exit(2)
    return root


def init_root(path):
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if not marker.exists():
        marker.write_text(json.dumps(
            {"schema": SCHEMA, "created": datetime.date.today().isoformat()},
            indent=2,
        ) + "\n")
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="make PATH (default: cwd) a workspace")
    p_init.add_argument("path", nargs="?", default=".")
    sub.add_parser("root", help="print the current workspace root")
    args = parser.parse_args()
    if args.command == "init":
        print(init_root(args.path))
    else:
        print(require_root())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests** — `python3 -m unittest tools/test_workspace.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit** — `git add tools/workspace.py tools/test_workspace.py && git commit -m "Add workspace discovery (marker walk-up)"`

---

### Task 3: Port `tracker.py`

**Files:**
- Create (copy then modify): `tools/tracker.py`, `tools/test_tracker.py` from `$SRC/tools/`

**Interfaces:**
- Consumes: `workspace.require_root()`, `workspace.init_root()`, `workspace.MARKER`.
- Produces (replacing the old module constants): `state_root() -> Path`, `active_path() -> Path`, `closed_path() -> Path`, `lock_path() -> Path`, `opportunity_path(company, role) -> Path` (now absolute: `state_root()/"opportunity"/slug/slug`). CLI unchanged. `ACTIVE_TITLE`, `CLOSED_TITLE`, `slugify`, `read_table`, `write_table`, `serialize_table`, `locked` unchanged in signature.

- [ ] **Step 1: Copy**

```bash
cp $SRC/tools/tracker.py $SRC/tools/test_tracker.py tools/
```

- [ ] **Step 2: Update tests first**

In `tools/test_tracker.py`:
- Every `setUp` that chdirs into a tempdir: after `os.chdir(...)`, add `workspace.init_root(".")` and add `import workspace  # noqa: E402` next to `import tracker`. The standalone test at ~line 239 that makes its own tmpdir: same.
- Replace `tracker.ACTIVE_PATH` → `tracker.active_path()`, `tracker.LOCK_PATH` → `tracker.lock_path()` (all occurrences).
- Replace `Path("state/opportunity/...")` → `Path("opportunity/...").resolve()` for comparisons of `opportunity_path` output, and `Path("state/opportunity/acme/vp_engineering/notes.md")` → `Path("opportunity/acme/vp_engineering/notes.md")`.
- Replace any script path built from `Path(self._cwd) / "tools" / "tracker.py"` with `str(Path(__file__).parent / "tracker.py")`.
- Rename `test_combines_slugified_company_and_role_under_state` → `test_combines_slugified_company_and_role_under_workspace`.
- Add these tests in a new class at the end:

```python
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
        r = self.run_cli(nested, "add", "Acme", "VP", "--stage", "Identified")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "tracker.md").exists())
        self.assertFalse((nested / "tracker.md").exists())

    def test_outside_workspace_exits_2_and_writes_nothing(self):
        outside = Path(self._tmpdir.name).resolve() / "elsewhere"
        outside.mkdir()
        r = self.run_cli(outside, "add", "Acme", "VP", "--stage", "Identified")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not inside a job-search-os workspace", r.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_opportunity_path_is_absolute_under_root(self):
        r = self.run_cli(self.root, "opportunity-path", "Acme Inc.", "VP Eng")
        self.assertEqual(Path(r.stdout.strip()), self.root / "opportunity" / "acme_inc" / "vp_eng")
```

- [ ] **Step 3: Run to verify failure** — `python3 -m unittest tools/test_tracker.py -v` — Expected: FAIL/ERROR (`AttributeError: module 'tracker' has no attribute 'active_path'`).

- [ ] **Step 4: Modify `tools/tracker.py`**

Replace module docstring's first line with `"""CLI for reading and writing the workspace's tracker.md / tracker_closed.md.` and replace lines 19-25 (the `state/` comment and the four constants) with:

```python
sys.path.insert(0, str(Path(__file__).parent))
import workspace  # noqa: E402

# All personal state lives in the user's workspace (see workspace.py), never
# alongside this code. Paths are resolved per call, not at import time.
ACTIVE_TITLE = "Active Opportunities"
CLOSED_TITLE = "Closed Opportunities"


def state_root() -> Path:
    return workspace.require_root()


def active_path() -> Path:
    return state_root() / "tracker.md"


def closed_path() -> Path:
    return state_root() / "tracker_closed.md"


def lock_path() -> Path:
    return state_root() / ".tracker.lock"
```

(Keep the existing `ACTIVE_TITLE`/`CLOSED_TITLE` lines only once — delete the originals.)

Then:
- `opportunity_path`: `return state_root() / "opportunity" / slugify(company) / slugify(role)`
- `locked()`: replace `STATE_ROOT.mkdir(parents=True, exist_ok=True)` with `lock = lock_path()`; replace every `LOCK_PATH` inside the function with `lock`. Update its docstring's `state/tracker.md / state/tracker_closed.md` → `tracker.md / tracker_closed.md`.
- Replace every `ACTIVE_PATH` → `active_path()` and `CLOSED_PATH` → `closed_path()` in the `cmd_*` functions.
- Grep to confirm: `grep -n "STATE_ROOT\|ACTIVE_PATH\|CLOSED_PATH\|LOCK_PATH\|state/" tools/tracker.py` → no output.

- [ ] **Step 5: Run tests** — `python3 -m unittest tools/test_tracker.py -v` — Expected: all PASS, including the concurrency test.

- [ ] **Step 6: Commit** — `git add tools/tracker.py tools/test_tracker.py tools/workspace.py && git commit -m "Port tracker.py to workspace-relative paths"`

---

### Task 4: Port remaining tools

**Files:**
- Create (copy then modify): `tools/score_table.py`, `tools/check_bootstrap_state.py`, `tools/gmail_extract.py`, `tools/option_value.py`, and their `test_*.py`

**Interfaces:**
- Consumes: `workspace.require_root()`, `workspace.init_root()`.
- Produces: `score_table.trajectory_path() -> Path`; `check_bootstrap_state.bootstrap_note(root: Path) -> str | None` (the note text, or None). `check_bootstrap_state.main()` still prints the hook JSON for the current workspace (used by its own tests).

- [ ] **Step 1: Copy**

```bash
for f in score_table check_bootstrap_state gmail_extract option_value; do
  cp $SRC/tools/$f.py $SRC/tools/test_$f.py tools/
done
```

- [ ] **Step 2: Verbatim tools pass as-is**

Run: `python3 -m unittest tools/test_gmail_extract.py tools/test_option_value.py -v` — Expected: PASS (these have no state paths). If a test builds the script path from cwd, change it to `Path(__file__).parent / "<x>.py"`.

- [ ] **Step 3: Update score_table tests**

In `tools/test_score_table.py`: in the CLI test `setUp` (~line 204): after `os.chdir(...)` add `workspace.init_root(".")`; add `import workspace  # noqa: E402`; `self.script = str(Path(__file__).parent / "score_table.py")`; `traj_dir = Path("career")`; `os.remove("career/trajectory.md")`. Add a test to that class:

```python
    def test_criteria_from_nested_subdir(self):
        nested = Path("opportunity/acme/vp")
        nested.mkdir(parents=True)
        r = subprocess.run([sys.executable, self.script, "criteria"],
                           cwd=nested, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
```

- [ ] **Step 4: Modify score_table.py**

Docstring first line: `state/career/trajectory.md` → `the workspace's career/trajectory.md`. Replace `TRAJECTORY_PATH = Path("state/career/trajectory.md")` with:

```python
sys.path.insert(0, str(Path(__file__).parent))
import workspace  # noqa: E402


def trajectory_path() -> Path:
    return workspace.require_root() / "career" / "trajectory.md"
```

(Place after the `from pathlib import Path` import.) In `_read_trajectory`: `path = trajectory_path()` then use `path` in place of the three `TRAJECTORY_PATH` references.

Run: `python3 -m unittest tools/test_score_table.py -v` — Expected: PASS.

- [ ] **Step 5: Update check_bootstrap_state tests**

In `tools/test_check_bootstrap_state.py`:
- CLI class `setUp` (~line 224): after chdir add `workspace.init_root(".")`; `self.script = str(Path(__file__).parent / "check_bootstrap_state.py")`; add `import workspace`.
- Replace every `"state/career/` → `"career/`.
- Any assertion on note text containing `state/career/` → `career/`.
- Add unit tests for the new function:

```python
class BootstrapNoteTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_workspace_gets_new_user_note(self):
        note = check_bootstrap_state.bootstrap_note(self.root)
        self.assertIn("career/profile.md does not exist", note)
        self.assertIn("bootstrap", note)

    def test_complete_workspace_gets_none(self):
        (self.root / "career").mkdir()
        (self.root / "career/profile.md").write_text(PROFILE_COMPLETE)
        (self.root / "career/trajectory.md").write_text(TRAJECTORY_COMPLETE)
        (self.root / "career/comp_target.md").write_text(COMP_TARGET_COMPLETE)
        self.assertIsNone(check_bootstrap_state.bootstrap_note(self.root))
```

(`PROFILE_COMPLETE`, `TRAJECTORY_COMPLETE`, `COMP_TARGET_COMPLETE` already exist in that test module.)

- [ ] **Step 6: Modify check_bootstrap_state.py**

- Docstring: first line → `"""Bootstrap-completeness check, used by the SessionStart hook (session_start.py).`; `state/career/profile.md` → `career/profile.md` in the workspace.
- Delete the three `*_PATH = Path("state/...")` constants; add after imports:

```python
import sys
sys.path.insert(0, str(Path(__file__).parent))
import workspace  # noqa: E402
```

- Replace `main()` with:

```python
def bootstrap_note(root):
    """The note to inject for the workspace at `root`, or None."""
    root = Path(root)
    profile = root / "career" / "profile.md"
    trajectory = root / "career" / "trajectory.md"
    comp_target = root / "career" / "comp_target.md"

    profile_missing = _missing_sections(profile, PROFILE_REQUIRED_SECTIONS)
    if profile_missing:
        if not profile.exists():
            detail = "does not exist"
        else:
            detail = "is missing: " + ", ".join(profile_missing)
        return (
            f"career/profile.md {detail}. This is a new user who "
            "has not run bootstrap yet (or started it and didn't "
            "finish). Your very first reply this session, before "
            "addressing anything else the user asked, must say so "
            "plainly and offer to run the `bootstrap` skill now."
        )

    trajectory_missing = _missing_sections(trajectory, TRAJECTORY_REQUIRED_SECTIONS)
    comp_target_missing = _missing_sections(comp_target, COMP_TARGET_REQUIRED_SECTIONS)
    if not trajectory_missing and comp_target_missing:
        if not comp_target.exists():
            detail = "doesn't exist yet"
        else:
            detail = "is missing: " + ", ".join(comp_target_missing)
        return (
            f"career/comp_target.md {detail} — offer-negotiator "
            "(comp coaching/benchmarking) won't be able to ground its "
            "advice in your actual walk-away numbers until it's set up. "
            "Mention this and offer to set it up, but address whatever "
            "the user asked first."
        )
    return None


def main():
    note = bootstrap_note(workspace.require_root())
    if note:
        _emit(note)
```

- [ ] **Step 7: Run all tool tests** — `tools/run_tests.sh` — Expected: all PASS. Confirm `grep -rn "state/" tools/*.py` prints nothing.

- [ ] **Step 8: Commit** — `git add tools && git commit -m "Port score_table, check_bootstrap_state, gmail_extract, option_value"`

---

### Task 5: Persona + SessionStart hook

**Files:**
- Create: `guidance/persona.md`, `tools/session_start.py`, `tools/test_session_start.py`, `hooks/hooks.json` (SessionStart entry only; Task 6 adds PreToolUse)

**Interfaces:**
- Consumes: `workspace.find_root(start)`, `check_bootstrap_state.bootstrap_note(root)`.
- Produces: `session_start.build_context(root: Path) -> str`; `session_start.resolve_start(hook_input: dict) -> str` (returns `CLAUDE_PROJECT_DIR` env, else `hook_input["cwd"]`, else `os.getcwd()`).

- [ ] **Step 1: Write `guidance/persona.md`**

Start from `$SRC/CLAUDE.md` and apply exactly these edits:
- Title `# Job Search Agent` → `# job-search-os: persona and guardrails`. Add after the title: `This session is running inside a job-search-os workspace (the folder containing .job-search-os.json). All paths below are relative to that workspace root.`
- Every `state/career/...`, `state/tracker*.md`, `state/opportunity/...` → drop the `state/` prefix.
- Paragraph 2 (the SessionStart hook paragraph): `(tools/check_bootstrap_state.py)` → `(the job-search-os plugin's SessionStart hook)`; keep the rest of its meaning; the note it refers to is appended at the end of this context.
- Replace the whole `## State Directory` section with:

```markdown
## Workspace

All personal data lives in this workspace — never in the plugin's own
directory. The plugin's code updates independently and cannot touch it.
Files and subfolders are created on demand by the skills and by the
plugin's `tracker.py`; don't create them speculatively. The user may keep
the workspace in its own private git repo.
```

- Guardrail 3 → replace with:

```markdown
3. **Never send correspondence.** You may draft emails, but sending
   through Gmail connector tools (send, reply, forward) is blocked inside
   this workspace by a job-search-os plugin hook as well as by this
   instruction. That hook only covers those Gmail tools — it does not
   prevent sending through some other means (e.g. browser automation
   reaching Gmail's web UI), so this guardrail is instruction-level for
   anything else, the same as guardrails #1 and #2. Never use any tool or
   method to send correspondence on the user's behalf, regardless of
   whether it's technically blocked.
```

- In Data Files: `Managed only via tools/tracker.py` → `Managed only via the plugin's tracker.py (python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py")`; `python3 tools/tracker.py opportunity-path` → `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" opportunity-path`. Note: `${CLAUDE_PLUGIN_ROOT}` is **not** substituted in hook-injected text, so `session_start.py` substitutes it itself (Step 3).
- Contacts section: unchanged except path prefix.

- [ ] **Step 2: Write failing tests** — `tools/test_session_start.py`:

```python
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
```

- [ ] **Step 3: Implement** — `tools/session_start.py`:

```python
#!/usr/bin/env python3
"""SessionStart hook: inside a job-search-os workspace, inject the persona/
guardrails (guidance/persona.md) plus any bootstrap-completeness note.
Outside a workspace, do nothing. Never fails the session."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_bootstrap_state  # noqa: E402
import workspace  # noqa: E402

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).parent.parent).resolve()
PERSONA_PATH = PLUGIN_ROOT / "guidance" / "persona.md"


def resolve_start(hook_input):
    return (os.environ.get("CLAUDE_PROJECT_DIR")
            or hook_input.get("cwd")
            or os.getcwd())


def build_context(root):
    persona = PERSONA_PATH.read_text().replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))
    parts = [persona, f"Workspace root: {root}"]
    note = check_bootstrap_state.bootstrap_note(root)
    if note:
        parts.append("Setup status: " + note)
    return "\n\n".join(parts)


def main():
    try:
        try:
            hook_input = json.loads(sys.stdin.read() or "{}")
            if not isinstance(hook_input, dict):
                hook_input = {}
        except ValueError:
            hook_input = {}
        root = workspace.find_root(resolve_start(hook_input))
        if root is None:
            return
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_context(root),
        }}))
    except Exception as e:  # never break a session over this hook
        print(f"job-search-os session_start: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

`hooks/hooks.json`:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/tools/session_start.py"] }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Run tests** — `python3 -m unittest tools/test_session_start.py -v` then `tools/run_tests.sh` — Expected: PASS. `claude plugin validate .` — Expected: passes.

- [ ] **Step 5: Commit** — `git add guidance hooks tools && git commit -m "Add persona guidance and workspace-scoped SessionStart hook"`

---

### Task 6: Gmail send guard (PreToolUse)

**Files:**
- Create: `tools/guard_send.py`, `tools/test_guard_send.py`
- Modify: `hooks/hooks.json`

**Interfaces:**
- Consumes: `workspace.find_root`, `session_start.resolve_start` (import it; don't duplicate).
- Produces: `guard_send.SEND_TOOL = re.compile(r"^mcp__.*Gmail.*__(send_message|reply|forward)$")`, `guard_send.decide(hook_input: dict) -> bool` (True = deny).

- [ ] **Step 1: Write failing tests** — `tools/test_guard_send.py`:

```python
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
        self.assertIn("draft", out["permissionDecisionReason"])

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
```

- [ ] **Step 2: Run to verify failure** — `python3 -m unittest tools/test_guard_send.py -v` — Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — `tools/guard_send.py`:

```python
#!/usr/bin/env python3
"""PreToolUse hook: inside a job-search-os workspace, deny Gmail send /
reply / forward. Outside a workspace, stay silent (normal permissions apply).

Fails closed: the hook's matcher only invokes it for send-like tools, so if
the input can't be understood, denying is the safe answer.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import session_start  # noqa: E402
import workspace  # noqa: E402

SEND_TOOL = re.compile(r"^mcp__.*Gmail.*__(send_message|reply|forward)$")
REASON = ("job-search-os: sending correspondence is disabled in job-search "
          "workspaces. Draft the message instead and let the user send it.")


def decide(hook_input):
    if not SEND_TOOL.search(hook_input["tool_name"]):
        return False
    return workspace.find_root(session_start.resolve_start(hook_input)) is not None


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
        deny = decide(hook_input)
    except Exception as e:
        print(f"job-search-os guard_send: {e}; failing closed", file=sys.stderr)
        deny = True
    if deny:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }}))


if __name__ == "__main__":
    main()
```

Add to `hooks/hooks.json` alongside `SessionStart`:
```json
    "PreToolUse": [
      {
        "matcher": "mcp__.*Gmail.*__(send_message|reply|forward)$",
        "hooks": [
          { "type": "command", "command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/tools/guard_send.py"] }
        ]
      }
    ]
```

- [ ] **Step 4: Run tests** — `tools/run_tests.sh` and `claude plugin validate .` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add hooks tools && git commit -m "Block Gmail send/reply/forward inside workspaces via PreToolUse hook"`

---

### Task 7: Migration tool

**Files:**
- Create: `tools/migrate.py`, `tools/test_migrate.py`

**Interfaces:**
- Consumes: `workspace.init_root`, `workspace.MARKER`.
- Produces: `migrate.resolve_source(from_path) -> Path` (accepts repo root containing `state/`, or the `state/` dir itself, identified by containing `career/`, `opportunity/`, or `tracker.md`; else raises `ValueError`); `migrate.plan(src, dst) -> list[tuple[Path, Path]]`; `migrate.conflicts(pairs) -> list[Path]`. CLI: `migrate.py --from PATH [--to PATH] [--dry-run]`; exit 0 ok, 1 conflicts, 2 bad source.

- [ ] **Step 1: Write failing tests** — `tools/test_migrate.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure** — `python3 -m unittest tools/test_migrate.py -v` — Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — `tools/migrate.py`:

```python
#!/usr/bin/env python3
"""Copy an original job-search-os checkout's state/ into a workspace.

Read-only on the source. All-or-nothing: if any destination file already
exists, nothing is copied. Writes the workspace marker on success.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workspace  # noqa: E402

SKIP_NAMES = {".tracker.lock", ".DS_Store"}
SKIP_DIRS = {"__pycache__"}
STATE_SIGNS = ("career", "opportunity", "tracker.md")


def _looks_like_state(path):
    return any((path / s).exists() for s in STATE_SIGNS)


def resolve_source(from_path):
    p = Path(from_path).expanduser().resolve()
    if (p / "state").is_dir() and _looks_like_state(p / "state"):
        return p / "state"
    if _looks_like_state(p):
        return p
    raise ValueError(
        f"{p} doesn't look like a job-search-os checkout or its state/ folder "
        "(expected career/, opportunity/, or tracker.md)")


def plan(src, dst):
    pairs = []
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if not f.is_file() or f.name in SKIP_NAMES or SKIP_DIRS & set(rel.parts):
            continue
        pairs.append((f, dst / rel))
    return pairs


def conflicts(pairs):
    return [d for _, d in pairs if d.exists()]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="src", required=True,
                        help="original job-search-os checkout (or its state/ folder)")
    parser.add_argument("--to", dest="dst", default=".", help="workspace (default: cwd)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        src = resolve_source(args.src)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    dst = Path(args.dst).expanduser().resolve()
    pairs = plan(src, dst)

    clash = conflicts(pairs)
    if clash:
        print("Refusing to migrate — these files already exist in the workspace:")
        for d in clash:
            print(f"  {d.relative_to(dst)}")
        print("Nothing was copied.")
        sys.exit(1)

    verb = "Would copy" if args.dry_run else "Copied"
    if not args.dry_run:
        workspace.init_root(dst)
        for s, d in pairs:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
    for _, d in pairs:
        print(f"  {d.relative_to(dst)}")
    print(f"{verb} {len(pairs)} files from {src} to {dst}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests** — `tools/run_tests.sh` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add tools && git commit -m "Add migrate.py for importing an original job-search-os state/"`

---

### Task 8: Port skills and command

**Files:**
- Create: `skills/<name>/...` for all 12 source skills (with their resource files), `skills/migrate/SKILL.md`, `commands/summarize-call.md`
- Modify: `tools/run_tests.sh` (add static check)

**Interfaces:**
- Consumes: tool CLIs from Tasks 2-7 (`workspace.py init|root`, `tracker.py`, `score_table.py`, `option_value.py`, `gmail_extract.py`, `migrate.py`).

- [ ] **Step 1: Add the static check first (it must fail after copying)**

Append to `tools/run_tests.sh`:
```sh
# Static check: plugin content must not reference the old in-repo state/
# layout or call tools by a cwd-relative path.
bad=0
if grep -rnE '\bstate/(career|opportunity|tracker)|`state/`' skills commands guidance hooks; then
  echo "FAIL: state/ path references remain (above)"; bad=1
fi
if grep -rnE 'tools/[a-z_]+\.py' skills commands guidance hooks | grep -v 'CLAUDE_PLUGIN_ROOT}/tools/'; then
  echo "FAIL: tool references without \${CLAUDE_PLUGIN_ROOT} (above)"; bad=1
fi
if grep -rnE '\bJim\b' skills commands guidance \
   || grep -nE '\b(his|he|him|himself)\b' skills/file-unemployment-claim/SKILL.md; then
  echo "FAIL: personal references remain (above)"; bad=1
fi
exit $bad
```

- [ ] **Step 2: Copy**

```bash
mkdir -p skills commands
cp -R $SRC/.claude/skills/* skills/
cp $SRC/.claude/commands/summarize-call.md commands/
find skills -name .DS_Store -delete
```

Run: `tools/run_tests.sh` — Expected: unit tests PASS, static check FAILs listing many lines.

- [ ] **Step 3: Mechanical rewrite**

```bash
files=$(grep -rlE 'state/|tools/[a-z_]+\.py' skills commands)
perl -pi -e 's#python3 tools/([a-z_]+\.py)#python3 "\$\{CLAUDE_PLUGIN_ROOT\}/tools/$1"#g' $files
perl -pi -e 's#(?<![/}])\btools/([a-z_]+\.py)#\$\{CLAUDE_PLUGIN_ROOT\}/tools/$1#g' $files
perl -pi -e 's#\bstate/(career|opportunity|tracker)#$1#g' $files
```

- [ ] **Step 4: Manual pass over every changed file**

Run `tools/run_tests.sh` and fix each remaining hit, then read `git diff --word-diff` for each skill and fix wording so every sentence still reads correctly:
- A bare mention of "`state/`" or "the state directory" → "the workspace".
- `CLAUDE.md guardrail #N` / "`CLAUDE.md`'s standing instruction" → "job-search-os guardrail #N" / "the standing instruction" (the guardrails are now injected by the plugin).
- morning-scan lines ~116-117 (`settings.json` deny-list) → "the job-search-os plugin hook, which covers only the Gmail send/reply/forward tools".
- morning-scan's template path → `${CLAUDE_PLUGIN_ROOT}/skills/morning-scan/job_alert_sources.template.md`; the destination stays `career/job_alert_sources.md` (workspace).
- A quoted `python3 "${CLAUDE_PLUGIN_ROOT}/tools/x.py"` inside an inline code span is fine; make sure no command is left with unbalanced quotes: `grep -rn 'CLAUDE_PLUGIN_ROOT}/tools/[a-z_]*\.py[^"]' skills commands | grep 'python3 "'` → no output.
- Frontmatter `description` lines: replace `state/...` paths with plain workspace paths; keep trigger wording.

- [ ] **Step 5: bootstrap step 0**

In `skills/bootstrap/SKILL.md`, insert before the first existing step (renumber nothing — call it "Step 0"):

```markdown
## Step 0: Workspace

job-search-os keeps all of your data in a *workspace* folder — separate
from the plugin itself. Check for one:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/workspace.py" root

- If it prints a path, that's the workspace; continue with Step 1.
- If it exits with "not inside a job-search-os workspace":
  1. If the user already has data from the original job-search-os repo,
     stop and use the `migrate` skill instead, then come back here.
  2. Otherwise tell the user the current directory (print it) will become
     their job-search workspace, and ask them to confirm. If they'd rather
     use a different folder, ask them to start Claude in that folder and
     run bootstrap again — don't create a workspace somewhere they aren't
     working.
  3. On confirmation run
     `python3 "${CLAUDE_PLUGIN_ROOT}/tools/workspace.py" init`.
  4. Offer (don't require) `git init` so their search history is
     versioned, and tell them to keep any remote **private** — this
     folder will hold personal and compensation data.
```

- [ ] **Step 6: Generalize `file-unemployment-claim`**

In `skills/file-unemployment-claim/SKILL.md`:
- description → `Use when the user needs to file their weekly Massachusetts unemployment (DUA) certification, or asks to "file unemployment," "do my weekly claim," or similar. Massachusetts DUA only — for any other state, say this skill doesn't cover it. Walks the unemployment.mass.gov weekly certification flow, pulling work search activities from tracker.md.`
- Add as the first line under `## Scope`: `**Massachusetts only.** This covers the MA DUA weekly certification at unemployment.mass.gov. If the user files in any other state, say so and stop.`
- Replace every `Jim` → `the user`, `his` → `their`, `he` → `they` (fix verb agreement, e.g. "he confirms" → "they confirm"), `himself` → `themselves`. Do not change URLs, steps, or hard limits.

- [ ] **Step 7: New `migrate` skill** — `skills/migrate/SKILL.md`:

```markdown
---
name: migrate
description: Use when the user has an existing checkout of the original job-search-os repo (with a state/ folder) and wants to move their data into a job-search-os plugin workspace, or asks to "migrate", "import my old data", or similar.
---

# Migrate from job-search-os

## Purpose

Copy the user's personal data from an original job-search-os checkout
(`<repo>/state/`) into a workspace. The old checkout is only read, never
changed.

## Steps

1. Ask for the path to the old checkout (e.g. `~/code/job-search-os`).
   The `state/` folder itself also works.
2. Decide the destination: the current directory, unless the user names
   another. Confirm it with the user — it will become their workspace.
3. Preview:
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/migrate.py" --from "<old>" --to "<dest>" --dry-run`
   Show the user the file count and top-level folders.
4. If it reports conflicts (exit 1), show them and stop — never delete or
   overwrite workspace files to make room. Let the user decide.
5. If it reports a bad source (exit 2), tell the user what was expected
   and ask for the right path.
6. On confirmation, run the same command without `--dry-run`.
7. Verify: `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" list` run in
   the destination shows their pipeline.
8. Tell the user to start future sessions from the workspace folder, and
   offer `git init` there (keep any remote private). If the destination
   isn't the current directory, tell them to restart Claude there so the
   persona and guardrails load.

## Guardrails

- Never modify, move, or delete anything in the old checkout.
- Never overwrite existing workspace files.
```

- [ ] **Step 8: Verify** — `tools/run_tests.sh` exits 0; `claude plugin validate .` passes; `ls skills` shows 13 directories.

- [ ] **Step 9: Commit** — `git add -A && git commit -m "Port skills and summarize-call command to plugin layout; add migrate skill"`

---

### Task 9: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README** based on `$SRC/README.md`, keeping its voice, "Why this exists", "Grounded in real frameworks", "Built like software", License and "About me" sections, with these changes:
- Title `# job-search-os (Claude Code plugin)`; one line under it: fork of job-search-os restructured as a plugin, code fully separate from your data.
- Skills table: 13 rows (add `file-unemployment-claim` — "Massachusetts DUA weekly certification only" — and `migrate`); note skills are invoked as `/job-search-os:<skill>` or just by asking.
- Replace the `state/` bullet in "Built like software" with the workspace model: plugin code is installed and updated by Claude Code; your data lives in a workspace folder you own (optionally its own private git repo); plugin updates cannot touch it.
- Replace the Gmail guardrail bullet: enforced by a plugin PreToolUse hook inside workspaces for Gmail connector send/reply/forward; instruction-level otherwise.
- Links to research files → `skills/career-coach/research.md`, `skills/offer-negotiator/research.md`.
- New **Install**:
  ```
  /plugin marketplace add jimkrygowski/job-search-os-plugin
  /plugin install job-search-os@job-search-os
  ```
  Then: make a folder (e.g. `~/job-search`), start Claude there, say you want to get started (or run `/job-search-os:bootstrap`). Requires Python 3.
- New **Coming from job-search-os**: run `/job-search-os:migrate` in the new workspace folder, pointing at the old checkout.
- New **Layout** showing plugin tree and workspace tree separately.
- New **List it in your own marketplace**:
  ```json
  {
    "name": "job-search-os",
    "source": { "source": "github", "repo": "jimkrygowski/job-search-os-plugin", "ref": "v0.1.0" }
  }
  ```
  Note: omit `ref` to track the default branch; releases are tagged `vX.Y.Z` matching `plugin.json`.
- New **Development**: `tools/run_tests.sh`, `claude plugin validate .`, `claude --plugin-dir <repo>` from a test workspace.

- [ ] **Step 2: Verify** — no `state/` in README except in the migration section describing the old repo: `grep -n "state/" README.md`.

- [ ] **Step 3: Commit** — `git add README.md && git commit -m "Add README"`

---

### Task 10: End-to-end verification and tag

- [ ] **Step 1:** `tools/run_tests.sh` → exit 0. `claude plugin validate .` → `✔ Validation passed`.
- [ ] **Step 2: Marketplace install smoke test** (local):
  ```bash
  claude plugin marketplace add "$PWD"
  claude plugin install job-search-os@job-search-os
  claude plugin details job-search-os   # Skills (13), Commands (1), Hooks present
  ```
- [ ] **Step 3: Live hook smoke test** in scratch workspace `$WS` (use the session scratchpad):
  ```bash
  mkdir -p "$WS/empty" "$WS/ws"; python3 tools/workspace.py init "$WS/ws"
  (cd "$WS/ws" && claude -p "Quote the first line of any job-search-os persona text in your context, or say NONE." )
  (cd "$WS/empty" && claude -p "Quote the first line of any job-search-os persona text in your context, or say NONE.")
  ```
  Expected: `ws` quotes the persona and mentions the missing profile; `empty` says NONE.
  Then: `(cd "$WS/ws" && claude -p "Use the job-search-os tracker tool to list the active pipeline." --allowedTools Bash)` → runs `tracker.py list` via the plugin path, empty table.
- [ ] **Step 4: Real-data migration dry run** — copy, never touch the original:
  ```bash
  REPO="$PWD"
  cp -R ~/code/job-search-os/state "$WS/state-copy"
  python3 tools/migrate.py --from "$WS/state-copy" --to "$WS/migrated"
  (cd "$WS/migrated" && python3 "$REPO/tools/tracker.py" list)
  diff -r "$WS/state-copy" "$WS/migrated" -x .job-search-os.json -x .tracker.lock -x .DS_Store
  ```
  Expected: tracker lists the real pipeline; diff shows no differences other than excluded files. Delete `$WS/state-copy` and `$WS/migrated` afterwards (they hold personal data).
- [ ] **Step 5: Uninstall local test install** — `claude plugin uninstall job-search-os@job-search-os && claude plugin marketplace remove job-search-os`.
- [ ] **Step 6: Tag** — `git tag -a v0.1.0 -m "v0.1.0"`.

---

### Task 11: Publish (requires explicit user confirmation first)

- [ ] **Step 1:** Ask the user to confirm creating the **public** repo `jimkrygowski/job-search-os-plugin` and pushing `main` + `v0.1.0`.
- [ ] **Step 2:** On yes: `gh repo create jimkrygowski/job-search-os-plugin --public --source . --push --description "job-search-os as a Claude Code plugin — code fully separate from your data"` then `git push origin v0.1.0`.
- [ ] **Step 3:** Verify from a clean state: `claude plugin marketplace add jimkrygowski/job-search-os-plugin && claude plugin install job-search-os@job-search-os`, then remove both.
