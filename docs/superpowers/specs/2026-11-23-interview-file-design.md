# Interview files and talking points: design

Date: 2026-11-23. Branch: `interview-prep-enhancements`.

## Intent

Two problems, both found in daily use of the plugin:

1. **`notes.md` is unmanageable.** `interview-prep` (when asked to save) and
   `interview-review` (always) append whole sections to the opportunity's
   `notes.md`. After a few rounds the file is hundreds of lines of prep,
   reviews and research mixed together. Each interview should get its own
   file that holds its whole life: the prep briefing, rehearsed answers, and
   the review afterwards. `notes.md` keeps one heading and a link per
   interview.
2. **Behavior that only lives in one user's memory.** Several corrections the
   user gave Claude are stored as workspace memories, not in the skills, so
   every other user (and any session that misses the memory) loses them:
   - read `career/talking_points.md`, the user's settled answers to questions
     that come up in every interview;
   - define every term in prep material;
   - prep is a best guess, so a review must not fault the user for not
     following it;
   - save rehearsed answers in full, not as summarized "fixes".

Only the general behavior moves into the plugin. Anything specific to one
user (their own boundaries, wording preferences) stays in their workspace.

## Goals

- One file per interview, at a path decided by a tool, shared by prep and
  review.
- `interview-prep` writes its briefing (with glossary) and rehearsed answers
  into that file; `interview-review` writes its review into the same file.
- `career/talking_points.md` becomes a known, optional workspace file:
  prep reads it; prep, rehearsal and review can offer additions; nothing is
  added without the user's OK.
- Reviews judge answers against what was actually asked.

## Non-goals

- Migrating existing inline prep/review sections out of `notes.md`. They stay.
- Reformatting any user's existing `talking_points.md`. The plugin never
  touches user state.
- Dashboard changes. The export contract (`dashboard/fixtures/export.json`)
  is unchanged. The dashboard's notes view shows `notes.md` only, so the new
  interview links appear there as text but don't open the interview file.
  Accepted for now (builder's call, flagged to the user).
- Changing `commands/summarize-call.md`'s one-line `notes.md` summary.
- Bootstrap creating `talking_points.md`.

## Anti-goals (a failure even if it works)

- Prep and review landing in two different files for the same interview.
- Review grading the user against the prep plan or against `talking_points.md`.
- Any skill writing to `talking_points.md` without the user's explicit OK.
- Prep material that names a term the user can't explain if asked about it.
- Coaching that invents accomplishments or contradicts a trajectory must-not
  to fit a settled answer (existing guardrail; keep it).

## Approaches

| | What | Trade-off |
|---|---|---|
| A | Skill text only: both skills describe the path, slug and link line. | Smallest change, but Claude derives the filename twice; a date or name spelled differently splits one interview into two files. The repo already bans constructing paths in prose for this reason. |
| **B (chosen)** | A `tracker.py` subcommand returns (and creates) the interview file and adds the `notes.md` link once; both skills call it. | A bit more code and tests; naming is decided and tested in one place, matching the existing `opportunity-path` pattern. |
| — | Show interview files on the dashboard. | Dropped: not asked for, and it would change the export contract. |

The user picked B.

## Design

### 1. `tracker.py interview-file`

```
python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" interview-file "<Company>" "<Role>" \
  --date YYYY-MM-DD --who "<interviewer name or short label>"
```

- Resolves the folder with `opportunity_path(company, role)` (no tracker-row
  lookup required, same as `opportunity-path`).
- File: `<opportunity>/prep/<date>_<slugify(who)>.md`. `--date` is validated
  as an ISO date. `--who` is free text: the interviewer's name; for a
  session with several interviewers, their names joined with "and"
  (`"Jane Doe and Raj Patel"`); or, only when names aren't known yet, a short
  label such as `recruiter screen`.

**One file per interview session.** A session is one conversation with one
set of people. A loop day with three sessions with different people is three
files, never one "loop" or "panel" file. Prep for a loop creates each
session's file and writes that session's briefing into it; each file stands
on its own (shared context is repeated briefly, not cross-referenced).

**Date.** The scheduled date when there is one. When the interview isn't
scheduled yet, the date prep is done. The review finds that file by
interviewer (see §3), so the date doesn't have to match the call.
- If the file doesn't exist: create `prep/` and the file with a header:
  ```
  # Interview: <Company> / <Role>: <who>, <date>
  ```
  and append to `notes.md` (creating the folder/file if needed):
  ```

  ## Interview (<date>): <who>
  [prep/<file>](prep/<file>)
  ```
- If the file exists: change nothing. Idempotent; the link is written only
  when the file is created.
- Prints the absolute path of the file on stdout (one line), like
  `opportunity-path`.
- Stdlib only; Python tests in `tools/test_tracker.py` cover: path and slug,
  creation with header, link appended exactly once across repeated calls,
  existing file untouched, invalid date rejected, works with no tracker row.

### 2. `interview-prep` skill

Session Start adds: read `career/talking_points.md` if it exists, plus
`career/profile.md` and `career/resume/master_resume.md` (already used for
talking points but not listed in Session Start). Then get the interview's
date and who, and call `interview-file` to get the file. If that file already
has content (an earlier prep session for the same interview), read it and
build on it.

Briefing contents keep the current four parts, with these changes:

- **Framing:** the briefing opens by saying it is a best guess at where the
  conversation will go, not a script.
- **Talking points:** when a likely question matches an entry in
  `talking_points.md`, use the settled answer and point to it; don't
  re-derive it.
- **Define every term:** every tool, metric, acronym, vendor or method named
  gets a short plain-language explanation on first use. A **Glossary**
  section at the end gives each technical term a one-line "if asked, say..."
  and marks terms that are background only (not worth saying aloud).

Output changes:

- The briefing is written to the interview file under `## Prep (<date>)`
  (in addition to being summarized in chat). No longer "only if asked".
- **Rehearsal:** when the user rehearses answers, save each agreed answer in
  full (the user's phrasing with the agreed changes folded in) under
  `## Rehearsed answers` in the interview file, as each one is settled.
  Before saying prep is done, check every answer worked out in chat is in
  the file.
- **Talking-points offer:** when an answer is settled for a question that
  would come up in any interview (not specific to this opportunity), offer
  to add it to `career/talking_points.md`, or update the existing entry.
  Write only on the user's OK; create the file on the first OK.

### 3. `interview-review` skill

- Description frontmatter: no longer "appends it to the opportunity's
  notes.md"; it writes into the interview's file.
- Session Start: read `career/talking_points.md` if it exists. List
  `<opportunity>/prep/` (folder from `opportunity-path`) and look for the
  file prepped for this session: same interviewer(s), any date (it may have
  been prepped before it was scheduled, or rescheduled). If exactly one
  matches, call `interview-file` with that file's date and label. If none
  match, call it with the call's date and interviewer(s), which creates the
  file. If it's unclear, ask the user which file it is. For a loop day
  reviewed from several transcripts, each session's review goes in that
  session's own file.
- Output step 1 becomes: write the review into the interview file under
  `## Review (<date>)`, with the `Source: transcripts/<filename>` line.
  Transcript saving, tracker update and people steps are unchanged.
- New guardrails ("prep is a guess"):
  - Judge each answer against the question actually asked.
  - Don't fault the user for skipping prep material (unused stories, prep
    questions that never came up) when the conversation went another way.
  - Call something a miss only when the transcript shows a clear, specific
    opening for it, and quote that moment. Don't claim an interviewer
    raised or invited something unless the transcript shows it.
  - `talking_points.md` is prep material, not a checklist: never grade
    against it.
- **Talking-points offer:** when the transcript shows a settled answer
  misfiring, or a new answer to a common question landing well, quote the
  moment and offer to update or add the entry. Write only on the user's OK.

### 4. `career/talking_points.md` format

Described once (in the persona's file list, referenced by both skills):

```
# Talking Points

## "<The question, as interviewers ask it>"

**Last updated:** YYYY-MM-DD. Sources: <files / transcripts with timestamps>.

<The user's position, if it matters to the answer.>

<The answer.>

<Optional: why earlier versions misfired, with sources.>
```

Every claim in an answer must trace to `career/profile.md`,
`career/resume/master_resume.md`, a transcript, or something the user said
(existing persona sourcing rule). Skills tolerate entries that don't match
this shape exactly (e.g. a missing date).

### 5. Skills that read `notes.md` follow the interview links

With reviews out of `notes.md`, any skill reading an opportunity's history
must also read the interview files `notes.md` links to (the
`## Interview (<date>): <who>` headings), or it loses comp signals, concerns
and team details learned in interviews. Each of these skills gets an explicit
instruction to follow those links when reading `notes.md`:

- `interview-prep`: reads earlier interviews' files (prep and review) before
  prepping a later round.
- `career-coach`: Session Start step 1 (pipeline read).
- `offer-negotiator`: wherever it reads `notes.md` for what's known about
  the opportunity, including comp signals from interviews.
- `score-opportunity`: re-scoring an existing opportunity.
- `backfill-history`: step 2's evidence includes `## Review (<date>)`
  headings in `prep/` files as well as legacy `## Interview Review (<date>)`
  headings in `notes.md`.

`company-research` and `summarize-call` only write to `notes.md` and are
unchanged. Old inline sections in `notes.md` remain valid evidence everywhere.

### 6. Persona and docs

- `guidance/persona.md`:
  - file list gains `career/talking_points.md` (optional, settled answers
    to questions asked in every interview) and the
    `opportunity/<co>/<role>/prep/` folder (one file per interview session);
  - the "facts come from ... `opportunity/*/notes.md`" rule (line ~13) and
    the sourcing rule (line ~73) extend to the interview files;
  - a general rule: reading an opportunity's `notes.md` means also reading
    the interview files it links.
- `README.md` rows for `interview-prep` and `interview-review` mention the
  per-interview file.
- `tools/test_skills.py`: assert both skills call `tracker.py interview-file`,
  both mention `career/talking_points.md`, prep mentions the glossary,
  review no longer says it appends the review to `notes.md`, and each skill
  in §5 mentions the `prep/` interview files.
- Version bump in `.claude-plugin/plugin.json` (0.3.0 → 0.4.0) and the README
  pin, matching how earlier feature releases were tagged.

## Left to the builder

- Exact wording of the skill text, within the rules above.
- Header and heading wording, as long as `notes.md` gets exactly one
  heading + link per interview file.
- Error messages for the new subcommand.
