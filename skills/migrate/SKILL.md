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
   Pointing directly at its state folder also works.
2. Decide the destination: the current directory, unless the user names
   another. Confirm it with the user — it will become their workspace.
   If the current directory is the old checkout (or inside it), ask for a
   separate folder instead (e.g. `~/job-search`) — the tool refuses to
   migrate into the old checkout.
3. Preview:
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/migrate.py" --from "<old>" --to "<dest>" --dry-run`
   Show the user the file count and top-level folders.
4. If it reports conflicts (exit 1), show them and stop — never delete or
   overwrite workspace files to make room. Let the user decide.
5. If it reports a bad source (exit 2), tell the user what was expected
   and ask for the right path.
6. On confirmation, run the same command without `--dry-run`.
7. Verify: `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" list` run in
   the destination shows their pipeline. If the migration printed stage
   names that aren't on the canonical list, show them to the user and, for
   each unknown one, agree the right stage and set it with `update-status`.
   Then offer `backfill-history` so the dashboard can show each
   opportunity's path.
8. Tell the user to start future sessions from the workspace folder, and
   offer `git init` there (keep any remote private). If the destination
   isn't the current directory, tell them to restart Claude there so the
   persona and guardrails load. If it is the current directory, read
   `${CLAUDE_PLUGIN_ROOT}/guidance/persona.md` now and follow it for the
   rest of this session (the SessionStart hook ran before the workspace
   existed).

## Guardrails

- Never modify, move, or delete anything in the old checkout.
- Never overwrite existing workspace files.
