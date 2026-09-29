# job-search-os dashboard (v1: reflection) — design

Date: 2026-09-29
Status: approved in conversation, pending written-spec review

## Intent

Make the information a job search generates easier to see and understand.
A local web dashboard, shipped inside the plugin, visualizes how
opportunities move through the pipeline and where they end up.

The long-term audience covers four uses: reflecting on the search, driving
it day to day, sharing progress with others, and showcasing the plugin.
**v1 serves reflection only**: seeing patterns in your own search, such as
where opportunities stall, which sources convert, and how the pace of the
search changes over time. The other three uses are later phases (see Out of
scope).

### Decisions (from interview)

| Topic | Decision |
|---|---|
| v1 focus | Reflection |
| Views | Outcome Sankey, stage conversion + time-in-stage, activity over time |
| Stage history | New append-only event log, written by `tracker.py`, plus a one-time backfill that marks inferred events |
| Stage vocabulary | Fixed canonical ladder + terminal outcomes, enforced by `tracker.py`, with a legacy mapping |
| Source | New `Source` column with a fixed set of values, required on `add`, backfilled for existing rows |
| Stalled | Computed only in the dashboard (active + no activity for `stallDays`, default 21), never written to state |
| Delivery | Local server bound to `127.0.0.1`, reads the workspace live, launched by a skill |
| Language | All new dashboard code is TypeScript: server on Node (no runtime npm deps, `.ts` run directly), browser code compiled at development time with the output committed |
| Tracker access | The dashboard reads tracker state only through `tracker.py export --json`. It never parses tracker markdown itself |
| Chart library | d3 + d3-sankey, pinned and committed into the plugin (works offline) |
| Interaction | Filters (date range, source, status) and drill-down to opportunity + read-only `notes.md`. No editing |
| Deferred | Score vs. outcome view, daily-driving board, sharing/export, showcase mode, UI editing, phone layout |

### Success criteria

1. `tools/run_tests.sh` passes: the Python suite, the `node --test` suite,
   and the check that `dashboard/web/dist` matches a fresh build.
   `claude plugin validate .` passes.
2. On the fixture workspace (`dashboard/fixtures/workspace/`, about 30
   opportunities, mixed active and closed, some inferred history), the
   dashboard shows all three views, and the filters and drill-down behave as
   specified. This is verified manually in Chrome against the checklist in
   Testing.
3. The dashboard server writes nothing to the workspace or to
   `${CLAUDE_PLUGIN_ROOT}`, and rejects any request whose `Host` header is not
   `127.0.0.1:<port>` or `localhost:<port>`.
4. A v0.1 workspace (tracker tables without `Source`, no event log) works in
   v0.2 without running a migration: all tracker commands succeed and the
   dashboard shows it.

## Data model (Python, `tools/tracker.py`)

`tracker.py` remains the only code that writes tracker state.

### Canonical stages and outcomes

Ordered stages (the Sankey diagram's middle columns):

`Identified → Applied → Recruiter Screen → Hiring Manager → Interview Loop → Offer`

Terminal outcomes: `Accepted`, `Rejected`, `Withdrew`, `Ghosted`, `Declined Offer`.

- `STAGES` and `OUTCOMES` are module constants in `tracker.py`, exported in
  `export --json` so the dashboard never hard-codes them.
- `add` and `update-status` exit non-zero on a stage not in `STAGES`, after
  applying `LEGACY_STAGES`. The error message lists the valid stages.
- `LEGACY_STAGES` is a dict of known old names mapped to canonical ones (e.g.
  `"Phone Screen" → "Recruiter Screen"`, `"Onsite" → "Interview Loop"`).
  Stage names found in existing rows that nothing maps are **reported, never
  guessed**, by `export` (in `warnings`) and by backfill.
- `update-status` does not accept outcomes. Closing is always done with `close`.

### `close --outcome`

`close` gains a required `--outcome` (one of `OUTCOMES`). `--reason` stays
free text. The closed row keeps its last stage in `Stage`, and a new `Outcome`
column in `tracker_closed.md` records the outcome.

### Source column

Values: `Referral | Recruiter Inbound | Applied Cold | Warm Intro | Job Alert | Other`.

- Added as a column to both `tracker.md` and `tracker_closed.md`.
- `add` requires `--source`. A new `set-source <company> <role> --source X`
  command corrects it later.
- **Backward compatibility:** `parse_table` accepts tables with either the
  old or the new column set. Missing columns read as `""`. Every write uses
  the new column set, so a v0.1 table upgrades itself on its next write.
  Rows with any other column count are still an error.

### Event log: `tracker_events.jsonl`

A workspace-root file. It is append-only, and each line is one JSON object:

```json
{"ts":"2026-09-28T10:14:00","company":"Acme","role":"VP Eng","type":"stage","from":"Applied","to":"Recruiter Screen","inferred":false}
```

| `type` | Written by | Extra fields |
|---|---|---|
| `add` | `add` | `to` (initial stage), `source` |
| `stage` | `update-status` when the stage changes | `from`, `to` |
| `close` | `close` | `from` (last stage), `outcome` |
| `source` | `set-source` | `source` |

- Events are appended inside the existing `locked()` block, after the table
  write succeeds.
- `record-event` writes no event, because it changes only the next action.
- `update-status` with an unchanged stage writes no event.
- `ts` is local time, ISO 8601, to the second. `inferred` is always present.

### `export --json`

This prints one JSON document to stdout and is the dashboard's only view of
tracker state:

```json
{
  "schema": 1,
  "stages": ["Identified", "..."],
  "outcomes": ["Accepted", "..."],
  "sources": ["Referral", "..."],
  "active": [{"company": "...", "role": "...", "slug": "acme/vp_eng", "stage": "...", "source": "...", "last_activity": "...", "next_action": "...", "next_action_date": "..."}],
  "closed": [{"...": "same as active, plus", "outcome": "..."}],
  "events": [{"...": "event log lines, in file order"}],
  "warnings": ["line 12 of tracker_events.jsonl is not valid JSON", "..."]
}
```

- `slug` is `<slugify(company)>/<slugify(role)>`: the opportunity folder
  relative to `<workspace>/opportunity/`.
- Malformed event lines are skipped and listed in `warnings`. Unmapped stage
  names are also listed there.
- A malformed tracker table is still a hard error (exit non-zero), as today.

### Backfill

- `tracker.py backfill --events-file <path>` takes a JSON list of proposed
  events and `source` assignments. It writes each one with `"inferred": true`
  and skips any event already in the log (same company, role, type, from/to,
  and date). Running it twice therefore adds nothing.
- The new **`backfill-history` skill** gathers the proposals. It reads each
  opportunity's `notes.md` (dated entries, stage mentions, `**Closed (date):**`
  lines) and tracker rows, drafts events and a Source for each opportunity,
  shows them to the user as a table, asks about anything ambiguous, then
  calls `backfill`. It never invents dates. An event without evidence for its
  date is left out and the user is told why.

### Skill and guidance updates

- `score-opportunity`: passes `--source`, asking the user if it isn't obvious from context.
- `interview-review`: picks the next stage from the canonical list.
- `morning-scan`: mentions opportunities that have stalled (same rule as the dashboard) as candidates to follow up on or close.
- `guidance/persona.md`: the data-file map gains `tracker_events.jsonl`, and closing guidance requires `--outcome`.
- `migrate`: maps legacy stages through `LEGACY_STAGES` and reports anything unmapped.

## Dashboard (TypeScript)

### Layout

```
dashboard/
  package.json        devDependencies only: typescript, @types/d3, @types/d3-sankey, @types/node
  tsconfig.json       strict; browser build: shared/ + web/src → web/dist
  shared/
    types.ts          the /api/data contract (Payload, OpportunityRecord, Filters, ...)
    aggregate.ts      pure: records + filters → chart data
  server/
    main.ts           CLI entry: args, workspace check, start, idle shutdown
    http.ts           routing, Host check, static files, notes endpoint
    derive.ts         pure: export JSON + config + now → Payload
    exporter.ts       runs `python3 tools/tracker.py export --json`
  web/
    index.html
    src/              app.ts, filters.ts, sankey.ts, conversion.ts, activity.ts,
                      drilldown.ts, markdown.ts, theme.ts
    dist/             compiled output, committed
    vendor/           d3.min.js, d3-sankey.min.js, LICENSE files (pinned versions)
  fixtures/
    workspace/        fixture workspace for tests and manual checks
    export.json       golden export shared by the Python and TS tests
  test/               *.test.ts (node --test)
```

The server runs on Node ≥ 22.18, which executes `.ts` files directly by
stripping types. Server code therefore uses only erasable TypeScript syntax
(no `enum`, no `namespace`, no parameter properties), which `tsconfig`
enforces with `erasableSyntaxOnly`. `tsc --noEmit` type-checks the server
code as part of the test run.

### Data flow

1. **Export.** Each `GET /api/data` runs `exporter.ts`, which calls `python3
   "${pluginRoot}/tools/tracker.py" export --json` with the workspace as cwd.
   Typical workspaces are small (hundreds of rows at most), so there's no
   caching.
2. **Derive.** `derive.ts` builds one `OpportunityRecord` per opportunity:
   ```ts
   { company, role, slug, source, status: "active" | "closed",
     path: { stage: string; ts: string; inferred: boolean }[],
     outcome: string | null, addedAt: string, lastActivity: string, stalled: boolean }
   ```
   - `path` comes from that opportunity's events, in order.
   - With no events, the path is just the current stage, dated
     `last_activity` and marked `inferred: true`.
   - `addedAt` is the `add` event's date, or else the first path entry's.
   - `stalled` is true when the opportunity is active and
     `today - lastActivity >= stallDays`. `now` is injected for testing.
   - `stallDays` comes from `.job-search-os.json` → `dashboard.stallDays` (default 21).
3. **Payload.** The server responds with
   `{ records, stages, outcomes, sources, stallDays, warnings, generatedAt }`.
4. **Aggregate (browser).** `aggregate.ts` takes records + filters and
   produces:
   - **Sankey:** nodes are Source → each stage reached → an end node: the
     outcome if closed, else `Still in <stage>` (with stalled ones split out
     as `Stalled in <stage>`). Links carry `count` and `allInferred` (true
     when every contributing transition was inferred). Paths that skip a
     stage link straight to the next stage reached; no placeholder nodes.
   - **Conversion:** for each consecutive pair of canonical stages, how many
     reached the first, how many then reached any later stage, the rate, and
     the median and p75 days spent in the first stage (only from
     opportunities that have both timestamps).
   - **Activity:** ISO-week buckets of `added`, `advanced` (stage events),
     and `closed`.

   Filtering happens in the browser, so changing a filter is instant and the
   server stays stateless.

### Server

- The command is `node dashboard/server/main.ts --workspace <root> [--port N]`.
  - The default port is 0, meaning the OS picks one. The server prints
    `job-search-os dashboard: http://127.0.0.1:<port>/` on startup.
  - It exits non-zero with a clear message if `<root>` has no
    `.job-search-os.json`.
- It binds to `127.0.0.1` only.
- Every request's `Host` header must equal `127.0.0.1:<port>` or
  `localhost:<port>`. Anything else gets 403, which blocks DNS rebinding.
- Only GET requests are accepted; anything else gets 405. No CORS headers
  are sent.
- Routes:
  - `/`, `/dist/*`, `/vendor/*`: static files from `dashboard/web`, with
    paths resolved and checked to stay under that directory.
  - `/api/data`: the payload above. An export failure returns 500 with
    `{error, detail}`, where `detail` is the command's stderr.
  - `/api/notes/<slug>`: raw text of `<workspace>/opportunity/<slug>/notes.md`.
    - The slug must match `^[a-z0-9_]+/[a-z0-9_]+$`.
    - The resolved path must stay under `<workspace>/opportunity/`.
    - A missing file returns 404.
- The server writes no files. It shuts down after 2 hours without a request
  (the clock is injectable for tests) and on SIGINT or SIGTERM.

### Frontend

**Layout.** A single page, laid out for laptop width and wider.

1. **Filter bar** (sticky):
   - Added-date range, with presets for 30 days, 90 days and all time.
   - Source chips (multi-select).
   - Status: Active / Closed / All.
   - All views redraw on any change. The filter state is kept in the URL
     hash, so a view can be bookmarked.
2. **Summary strip:** total opportunities, active, offers, Applied→Offer
   conversion, and the stalled count.
3. **Outcome Sankey diagram** (d3-sankey).
   - Links where `allInferred` is true are drawn dashed.
   - Stalled end nodes use a muted color.
   - Labels are drawn on the nodes.
4. **Stage conversion and time:**
   - One row per transition: a conversion bar and median/p75 days.
   - `n` is shown on each row. Rows with `n < 5` are visually de-emphasized
     and marked "small sample."
5. **Activity over time:** a weekly column chart of added, advanced and
   closed opportunities.

Every chart has a "show as table" toggle that renders the same aggregate as
an HTML table.

**Drill-down.**
- Clicking a Sankey node or link, or a conversion row, opens a side panel
  listing the opportunities it covers.
- Selecting one shows its tracker fields, a dated stage timeline (with
  inferred steps marked), and its `notes.md`.
- `markdown.ts` renders a small subset of markdown: headings, lists,
  bold/italic, inline code, code blocks and links. **The input is
  HTML-escaped first, and raw HTML is never passed through.** Links are
  limited to `http:`, `https:` and `mailto:`, and open with
  `rel="noopener noreferrer"`.

**Visual design.**
- Follows the `dataviz` skill:
  - One categorical palette with a fixed color per outcome and per source,
    kept the same across views.
  - Light and dark themes via `prefers-color-scheme`.
  - Direct labels rather than color-only encoding.
- All controls and chart elements are keyboard-reachable, and the side panel
  traps focus while it's open.

**Empty and degraded states.**
- **No opportunities:** a message pointing to `score-opportunity`.
- **Opportunities but no events:** the views still render from each
  opportunity's current stage, and a banner says "History isn't recorded yet.
  Run backfill-history to see full paths."
- **`warnings` not empty:** a dismissible notice listing them.
- **`/api/data` fails:** an error banner with the detail text.

### Launch skill: `dashboard`

`skills/dashboard/SKILL.md` (invoked as `/job-search-os:dashboard`):

1. Resolve the workspace root with `python3 "${CLAUDE_PLUGIN_ROOT}/tools/workspace.py" root`.
   If there is none, stop and point to bootstrap.
2. Check that `node --version` is ≥ 22.18. If it isn't, explain the
   requirement and stop.
3. Start `node "${CLAUDE_PLUGIN_ROOT}/dashboard/server/main.ts" --workspace <root>`
   in the background, read the URL it prints, and open it in the browser.
4. Tell the user the URL, how to stop the server, and that it stops itself
   after 2 idle hours.
5. If the export reports no events, suggest `backfill-history`.

## Testing

### Python (`tools/test_tracker.py`, extended)

- Stage validation: canonical stages are accepted, legacy names are mapped,
  and unknown names are rejected with a message listing the valid stages.
- `close` requires a valid `--outcome` and records it in the `Outcome` column.
- Tables without `Source`/`Outcome` load, and are rewritten with the new
  columns on the next write.
- Each writing command appends exactly the specified event. `record-event`
  and `update-status` with an unchanged stage append nothing.
- `export --json` on `dashboard/fixtures/workspace` matches
  `dashboard/fixtures/export.json` exactly, apart from volatile fields,
  which are normalized. This is the shared contract with the TS tests.
- Malformed event lines end up in `warnings`, not in a crash.
- Running `backfill` twice with the same input leaves the log unchanged.

### TypeScript (`dashboard/test/*.test.ts`, `node --test`)

- **`derive`:**
  - Builds paths from events.
  - Falls back to the current stage when there are no events.
  - `stalled` flips exactly at `stallDays`.
  - Warnings pass through.
- **`aggregate`:**
  - Flow into each Sankey node equals flow out, except at sources and ends.
  - Skipped stages link directly to the next stage reached.
  - `allInferred` is set correctly.
  - Filters combine correctly (AND across filter types, OR within source).
  - Median and p75 are right for n = 1, 2 and even/odd counts.
  - ISO weeks bucket correctly across a year boundary.
- **`markdown`:** `<script>`, `<img onerror>`, `javascript:` links and raw
  HTML all come out inert.
- **`http`** (with a real server on an ephemeral port):
  - A bad `Host` header gets 403.
  - Non-GET requests get 405.
  - `../` and URL-encoded traversal attempts on both the notes and static
    routes are rejected.
  - An export failure returns 500 with the detail.
  - Idle shutdown works with an injected clock.

### Build and suite wiring

- `npm run build` runs `tsc` for the browser project into `web/dist`.
- `npm test` runs `tsc --noEmit` (server + tests) and then `node --test`.
- `tools/run_tests.sh` also:
  - Runs `npm test` in `dashboard/`, after `npm ci` if `node_modules` is
    missing.
  - Rebuilds `web/dist` into a temp directory and fails if it differs from
    the committed `dist`.
  - Applies the existing check against `state/` and bare `tools/` references
    to `skills/dashboard` and `skills/backfill-history`.

### Manual check (Chrome, fixture workspace)

1. All three views render with no console errors.
2. Changing each filter updates all views and the URL hash.
3. Clicking a Sankey node, a Sankey link and a conversion row each opens the
   side panel with the right opportunities.
4. Notes render, and a fixture note containing `<script>` shows as text.
5. Dashed inferred links and stalled nodes are visible and distinct.
6. "Show as table" works for each chart.
7. Both light and dark themes are readable.
8. Pointing the dashboard at an empty workspace, and at one with no events,
   shows the right empty and degraded states.

## Rollout

- Released as plugin v0.2.0.
- Existing workspaces need no migration step. Tables gain columns on their
  next write, and history starts building from the next tracker command.
  `backfill-history` is recommended once, but not required.
- **README:** a Dashboard section covering what it shows, the Node ≥ 22.18
  requirement (only for the dashboard), how to launch it, and the backfill
  recommendation.
- **CLAUDE.md:** the "Tools and tests are stdlib only" rule becomes: *Python
  tools and tests are stdlib only. The dashboard server uses only Node
  built-ins at runtime. npm packages are dev-only (typescript, type
  definitions). Commit `dashboard/web/dist` after `npm run build`.*

## Out of scope for v1

- A daily-driving pipeline board (due, overdue and stale actions).
- A shareable, redacted snapshot export.
- A showcase/demo mode with sample data.
- A score vs. outcome view.
- Any editing from the UI. The server stays read-only.
- A phone layout.
- Multi-workspace or multi-user support, and any non-localhost access.
