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
