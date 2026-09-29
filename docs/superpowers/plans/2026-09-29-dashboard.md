# Dashboard v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only, localhost reflection dashboard (outcome Sankey, stage conversion + time, weekly activity) backed by a new stage-event log in `tracker.py`.

**Architecture:** `tracker.py` gains canonical stages, `Source`/`Outcome` columns, an append-only `tracker_events.jsonl`, `export --json` and `backfill`. A Node (≥ 22.18, built-ins only) TypeScript server shells out to `export --json`, derives one record per opportunity, and serves a TypeScript browser app (compiled at development time, output committed) that aggregates and renders the charts with vendored d3 + d3-sankey.

**Tech Stack:** Python 3 stdlib (unittest); Node ≥ 22.18 running `.ts` directly (type stripping), `node:test`; TypeScript (dev only) for type-checking and the browser build; d3 7.9.0 + d3-sankey 0.12.3 vendored.

**Spec:** `docs/superpowers/specs/2026-09-29-dashboard-design.md`

**Execution note:** the user asked for autonomous, uninterrupted execution
("go as far as you can without asking questions"). It runs natively in the
session on branch `dashboard-v1`. Tasks list their tests as concrete cases
rather than full code listings, because the planner and the implementer are
the same session.

## Global Constraints

- Python tools and tests: stdlib only. Tools set `sys.dont_write_bytecode = True`.
- Dashboard runtime: Node built-ins only; Node ≥ 22.18; server `.ts` uses erasable syntax only.
- npm packages are dev-only: `typescript`, `@types/d3`, `@types/d3-sankey`, `@types/node`.
- Nothing is written into `${CLAUDE_PLUGIN_ROOT}` at runtime. The dashboard server writes nothing at all.
- Skills reference tools as `python3 "${CLAUDE_PLUGIN_ROOT}/tools/<x>.py"` and the server as `node "${CLAUDE_PLUGIN_ROOT}/dashboard/server/main.ts"`.
- Stages: `Identified, Applied, Recruiter Screen, Hiring Manager, Interview Loop, Offer`. Outcomes: `Accepted, Rejected, Withdrew, Ghosted, Declined Offer`. Sources: `Referral, Recruiter Inbound, Applied Cold, Warm Intro, Job Alert, Other`.
- `stallDays` default 21, from `.job-search-os.json` → `dashboard.stallDays`.
- The server binds to 127.0.0.1, is GET-only, checks the Host header, and shuts down after 2 hours idle.
- The repo never contains a `.job-search-os.json`. Fixtures are stored without a marker, and tests create one in a temp copy.

## Review Focus

1. **A v0.1 tracker that has non-canonical stages already in its rows** (e.g. "Screen", "Final round"). `export` and the dashboard must still work, reporting the unmapped stage in `warnings` and showing it as its own node. Pinned in Task 2 (export test with an unmapped stage) and Task 4 (derive keeps unknown stages).
2. **Company or role names with `|`, commas, quotes or unicode** flowing through events JSONL → export → UI. Pinned in Task 1 (event round-trip with `Bed | Bath, "Inc"`) and Task 7 (all UI text inserted via `textContent`/escaped).
3. **An opportunity closed and later re-added** (same company/role). Events for both lifetimes exist, so derive uses only events after the most recent `add`. Pinned in Task 4.
4. **Events whose company/role match no tracker row** (a hand-deleted row) are ignored with a warning rather than crashing. Pinned in Task 4.
5. **`python3` missing, or the export exiting non-zero**, gives a 500 with the detail and a visible banner, not a hung request. Pinned in Task 6 (exporter pointed at a failing command).

---

### Task 1: tracker.py — canonical stages, Source/Outcome columns, event log

**Files:** Modify `tools/tracker.py`, `tools/test_tracker.py`.

**Produces:**
- `STAGES`, `OUTCOMES`, `SOURCES`, `LEGACY_STAGES` (lowercased-key dict).
- `canonical_stage(name) -> str | None`.
- `ACTIVE_COLUMNS` = the six v0.1 columns + `Source`. `CLOSED_COLUMNS` = `ACTIVE_COLUMNS` + `Outcome`.
- `parse_table(text, columns)` accepts either the legacy or the full column set.
- `events_path()`, `append_event(dict)`, `read_events() -> (events, warnings)`.
- CLI:
  - `add --stage --source` (source required).
  - `update-status` (validated, logs only on change).
  - `close --outcome --reason`.
  - `set-source --source`.

**Tests:**
- [ ] `add` with a legacy stage ("Screen") stores "Recruiter Screen". An unknown stage exits 1 and lists the valid stages. `add` without `--source` fails, and an invalid source fails.
- [ ] `update-status` with an outcome name (e.g. "Rejected") is rejected with a hint to use `close`.
- [ ] `close` requires a valid `--outcome`, and the closed table has `Outcome`.
- [ ] A v0.1 table (6 columns) loads with Source "". After `update-status` the file has 7 columns. A v0.1 closed table loads, and `close` rewrites it with 8 columns.
- [ ] Event log: `add` → type `add` with `to`, `source`. `update-status` stage change → `stage` with from/to. Same stage → no event. `record-event` → no event. `close` → `close` with from and outcome. `set-source` → `source`. Every event has `ts` (seconds) and `inferred: false`.
- [ ] A company `Bed | Bath, "Inc"` round-trips through the event log.
- [ ] Update the existing tests to pass `--source` and the new stage and outcome rules.
- [ ] Run `python3 -m unittest tools.test_tracker` and commit.

### Task 2: tracker.py — `export --json`, `backfill`, fixture workspace

**Files:** Modify `tools/tracker.py` and `tools/test_tracker.py`. Create `dashboard/fixtures/workspace/{tracker.md,tracker_closed.md,tracker_events.jsonl,opportunity/*/*/notes.md}`, `dashboard/fixtures/export.json`, `dashboard/fixtures/make_fixture.py` (deterministic generator, about 30 opportunities).

**Produces:**
- `export_data() -> dict`, with keys `schema, stages, outcomes, sources, active, closed, events, warnings`. Row keys are snake_case: `company, role, slug, stage, source, last_activity, next_action, next_action_date` (+ `outcome` on closed rows).
- `backfill --events-file PATH`, with input `[{company, role, type, ts, from?, to?, outcome?, source?}]`.

**Tests:**
- [ ] `export --json` on a temp copy of the fixture equals `dashboard/fixtures/export.json`.
- [ ] Malformed JSONL lines and unmapped stages appear in `warnings`, and the exit code is 0.
- [ ] Rows in legacy stages are exported with their canonical name.
- [ ] `backfill` writes events with `inferred: true`, and a second run appends nothing (dedup on company-slug, role-slug, type, from, to, date).
- [ ] `backfill` with a `source` entry for a row that has an empty Source fills it in. It never overwrites a non-empty Source.
- [ ] `backfill` rejects entries with invalid stages, outcomes or sources, and writes nothing if any entry is invalid (all-or-nothing).
- [ ] Commit.

### Task 3: Skills, guidance, migrate

**Files:**
- Modify: `skills/score-opportunity/SKILL.md`, `skills/interview-review/SKILL.md`, `skills/morning-scan/SKILL.md`, `skills/migrate/SKILL.md`, `guidance/persona.md`, `tools/migrate.py`, `tools/test_migrate.py`, `tools/test_skills.py`.
- Create: `skills/backfill-history/SKILL.md`.

**Tests:**
- [ ] `test_skills.py`:
  - Every `tracker.py" add` invocation in skills includes `--source`.
  - Every `close` invocation includes `--outcome`.
  - The `backfill-history` skill references `tracker.py" backfill`.
- [ ] `migrate.py` prints a report of stage names in the copied trackers that aren't canonical or mappable. It never changes them.
- [ ] Run the whole suite and commit.

### Task 4: Dashboard scaffolding, shared types, `derive.ts`

**Files:** Create:
- `dashboard/package.json` with scripts `build`, `typecheck`, `test`.
- `dashboard/tsconfig.json` (server + shared + tests, `noEmit`, `erasableSyntaxOnly`, `allowImportingTsExtensions`).
- `dashboard/tsconfig.web.json` (shared + web/src → web/dist, DOM lib).
- `dashboard/shared/types.ts`, `dashboard/server/derive.ts`, `dashboard/test/derive.test.ts`.
- `.gitignore` gains `dashboard/node_modules/`.

**Produces** (`shared/types.ts`):
```ts
export type Export = { schema: number; stages: string[]; outcomes: string[]; sources: string[];
  active: ExportRow[]; closed: ExportRow[]; events: TrackerEvent[]; warnings: string[] };
export type OpportunityRecord = { company: string; role: string; slug: string; source: string;
  status: "active" | "closed"; path: PathStep[]; outcome: string | null; addedAt: string;
  lastActivity: string; stalled: boolean; stage: string; nextAction: string; nextActionDate: string };
export type Payload = { records: OpportunityRecord[]; stages: string[]; outcomes: string[];
  sources: string[]; stallDays: number; warnings: string[]; generatedAt: string };
```
`derive(exp: Export, opts: { stallDays: number; now: Date }): Payload`.

**Tests:**
- [ ] The path is built from events in order.
- [ ] With no events, the path falls back to the current stage, marked inferred.
- [ ] `stalled` is false at `stallDays - 1` days and true at `stallDays`. Closed opportunities are never stalled.
- [ ] Only events after the last `add` count (re-added opportunity).
- [ ] Orphan events are dropped with a warning.
- [ ] Unknown stages are kept.
- [ ] Commit.

### Task 5: `shared/aggregate.ts`

**Files:** Create `dashboard/shared/aggregate.ts`, `dashboard/test/aggregate.test.ts`.

**Produces:**
- `applyFilters(records, filters: Filters, now: Date) → OpportunityRecord[]`, where `Filters = { range: "30" | "90" | "all"; sources: string[]; status: "active" | "closed" | "all" }` (an empty `sources` means all).
- `sankey(records, payload) → { nodes: {id, label, kind}[]; links: {source, target, value, allInferred, recordKeys: string[]}[] }`.
- `conversion(records, stages) → {from, to, reached, advanced, rate, medianDays, p75Days, n}[]`.
- `activity(records) → {week: string; added: number; advanced: number; closed: number}[]`.
- `summary(records) → {total, active, offers, appliedToOffer, stalled}`.
- `recordKey(r) = r.slug`.

**Tests:**
- [ ] Sankey flow is conserved at every intermediate node.
- [ ] Skipped stages link directly to the next stage reached.
- [ ] `allInferred` is set correctly.
- [ ] End nodes: outcome for closed, `Still in X` for active, `Stalled in X` for stalled.
- [ ] Filters combine with AND across filter types and OR within sources.
- [ ] Median and p75 are right for n = 1, 2, 3 and 4.
- [ ] ISO weeks bucket correctly across 2025-12-29 … 2026-01-04 (2026-W01).
- [ ] Summary counts are right.
- [ ] Commit.

### Task 6: Server (`exporter.ts`, `http.ts`, `main.ts`)

**Files:** Create `dashboard/server/{exporter.ts,http.ts,main.ts,config.ts}`, `dashboard/test/http.test.ts`.

**Produces:**
- `runExport(pluginRoot, workspace, cmd?) → Promise<Export>`. It throws an `ExportError` with `detail`, and `cmd` is overridable for tests.
- `createServer({ workspace, webRoot, getPayload, idleMs, now? }) → { server, listen(port): Promise<number>, close() }`.
- `readStallDays(workspace) → number`.

**Tests** (real server on port 0):
- [ ] A bad Host header gets 403. POST gets 405.
- [ ] `/api/notes/<slug>` serves the file. Traversal via `..`, `%2e%2e` and encoded slashes, and a bad slug shape, get 400 or 404. A missing file gets 404.
- [ ] Static traversal attempts get 404.
- [ ] An export failure gets 500 with `detail`.
- [ ] The server closes after `idleMs` with no requests (short idle for the test).
- [ ] `runExport` against the fixture copy returns the expected record count.
- [ ] Commit.

### Task 7: Browser app

**Files:** Create:
- `dashboard/web/index.html`, `dashboard/web/style.css`.
- `dashboard/web/src/{app,filters,sankey,conversion,activity,drilldown,markdown,theme,dom}.ts`.
- `dashboard/web/vendor/{d3.min.js,d3-sankey.min.js,LICENSE-d3.txt,LICENSE-d3-sankey.txt}`.
- `dashboard/test/markdown.test.ts`.
- Build output: `dashboard/web/dist/**`.

**Tests:**
- [ ] `markdown.ts`: `<script>`, `<img onerror>`, `javascript:` links and raw HTML come out inert. Headings, lists, bold, code and links render.
- [ ] Build, then check in Chrome against the spec's manual checklist.
- [ ] Commit.

### Task 8: Launch skill, suite wiring, docs, version

**Files:**
- Create: `skills/dashboard/SKILL.md`.
- Modify: `tools/run_tests.sh`, `CLAUDE.md`, `README.md`, `.claude-plugin/plugin.json` (0.2.0).

**Steps:**
- [ ] `run_tests.sh`:
  - Runs `npm ci` if needed, then `npm test`.
  - Rebuilds dist into a temp dir and diffs it against the committed dist.
  - The static checks also cover `node ... dashboard/server/main.ts` references needing `${CLAUDE_PLUGIN_ROOT}`.
- [ ] Run `claude plugin validate .`.
- [ ] Run the full suite and commit.

### Task 9: End-to-end verification

- [ ] Start the server via the skill's command against a temp copy of the fixture, and run the manual checklist in Chrome, including the empty and no-events workspaces.
- [ ] Fix whatever is found, then run a final full-suite pass.
