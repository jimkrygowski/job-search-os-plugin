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
- Python tools and tests are stdlib only. The dashboard server uses only
  Node built-ins at runtime; npm packages are dev-only (typescript, type
  definitions). Run everything with `tools/run_tests.sh`.
- Dashboard (`dashboard/`): TypeScript run directly by Node >= 22.18, so
  server code must use erasable syntax only (tsconfig enforces it). The
  browser code is compiled: after changing `dashboard/web/src` or
  `dashboard/shared`, run `npm run build` in `dashboard/` and commit
  `dashboard/web/dist` — `run_tests.sh` fails on a stale build.
- UI changes: run `npm run test:e2e` in `dashboard/` (Playwright, real
  browser against temp copies of the fixture). Assert what the user sees
  (visibility, focus), not DOM properties — a `hidden` drawer that stayed
  on screen passed a property check.
- The dashboard reads tracker state only via `tracker.py export --json`,
  never by parsing the markdown. `dashboard/fixtures/export.json` is the
  contract both test suites check; regenerate it with
  `dashboard/fixtures/make_fixture.py` when the export changes.
- Validate the manifest with `claude plugin validate .`; try it live with
  `claude --plugin-dir /path/to/this/repo` from inside a test workspace.
- `job-search-os` is a public identifier (install id + skill prefix). Don't rename it.
