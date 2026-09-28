# job-search-os plugin — design

Date: 2026-09-28
Status: approved in conversation, pending written-spec review

## Intent

Hard-fork the `job-search-os` skills (source: `~/code/job-search-os`, commit
`9ef2456`) into a Claude Code **plugin** that is publicly distributable and
**completely separates code from state**. The plugin is installed once;
each user's personal data lives in a *workspace* folder the plugin code never
lives in. The original repo is left untouched.

### Decisions (from interview)

| Topic | Decision |
|---|---|
| Audience | Public distribution |
| State location | Workspace = the folder Claude is run in (cwd) |
| Activation | Marker-scoped: hooks act only inside a workspace |
| Existing data | Ship a migration tool + skill |
| Workspace layout | Flat at workspace root (no `state/` subfolder) |
| Distribution | New GitHub repo `jimkrygowski/job-search-os-plugin`, which is its own one-plugin marketplace; PolyForm Noncommercial 1.0.0; README keeps a short author section |
| Also listable elsewhere | Yes: plugin at repo root, installable from any marketplace via a `github` source |
| Skill changes | Port only: change what the plugin structure requires, nothing else |
| `file-unemployment-claim` | Include, generalized (no personal references; explicitly MA DUA-only) |
| Git history | Fresh repo; initial commit notes the fork point |

### Success criteria

1. `claude plugin validate .` passes for the repo (plugin + marketplace).
2. Every ported tool test suite passes, plus new tests for workspace
   resolution, migration, and both hooks. Stdlib only, no pip dependencies.
3. No plugin file references `state/` paths or bare `tools/...` invocations
   (a grep check proves it).
4. In a fresh temp workspace, loading the plugin with `--plugin-dir`:
   the SessionStart hook injects the persona + bootstrap nudge; outside a
   workspace it injects nothing.
5. The PreToolUse hook denies Gmail send/reply/forward inside a workspace
   and allows them outside one.
6. `migrate.py` reproduces the original `state/` tree in a workspace
   without overwriting anything, and the migrated workspace's tracker is
   readable by the ported `tracker.py`.
7. The plugin writes nothing outside the workspace, and nothing into
   `${CLAUDE_PLUGIN_ROOT}`.

## Architecture

### Repository layout (plugin root = repo root)

```
.claude-plugin/
  plugin.json                 name "job-search-os", version, description, author, license, homepage/repository
  marketplace.json            name "job-search-os", owner, one entry: {name "job-search-os", source "./"}
skills/
  bootstrap/  build-profile/  define-trajectory/  offer-negotiator/
  score-opportunity/  tailor-resume/  company-research/  interview-prep/
  interview-review/  career-coach/  morning-scan/  file-unemployment-claim/
  migrate/                    (new)
commands/
  summarize-call.md
hooks/
  hooks.json                  SessionStart + PreToolUse
guidance/
  persona.md                  former CLAUDE.md content (persona, guardrails, data-file map, contacts rule)
tools/
  workspace.py                (new) workspace discovery
  tracker.py  score_table.py  option_value.py  gmail_extract.py  check_bootstrap_state.py
  session_start.py            (new) SessionStart hook entry point
  guard_send.py               (new) PreToolUse hook entry point
  migrate.py                  (new)
  test_*.py                   one per module
  run_tests.sh                runs the whole suite
docs/superpowers/specs|plans/ this spec and its plan
README.md  LICENSE  CLAUDE.md (developer notes for working ON the plugin)  .gitignore
```

Resources that skills reference (`career-coach/research.md`,
`offer-negotiator/research.md`, `research-source.md`,
`morning-scan/job_alert_sources.template.md`) move with their skills.

Not carried over: `.obsidian/`, `.DS_Store`, `__pycache__`,
`bootstrap-planning.md`, the original `docs/superpowers/` history,
`.claude/settings.json` (replaced by hooks).

### Workspace

A workspace is any directory that contains `.job-search-os.json`:

```json
{ "schema": 1, "created": "2026-09-28" }
```

Flat layout at the workspace root, identical to the original's `state/`
contents:

```
.job-search-os.json
career/profile.md  career/trajectory.md  career/comp_target.md
career/job_alert_sources.md  career/resume/master_resume.md
opportunity/<company_slug>/<role_slug>/...
tracker.md  tracker_closed.md  .tracker.lock (transient)
```

Users may make the workspace its own (private) git repo; bootstrap offers
`git init` but does not require it.

### `tools/workspace.py`

- `find_root(start: Path | None = None) -> Path | None`: walks up from
  `start` (default: cwd) to the filesystem root, returning the first
  directory that contains `.job-search-os.json`.
- `require_root() -> Path`: `find_root()` or exit 2 with the message
  `error: not inside a job-search-os workspace (no .job-search-os.json found
  from <cwd> upward). Run the bootstrap skill to create one, or cd into your
  workspace.`
- `init_root(path: Path) -> Path`: writes the marker if absent (idempotent,
  never overwrites) and returns the path.
- `MARKER = ".job-search-os.json"`.

Every tool resolves every state path as `require_root() / <relative path>`,
computed at call time (not import time), so tests can chdir freely. The
tools keep their existing CLIs; only path resolution changes
(`tracker.py opportunity-path` now prints an absolute path). Tools are
imported by one another via their own directory (`sys.path` insertion of
`Path(__file__).parent`), so they work when invoked from any cwd.

### Invocation from skills

Every `python3 tools/<x>.py` in skill/command Markdown becomes
`python3 "${CLAUDE_PLUGIN_ROOT}/tools/<x>.py"`. Claude Code substitutes the
variable when it loads the skill. Every `state/<path>` reference becomes the
workspace-relative `<path>`, described as "in the workspace".
Cross-skill references use the plugin's skill names unchanged (Claude
resolves `bootstrap` → `job-search-os:bootstrap`).

No `bin/` directory: a plugin with `bin/` cannot be installed in claude.ai
or Cowork.

### Hooks (`hooks/hooks.json`, exec form)

Both hooks decide scope from `CLAUDE_PROJECT_DIR` (falling back to the
stdin `cwd`) via `workspace.find_root`. Outside a workspace they exit 0
with no output.

**SessionStart** → `python3 ${CLAUDE_PLUGIN_ROOT}/tools/session_start.py`
- Inside a workspace, prints JSON
  `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": <text>}}`
  where `<text>` = `guidance/persona.md` + the bootstrap-completeness note
  from `check_bootstrap_state.py` (unchanged logic, flat paths), if any.
- Outside a workspace: nothing. The skills stay available; `bootstrap`
  creates a workspace.

**PreToolUse**, matcher `mcp__.*Gmail.*__(send_message|reply|forward)$`,
→ `python3 ${CLAUDE_PLUGIN_ROOT}/tools/guard_send.py`
- Inside a workspace, prints a `permissionDecision: "deny"` with reason
  "job-search-os: sending correspondence is disabled in job-search
  workspaces; draft instead."
- Outside: exits 0, no output (defers to normal permissions).
- `guard_send.py` re-checks `tool_name` against the same pattern (defense
  in depth against matcher drift).

Persona guardrail #3 is rewritten to describe this truthfully: enforced by
a plugin hook for Gmail-connector send tools in workspaces; instruction-level
for every other channel. The README says the same.

The original ran a hook with a relative `tools/` path; plugin hooks must
use `${CLAUDE_PLUGIN_ROOT}`, which is why the hooks move to exec form.

### Persona delivery

Plugins can't ship a `CLAUDE.md` that applies to the user's project, so
the former `CLAUDE.md` content becomes `guidance/persona.md`, injected by
SessionStart. Edits in the port: `state/` → workspace-relative paths; tool
paths → `${CLAUDE_PLUGIN_ROOT}` form written as "the plugin's
`tools/tracker.py`"; the "State Directory" section is rewritten to describe
the workspace/marker model; the settings.json reference becomes the hook.
The repo's own `CLAUDE.md` is developer guidance for editing the plugin.

### Skills: port rules

Port-only. For each skill/command:
1. `state/X` → `X` (workspace-relative), wording adjusted minimally.
2. `python3 tools/X.py` → `python3 "${CLAUDE_PLUGIN_ROOT}/tools/X.py"`.
3. References to `CLAUDE.md` → "the job-search-os persona/guardrails".
4. References to `.claude/settings.json` deny rules → the plugin hook.
5. `description` frontmatter keeps the same trigger semantics.

Skill-specific changes:
- **bootstrap**: new step 0. If `workspace.find_root()` is None, tell the
  user bootstrap will make the current directory a job-search workspace,
  confirm, run `python3 "${CLAUDE_PLUGIN_ROOT}/tools/workspace.py" init`,
  and offer (not require) `git init` plus a note to keep it private. If the
  user has an existing job-search-os checkout, point to `migrate` instead.
  Then continue with the existing flow.
- **morning-scan**: template path → `${CLAUDE_PLUGIN_ROOT}/skills/morning-scan/job_alert_sources.template.md`.
- **file-unemployment-claim**: "Jim"/"his" → "the user"/"their";
  description states it covers only the Massachusetts DUA weekly
  certification; the flow, hard limits, and URLs are unchanged;
  `state/` → workspace paths.
- **migrate** (new): asks for the old repo path, runs
  `migrate.py --from <path> --dry-run`, shows the plan, confirms, runs it,
  reports results, then suggests the user start a session in the workspace.

### `tools/migrate.py`

`python3 migrate.py --from <old-repo> [--to <workspace>] [--dry-run]`
- `--to` defaults to cwd. Source = `<old-repo>/state`, or `--from` itself if it
  is a state folder (contains `career/`, `opportunity/`, or `tracker.md`);
  exits 2 otherwise.
- Copies every file under source into `--to`, preserving relative paths,
  skipping `.tracker.lock`, `.DS_Store`, and `__pycache__`.
- Never overwrites: if any destination file exists, it lists the conflicts
  and exits 1 **before copying anything** (all-or-nothing preflight).
- Writes the marker via `workspace.init_root`. Prints a summary (file count,
  top-level dirs). `--dry-run` prints the plan and writes nothing.
- Read-only on the source.

### Error handling

- Tools outside a workspace: exit 2, with the message above; skills tell
  the user to run bootstrap or cd into the workspace.
- Hooks never fail a session. Any exception → exit 0 with no output, and
  a one-line message on stderr. Exception: `guard_send.py` **denies** on
  any internal error or unreadable input (fail closed — its matcher
  already limits it to send tools).
- Tracker lock semantics unchanged; the lock file lives in the workspace root.

## Testing

- Port the five existing suites (`tracker`, `score_table`, `option_value`,
  `gmail_extract`, `check_bootstrap_state`). Fixtures create a temp dir
  with a marker and chdir into it instead of creating `state/`.
- New: `test_workspace.py` (find from root, from nested subdir, none
  found, `init` idempotent), `test_migrate.py` (copy, skip list, conflict
  preflight writes nothing, dry-run writes nothing, missing source),
  `test_session_start.py` (in/out of workspace, JSON shape, incomplete
  profile note included), `test_guard_send.py` (deny inside, silent
  outside, non-matching tool silent, internal error fails closed).
- `tools/run_tests.sh`: `python3 -m unittest discover -s tools -p 'test_*.py'`.
- Static check (in `run_tests.sh`): grep over `skills/ commands/ guidance/
  hooks/` fails if it finds `state/` or a `python3 tools/` without
  `${CLAUDE_PLUGIN_ROOT}`.
- Integration: `claude plugin validate .`; a smoke session with
  `claude --plugin-dir . -p` in a temp workspace that confirms the persona
  context is present and a skill runs `tracker.py list`; a migration of a
  **copy** of the real `~/code/job-search-os/state` into a temp workspace,
  followed by `tracker.py list`.

## Distribution

- `plugin.json` is the single source of metadata; version starts at
  `0.1.0`, with a matching git tag `v0.1.0`.
- Install: `/plugin marketplace add jimkrygowski/job-search-os-plugin`, then
  `/plugin install job-search-os@job-search-os`.
- README section "List it in your own marketplace" with the
  `{"source": "github", "repo": "jimkrygowski/job-search-os-plugin"}`
  entry and optional `ref`/`sha` pinning.
- The plugin name `job-search-os` is a stable public identifier: don't rename it.
- GitHub repo creation and push happen only after explicit user
  confirmation (public, outward-facing).

## Out of scope

Behavior changes to skills; CI; `bin/` executables; carrying over the
original's docs/plans; submission to Anthropic's directory; changes to the
original repo; moving the user's real data (the user runs migrate
themselves, or asks for it explicitly).
