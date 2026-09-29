---
name: backfill-history
description: Use when the user wants the dashboard to show how past opportunities moved through the pipeline, asks to "backfill history", or has opportunities from before stage history was recorded (the dashboard says "History isn't recorded yet"). Reconstructs past stage changes and sources from notes and tracker rows, confirms them with the user, and records them as inferred.
---

# Backfill Pipeline History

## Purpose

The tracker records every stage change in `tracker_events.jsonl`, but
only from the moment that log existed. This skill reconstructs the
earlier history (and any blank Source) once, from evidence already in the
workspace, so the dashboard's Sankey and timing views cover the whole
search. Everything it writes is marked `inferred`, and the dashboard draws
inferred history differently from recorded history.

## Steps

1. Get the current state:
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" export --json`
   Note which opportunities (active and closed) have no `add` event, and
   which have a blank `source`.
2. For each of those, resolve its folder with
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" opportunity-path "<Company>" "<Role>"`
   and read `notes.md` (and `jd.md` if present). Collect evidence:
   dated `## Interview Review (<date>)` headings, `**Closed (<date>):**`
   lines, dated entries that mention applying, a recruiter call, a hiring
   manager conversation, an onsite/loop, or an offer, and anything saying
   how the opportunity arrived (referral, recruiter, job alert, etc.).
3. Draft proposed events for each opportunity using only the canonical
   stages (Identified, Applied, Recruiter Screen, Hiring Manager, Interview
   Loop, Offer) and outcomes (Accepted, Rejected, Withdrew, Ghosted,
   Declined Offer):
   - one `add` (`to` = earliest known stage),
   - a `stage` event (`from`, `to`) for each later step,
   - a `close` event (`from` = last stage, `outcome`) for closed ones,
     matching the Outcome already in `tracker_closed.md`,
   - a `source` entry when the Source is blank and the evidence shows it.
   **Every event needs a date taken from the evidence.** If a step clearly
   happened but nothing dates it, leave it out and say so — never invent
   or interpolate a date.
4. Show the user one table per opportunity (stage, date, evidence quote)
   and ask about anything ambiguous: a missing source, a stage the notes
   don't settle, conflicting dates. Apply their corrections.
5. Write the confirmed entries to a temporary JSON file outside the
   workspace's tracked files, as a list of objects:
   `{"company", "role", "type": "add"|"stage"|"close"|"source", "ts": "YYYY-MM-DDTHH:MM:SS", "from"?, "to"?, "outcome"?, "source"?}`
   (use `T09:00:00` when only the date is known). Company and Role must
   match the tracker row as written.
6. Record them:
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" backfill --events-file "<file>"`
   It validates everything first and writes nothing if any entry is
   invalid — fix what it names and re-run. Re-running is safe: events
   already in the log are skipped. Blank Sources are filled; a Source the
   user already set is never overwritten.
7. Delete the temporary file and report how many events were added.
   Suggest opening the dashboard (`/job-search-os:dashboard`).

## Guardrails

- Never edit `tracker_events.jsonl`, `tracker.md` or
  `tracker_closed.md` directly — only through `tracker.py`.
- Never invent dates or stages. Missing history is better than false
  history.
- Don't change an opportunity's current stage or outcome here; if the
  evidence contradicts it, tell the user and let them decide.
