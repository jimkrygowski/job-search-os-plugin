---
name: dashboard
description: Use when the user wants to see their job search visually — the dashboard, charts, a Sankey of where opportunities went, conversion rates, time in stage, or weekly activity — or asks to "open the dashboard". Starts a local, read-only web dashboard for the current workspace and opens it in the browser.
---

# Job Search Dashboard

## Purpose

A read-only web page, served only on this computer (127.0.0.1), that
shows the pipeline for reflection:

- **Where opportunities go** — a Sankey from Source through the stages
  each opportunity reached to its outcome (or where it's sitting now).
- **Stage conversion and time in stage** — how many moved past each stage
  and how long they spent there.
- **Activity by week** — opportunities added, advanced and closed.

Filters (date added, source, status) and click-through to each
opportunity's timeline and `notes.md`. The dashboard never changes any
file.

## Steps

1. Find the workspace:
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/workspace.py" root`
   If it fails, the user isn't in a workspace — point them to the
   `bootstrap` skill (or to `cd` into their workspace) and stop.
2. Check Node: `node --version` must be **22.18 or newer** (the dashboard
   server runs TypeScript directly on Node, with no npm install). If Node
   is missing or older, say so plainly — the rest of the plugin only
   needs Python; only the dashboard needs Node — suggest installing a
   current LTS from nodejs.org (or `brew install node`), and stop.
3. Start the server **in the background** (Bash with
   `run_in_background`), so this session stays usable:
   `node "${CLAUDE_PLUGIN_ROOT}/dashboard/server/main.ts" --workspace "<workspace root>"`
   It prints `job-search-os dashboard: http://127.0.0.1:<port>/` once
   it's listening. Read that line from the background output. If it exits
   with an error instead, show the error and stop.
4. Open the URL in the browser (`open <url>` on macOS, `xdg-open <url>`
   on Linux, `start <url>` on Windows).
5. Tell the user:
   - the URL (it only works on this computer),
   - that the page reads the workspace fresh on every load — reload it
     after tracker changes,
   - how to stop it: ask you to stop it (stop the background task), and
     that it also shuts itself down after 2 idle hours.
6. If the page shows "History isn't recorded yet", or most of the flow is
   striped (reconstructed), suggest the `backfill-history` skill so past
   opportunities show their full paths.

## Guardrails

- Never pass a port or host that exposes it beyond 127.0.0.1; the server
  only binds locally and there is no option to change that.
- Don't start a second server if one from this session is still running —
  give the user the existing URL.
- Stalled opportunities (no activity for 21+ days, configurable as
  `"dashboard": {"stallDays": N}` in `.job-search-os.json`) are only
  shown, never closed. Closing is the user's decision.
