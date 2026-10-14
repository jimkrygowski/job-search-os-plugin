---
name: relationships
description: Use when the user asks who to reach out to, wants to know about a person in their search, wants to log a conversation or an intro, or wants to set up the people import from their old contacts.md files.
---

# Relationships

## Purpose

Keep the people side of the search moving. Who is due for a touch, which
intros have stalled, and what is known about someone. Everything goes
through `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py"`. Never send
anything; draft notes only when asked.

## "Who should I reach out to?"

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" due --within 7d`.
2. For each person listed, run `people.py show "<slug>"` and read their
   page. Explain in a line why they're due: the last touch, what they're
   connected to, and anything open with them.
3. For stalled intros, say who owes the next step if the notes show it.
   Otherwise say it isn't known.
4. If the user wants, draft short notes. Never send them.

## "Tell me about <person>"

Run `people.py show "<person>"`, read `people/<slug>.md`, and summarize:
- who they are and their roles across opportunities;
- the touches and open intros;
- what the notes say, with dates.

If `show` reports more than one match, list the candidates and ask which.

## Logging

- **A conversation:** `people.py touch "<person>" --channel call|email|meeting|message|other --date <YYYY-MM-DD> --note "<what>"`.
- **An intro:**
  - `people.py intro offer "<from>" --to "<person>"` or `--to-org "<Org>"`, adding `--for <opportunity slug>` if it's for an opportunity;
  - then `intro made|met <id>`;
  - then `intro close <id> --result led_to_opportunity --opportunity <slug> | led_to_intros | dead_end`.
- **A duplicate person:** `people.py merge <keep> <drop>`. Confirm with the user first.

## Setting up the import (once)

For a workspace that still has hand-written `contacts.md` files or a
`networking.md`:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" import --draft`. It writes `people-import-draft.md` in the workspace.
2. Walk the user through the draft:
   - every `?` in Roles needs a role;
   - the *Same person?* suggestions need a decision;
   - rows to leave out can be deleted;
   - the overdue rows come first.

   Edit the draft as they decide, and don't guess roles.
3. Suggest committing the workspace first, if it is a git repo. Then run
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" import --apply people-import-draft.md`.
   If it reports errors, fix those rows and apply again. Nothing is
   written until the whole draft is valid.
4. Afterwards, the original files are kept as `contacts.hand-written.md`
   and `networking.hand-written.md`. Point the user to them for anything
   listed under *Unparsed*.

## Guardrails

- Never send anything. Draft only, whatever the channel.
- Never hand-edit a page's field block or any `contacts.md`.
- Don't set `relationship: yes` or a cadence without the user's say-so.
