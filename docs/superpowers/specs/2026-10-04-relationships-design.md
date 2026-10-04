# Relationships tracker (v1) — design

Date: 2026-10-04
Status: approved in conversation, pending written-spec review
Target release: plugin v0.3.0 (after v0.2.0 ships)

## Intent

A job search runs on people: recruiters, connectors and peers who keep
producing opportunities and intros. Today they live in one `contacts.md`
per opportunity (47 files in the author's workspace), so the same person is
recorded several times, nothing says when to get back in touch, and intros
that were offered but never made go unnoticed. Relationships that
aren't tied to one opening ended up in a free-text `networking.md`.

v1 gives every person **one page**, gives relationships a **follow-up
rhythm**, and treats **intros as a pipeline**. Measuring which
relationships produce results (dashboard views) is phase 2; the data model
is built so it can answer that.

### Decisions (from interview)

| Topic | Decision |
|---|---|
| v1 scope | People + follow-ups + intros. Measurement dashboard is phase 2. |
| Unit | A person, with an organization. Firms are not records; group/filter by `org`. |
| Who is in | Everyone from contacts.md is imported; `relationship: yes/no` decides who gets follow-ups. |
| Roles | Per person-to-opportunity link (`role @ opportunity`), not per person; a role may also stand alone. |
| Source of truth | The people tool. Each `contacts.md` becomes a generated, read-only view. |
| Storage | One markdown page per person (`people/<slug>.md`), tool-managed field block + free-form notes; append-only `people_events.jsonl`. |
| Intro lifecycle | Offered → Made → Met → result: `led_to_opportunity` / `led_to_intros` / `dead_end`. |
| Follow-ups | A cadence per relationship; a touch rolls `next_touch` forward; an explicit date can override. |
| Morning-scan | Reports due relationships and stalled intros; logs email touches automatically. |
| Deferred | Dashboard people views, a search index over people pages, calendar-driven touches, any sending. |

### Success criteria

1. `tools/run_tests.sh` and `claude plugin validate .` pass; the Playwright
   suite stays green.
2. On the author's workspace: every person in the 47 `contacts.md` files
   has a page or is listed as unparsed; no notes text is lost (word count
   of imported notes ≥ word count of source Notes cells); `due` produces a
   bounded first list (overdue items at the top of the draft for review).
3. Every regenerated `contacts.md` still names everyone it named before,
   now with a role.
4. A morning-scan run lists due relationships and stalled intros and logs
   at least one real email touch.

## Data model

### Person page — `people/<slug>.md`

```markdown
---
name: Dana Reyes
org: Northwind Motors
title: Senior Manager, Technical Recruiting
email: dana.reyes@example.com
relationship: yes
cadence: 21d
next_touch: 2026-10-23
roles: recruiter @ northwind_motors/vp_of_engineering, connector @ bluefin_security/head_of_platform
aliases: Dana Reyes-Kim
---

## Notes
...free-form; never modified by the tool...
```

**Field block format** (deliberately not YAML; stdlib-only):
- Delimited by the first line `---` and the next line that is exactly `---`.
  The block is only recognized at the very top of the file.
- One `key: value` per line; the key is `[a-z_]+`, split at the first `: `.
  Values are single-line strings. Empty value = unset.
- List fields (`roles`, `aliases`) are comma-separated; an item may not
  contain a comma (names/orgs with commas go in `name`/`org`, which are not
  lists). Leading/trailing whitespace is trimmed.
- Known keys only: `name` (required), `org`, `title`, `email`,
  `relationship` (`yes`/`no`, default `no`), `cadence` (`<N>d` or `none`,
  default `none`), `next_touch` (`YYYY-MM-DD` or empty), `roles`,
  `aliases`. An unknown key, a malformed line, or an invalid value is an
  error that names the file and line; nothing is written.
- Everything after the closing `---` is the body. The tool preserves it
  byte-for-byte, including body lines that are themselves `---`.
- Keys are written in the fixed order above; unset keys are omitted.

**Roles:** `recruiter | connector | hiring | peer | panelist | other`.
An entry is `role @ opportunity-slug` (slug = `tracker.py`'s
`<company>/<role>` folder slug, which must exist in the tracker, active or
closed) or a bare `role` (not tied to an opportunity). The same person may
hold several entries, including different roles on one opportunity.

**Slugs:** `slugify(name)` with `-` separators (e.g. `dana-reyes`);
on collision `-2`, `-3`… A `<person>` argument resolves by slug, then
email, then exact name (case-insensitive), then alias. More than one match
→ error listing the candidates; zero → error. Never fuzzy.

### Event log — `people_events.jsonl`

Append-only, one JSON object per line, written under the same lock as the
pages. Every event has `ts`, `type`, `inferred` (bool).

| type | fields |
|---|---|
| `person` | `person`, `action` (`add`/`update`/`merge`/`role`), `detail` |
| `touch` | `person`, `channel` (`call`/`email`/`meeting`/`message`/`other`), `note` |
| `intro` | `intro` (id `i-<n>`), `status` (`offered`/`made`/`met`/`closed`), `from`, `to` (person slug or `org:<Name>`), `for` (opportunity slug, optional), `result` (on `closed`), `opportunity` (when result is `led_to_opportunity`), `note` |

An intro's current state is its latest event. Ids are allocated
`i-<max+1>`. An open intro is **stalled** when its latest event is at
least `stallDays` old (`dashboard.stallDays` in `.job-search-os.json`,
default 21).

### Follow-up rule

For a person with `relationship: yes` and a cadence `Nd`, a touch dated D
sets `next_touch = max(D + N days, existing next_touch if it was set
explicitly and is later)`. An explicit `--next-touch` always wins until
the next touch. `cadence: none` people never come due unless they have an
explicit `next_touch`. People with `relationship: no` never come due.

## The tool — `tools/people.py`

Sole writer of `people/`, `people_events.jsonl` and generated
`contacts.md`. Stdlib only; `sys.dont_write_bytecode = True`; workspace
via `workspace.require_root()`; mutual exclusion via a `.people.lock`
(same mechanism as `tracker.locked()`).

### Commands

| Command | Behavior |
|---|---|
| `add "Name" [--org --title --email] [--role R@opp|R …] [--relationship yes\|no] [--cadence Nd\|none] [--next-touch D]` | Creates the page. Refuses a duplicate (same email, or same name + org) and names the existing page. |
| `update <person> [field flags…]` | Changes fields; body untouched. |
| `role <person> --add R@opp|R` / `--drop …` | Edits roles; opportunity must exist in the tracker. |
| `show <person>` | Fields, roles, last 10 touches, open intros. |
| `find <text>` | Substring match over name, org, email, aliases. |
| `merge <keep> <drop>` | Union of roles and aliases (drop's name becomes an alias); drop's body appended under `## Merged from <name>`; events for `drop` are re-pointed by a `person/merge` event (readers resolve through it); drop's page removed. |
| `touch <person> --channel C [--date D] [--note N]` | Logs a touch; applies the follow-up rule. |
| `due [--within Nd]` | Relationships with `next_touch` ≤ today + window (overdue first), then stalled intros, then open intros waiting on the user (status `offered` where the user owes a reply is not modeled in v1; listed as open). |
| `intro offer <from> --to <person\|"Org"> [--for opp] [--date] [--note]` | Opens an intro; prints its id. With `--for`, adds `connector @ opp` to `<from>`. |
| `intro made\|met <id> [--date]` | Advances; may skip forward (offered → met), never backward; error on a closed intro. |
| `intro close <id> --result led_to_opportunity --opportunity opp` / `--result led_to_intros\|dead_end` | Closes; `led_to_opportunity` requires an existing opportunity. |
| `intro list [--open]` | Id, from → to, status, age. |
| `sync-contacts [--opportunity opp]` | Regenerates `contacts.md` for every linked opportunity (or one). Run automatically by every write for the opportunities it touches. |
| `export --json` | People (fields + roles), touches, intros (with current state), for phase 2. |
| `import --draft` / `import --apply <draft>` | One-time migration (below). |

All validation happens before any write. Dates are `YYYY-MM-DD`
(`--date` defaults to today; touches/intros store `<date>T<now-time>` for
today, `<date>T09:00:00` otherwise).

### Generated `contacts.md`

```markdown
# Contacts — Northwind Motors / VP of Engineering

<!-- generated by people.py — edit people/ pages via people.py, not this file -->

| Name | Role | Org | Title | Email | Page |
| --- | --- | --- | --- | --- | --- |
| Dana Reyes | recruiter | Northwind Motors | Senior Manager, … | dana.reyes@… | [[people/dana-reyes]] |
```

Rows sorted by role (recruiter, hiring, connector, peer, panelist, other),
then name. Cells escaped like tracker tables. An opportunity with no
linked people gets the header and an empty table.

## Import (one-time)

1. **`import --draft`** parses every `opportunity/*/*/contacts.md`:
   markdown tables (any column order; columns recognized by header names
   Name/Title/Role…/Email/Notes and close variants) and bullet lists
   (`- **Name** — …`). Unparsed lines are listed with file:line.
   It also reads `networking.md` entries (`## Name — Role` sections).
2. It writes `people-import-draft.md` in the workspace:
   - one row per proposed person: name, org, title, email, proposed roles
     (`role @ opp` per file, from the "Role in Process" text by keyword;
     uncertain → `?`), `relationship` (yes for recruiter/connector/peer;
     no for panelist and for anyone only attached to closed
     opportunities as hiring/other), cadence (recruiter 21d, connector
     30d, peer 45d), proposed `next_touch` (latest dated mention + cadence;
     overdue rows listed first);
   - a **"Same person?"** section for non-exact candidate merges
     (same email domain + similar name, alias hints in notes);
   - proposed **intros** found in notes and networking.md, marked inferred.
   Merge rules: same email → same person; same exact name + same org →
   same person; nothing else merges without the user's decision.
3. The user edits the draft.
4. **`import --apply <draft>`** validates the whole draft first, then
   creates pages (each source Notes cell appended to the body under
   `### From <opportunity>`), records intros (inferred), writes
   `person/add` events, regenerates every `contacts.md`, and replaces
   `networking.md`'s body with a pointer to `people/` (its content moves
   onto the people pages' notes). Re-applying the same draft is a no-op.
   The author commits the result in the workspace as one revertible
   commit.

## Skills and guidance

- **`guidance/persona.md`:** contacts rule → `people.py add` / `role
  --add`; never hand-edit `contacts.md`; log conversations with
  `people.py touch`, intros with `people.py intro`; data-file map gains
  `people/`, `people_events.jsonl`; `networking.md` retired.
- **`morning-scan`:** new step runs `people.py due --within 3d` and
  reports due relationships, stalled intros, open intros; the existing
  email tier logs an `email` touch for each new message from a known
  person (matched by email).
- **`interview-review`, `summarize-call`:** touch every attendee
  (`call`/`meeting`), add new attendees with a role, record intros offered.
- **`company-research`:** people found get pages with `relationship: no`
  and a role on the opportunity.
- **`score-opportunity`:** when an opportunity came through a person,
  close the matching intro as `led_to_opportunity` (or record it).
- **New `relationships` skill:** "who should I reach out to?" (runs `due`,
  explains why, drafts notes on request — never sends), "tell me about X"
  (`show` + notes summary), and "set up the import" (walks section
  *Import*).

The tracker, the dashboard and the never-send guardrail are unchanged.

## Testing

Python stdlib `unittest`, in `tools/test_people.py`, plus skill checks in
`tools/test_skills.py`.

- **Field block:** round-trip identity; body preserved byte-for-byte
  (including `---` lines and trailing whitespace); unicode, commas in
  `name`/`org`, `@` in emails; malformed block → error with line, no write;
  unknown key → error; a hand-edited page is re-read, not clobbered.
- **People:** duplicate refusal; ambiguous `<person>` lists candidates;
  slug collisions; `merge` keeps both bodies, unions roles, removes the
  dropped page, resolves the dropped slug through the merge event; role
  on an unknown opportunity rejected.
- **Follow-ups:** touch rolls `next_touch`; a later explicit date is
  kept; `cadence: none` never due; `relationship: no` never due; `due
  --within` boundary.
- **Intros:** no backward moves; skip-forward allowed; closed intro is
  immutable; `led_to_opportunity` requires an existing opportunity;
  `offer --for` adds the connector role; stall threshold uses `stallDays`.
- **contacts.md:** generated content and header; regenerated on writes
  for touched opportunities only; sorting; escaping.
- **Import:** fake fixtures modeled on the real shapes (tables with
  differing columns, bullet lists, networking.md) — no real data in the
  repo; email merge; name+org merge; non-exact candidates listed not
  merged; unparsed lines reported; apply twice = no-op; notes text
  preserved (word count).
- **Locking:** concurrent `touch` calls don't clobber (mirrors the
  tracker's concurrency test).
- **Skills:** persona/skills call `people.py` via `${CLAUDE_PLUGIN_ROOT}`;
  no instruction to edit `contacts.md` by hand; morning-scan calls `due`;
  `run_tests.sh`'s static checks cover `people.py` references.

## Rollout

1. Ship v0.2.0 first (merge the "No Role" change, tag, user updates the
   plugin) — the author's workspace is already in v0.2 format.
2. Build v0.3.0 on `relationships-v1`: this spec → implementation plan →
   test-first implementation → PR → independent review → merge → tag.
3. Run the import on the author's workspace: dry run on a copy, draft,
   review, apply, one revertible workspace commit.

## Out of scope (v1)

- Dashboard views of relationships (which connectors led to interviews or
  offers, intro conversion) — phase 2, fed by `people.py export --json`.
- A search index over `people/` pages.
- Calendar-driven touches (only email touches are automatic in v1).
- Modeling "intro waiting on the user" separately from other open intros.
- Sending anything.
