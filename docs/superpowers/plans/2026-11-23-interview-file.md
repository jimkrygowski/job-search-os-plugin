# Interview Files and Talking Points Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One file per interview session shared by prep and review, `career/talking_points.md` as a known file, and the "define every term" / "prep is a guess" / "save rehearsed answers in full" behaviors written into the skills.

**Architecture:** A new `tracker.py interview-file` subcommand owns the file name, creation and the one-time `notes.md` link. Skills call it; skills that read `notes.md` follow its links.

**Tech Stack:** Python 3 stdlib (`unittest`), markdown skills.

**Spec:** `docs/superpowers/specs/2026-11-23-interview-file-design.md`

## Global Constraints

- Stdlib only; tests run via `tools/run_tests.sh`.
- Skills call tools as `python3 "${CLAUDE_PLUGIN_ROOT}/tools/<x>.py"`; never bare `tools/...` or `state/...`.
- No real people/companies in examples, fixtures or tests (invented names only); no "Jim" in skills/guidance.
- Never write user state outside the workspace.
- Version 0.3.0 → 0.4.0 in `.claude-plugin/plugin.json`, `marketplace.json` if it carries one, and the README pin.

## Review Focus

1. Calling `interview-file` twice (prep then review) → same file, one link in `notes.md`. (Task 1 `test_second_call_changes_nothing`)
2. Opportunity folder or `notes.md` doesn't exist yet (review of an unprepped call on a new opportunity) → both created. (Task 1 `test_creates_folder_and_notes_when_missing`)
3. `notes.md` without a trailing newline → link starts on its own line. (Task 1 `test_link_starts_on_own_line`)
4. Bad date (`2026-13-01`, `next tuesday`) or empty/punctuation-only `--who` → exit 1, nothing written. (Task 1 `test_rejects_bad_date_and_empty_who`)
5. Two interviewers in one session → one file with both names in the slug. (Task 1 `test_two_interviewers_one_file`)

---

### Task 1: `tracker.py interview-file`

**Files:**
- Modify: `tools/tracker.py` (new `interview_file_path`, `cmd_interview_file`, parser entry next to `opportunity-path`)
- Test: `tools/test_tracker.py` (new `InterviewFileTest`, CLI via subprocess like `WorkspaceResolutionTest`)

**Interfaces:**
- Produces: CLI `tracker.py interview-file "<Company>" "<Role>" --date YYYY-MM-DD --who "<text>"` → prints absolute file path; exit 1 with `error: ...` on bad input.
- Produces: `interview_file_path(company: str, role: str, date: str, who: str) -> Path` = `opportunity_path(company, role) / "prep" / f"{date}_{slugify(who)}.md"`.

- [ ] **Step 1: Write failing tests** in `InterviewFileTest` (temp workspace, run CLI):
  - `test_creates_file_with_header_and_prints_path`: `interview-file Acme "VP Eng" --date 2026-12-01 --who "Dana Reyes"` → stdout == `<root>/opportunity/acme/vp_eng/prep/2026-12-01_dana_reyes.md`; file text starts with `# Interview: Acme / VP Eng: Dana Reyes, 2026-12-01\n`.
  - `test_appends_link_to_notes`: notes.md contains `\n## Interview (2026-12-01): Dana Reyes\n[prep/2026-12-01_dana_reyes.md](prep/2026-12-01_dana_reyes.md)\n`.
  - `test_second_call_changes_nothing`: write extra text into the file; call again; same stdout, file text unchanged, link appears exactly once in notes.md.
  - `test_creates_folder_and_notes_when_missing`: fresh workspace, no tracker row → exit 0, notes.md exists.
  - `test_link_starts_on_own_line`: pre-write notes.md as `"# Notes\nlast line"` (no newline) → notes contains `"last line\n\n## Interview ("`.
  - `test_rejects_bad_date_and_empty_who`: `--date 2026-13-01`, `--date "next tuesday"`, `--who "  "`, `--who "--"` each → returncode 1, `error:` in stderr, no `prep/` folder created.
  - `test_two_interviewers_one_file`: `--who "Dana Reyes and Sam Ortiz"` → filename `2026-12-01_dana_reyes_and_sam_ortiz.md`.
  - `test_date_is_normalized`: `--date 2026-12-01` only ISO accepted; output filename uses `date.fromisoformat(...).isoformat()`.
- [ ] **Step 2:** `python3 -m unittest tools.test_tracker -k InterviewFile` (from `tools/`: `python3 -m unittest test_tracker.InterviewFileTest`) → FAIL (invalid choice).
- [ ] **Step 3: Implement.** Validate date with `datetime.date.fromisoformat` and require `slugify(who) != "unnamed"` via `_fail`. Create the file with `open(path, "x")`; only on successful creation append the link to `notes.md`, prefixing `\n` and an extra `\n` if the existing file doesn't end with a newline. `FileExistsError` → do nothing. Print the path.
- [ ] **Step 4:** Rerun → PASS; `tools/run_tests.sh` → PASS.
- [ ] **Step 5:** Commit `tracker: interview-file command`.

### Task 2: `interview-prep` and `interview-review` skills

**Files:**
- Modify: `skills/interview-prep/SKILL.md`, `skills/interview-review/SKILL.md`
- Test: `tools/test_skills.py` (new `InterviewFileSkillsTest`)

**Interfaces:**
- Consumes: Task 1 CLI. The skill text must contain the literal `"${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" interview-file` invocation.

- [ ] **Step 1: Failing tests:**
  - `test_both_skills_call_interview_file`: both contain `f'{TRACKER} interview-file '` (use `_invocations("interview-file")`, assert the set of skill names ⊇ {interview-prep, interview-review}).
  - `test_both_read_talking_points`: both contain `career/talking_points.md`.
  - `test_prep_defines_terms_and_saves_rehearsals`: prep contains `Glossary`, `best guess`, `Rehearsed answers`.
  - `test_review_writes_to_interview_file_not_notes`: review does not contain `Append the review under` nor `appends it to the opportunity's notes.md`; contains `## Review (<date>)` and `question actually asked`.
  - `test_talking_points_needs_ok`: both contain `talking_points.md` and the phrase `only with the user's OK`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Rewrite the skills per spec §2–§4.** Prep: Session Start adds profile, master resume, talking points (optional), earlier interview files linked from notes.md; get date (scheduled, else today) and interviewer(s) per session; one `interview-file` call per session (loop = one per set of people). Briefing opens as a best guess; uses settled talking points; defines every term inline + Glossary with "if asked, say…" and background-only marks. Output: write under `## Prep (<date>)`; rehearsed answers in full under `## Rehearsed answers` as settled, check before saying done; talking-points offer. Review: frontmatter description; Session Start file matching (list `prep/`, match by interviewer, any date; else create; ask if unclear); write under `## Review (<date>)` with `Source:` line; guardrails (question actually asked, no faulting for unused prep, quote openings, not a checklist); talking-points offer on misfire/landing. Talking-points entry format described in prep (review references it).
- [ ] **Step 4:** Run tests → PASS; `tools/run_tests.sh` → PASS.
- [ ] **Step 5:** Commit `interview skills: per-interview files, talking points, review guardrails`.

### Task 3: Readers follow interview links; persona; docs; version

**Files:**
- Modify: `skills/career-coach/SKILL.md:26`, `skills/offer-negotiator/SKILL.md` (lines ~18, ~326, ~399), `skills/score-opportunity/SKILL.md:80`, `skills/backfill-history/SKILL.md:25`, `guidance/persona.md` (~13, ~73, file list ~87), `README.md` (rows 45–46, version pin), `.claude-plugin/plugin.json`
- Test: `tools/test_skills.py`

- [ ] **Step 1: Failing tests:**
  - `test_notes_readers_follow_interview_links`: each of career-coach, offer-negotiator, score-opportunity, backfill-history, interview-prep, and `guidance/persona.md` contains `prep/`.
  - `test_backfill_reads_both_review_headings`: backfill contains `## Review (<date>)` and `## Interview Review (<date>)`.
  - `test_persona_lists_talking_points`: persona contains `career/talking_points.md`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Edit per spec §5–§6. Persona gets one general rule ("reading an opportunity's `notes.md` includes the interview files under its `## Interview (<date>): <who>` links, in `prep/`"); each reader skill points at that rule with a short explicit clause. README rows + pin; plugin.json version.
- [ ] **Step 4:** `tools/run_tests.sh` → PASS; `claude plugin validate .` → passes.
- [ ] **Step 5:** Commit `skills follow interview links; persona, README, v0.4.0`.

### Task 4: End-to-end check, review, fixes

- [ ] **Step 1:** In a scratch workspace with invented data, run `claude -p --plugin-dir <repo>` through: prep for a two-session loop, then a review of one session's (invented) transcript. Check: two prep files, two links in notes.md, review landed in the matching prep file, glossary present, talking_points offer made but file not written, `notes.md` has no review body.
- [ ] **Step 2:** Fresh reviewer on the whole branch diff against the spec; fix confirmed findings; rerun `tools/run_tests.sh`; commit.
