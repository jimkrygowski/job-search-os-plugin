---
name: interview-prep
description: Use when a user has an upcoming interview or call and wants a prep briefing, or wants to rehearse answers for one. Reads the opportunity's jd.md, notes.md (and the interview files it links), contacts.md, career/trajectory.md and career/talking_points.md, and writes the briefing into that interview's own file under prep/.
---

# Interview Prep

## Purpose

Produce a prep briefing ahead of a specific interview session, saved in
that session's own file, and help the user rehearse.

The briefing is a best guess at where the conversation will go, not a
script. Interviewers go their own way; the point is to have the user ready,
not to hold them to a plan.

## Session Start

1. Identify which opportunity this is for, and resolve its folder via
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" opportunity-path "<Company>" "<Role>"` — never
   construct the path yourself from the typed Company/Role.
2. Read from that folder: `jd.md`, `notes.md`, and `contacts.md`. `notes.md`
   links each earlier interview's file under an `## Interview (<date>): <who>`
   heading (files in `prep/`) — read those too. They hold earlier prep,
   rehearsed answers and reviews, which is what a later round builds on.
3. Read `career/trajectory.md`, `career/profile.md`,
   `career/resume/master_resume.md`, and `career/talking_points.md` if it
   exists (the user's settled answers to questions that come up in every
   interview — see Talking Points below).
4. For each person in `contacts.md`, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" show "<slug>"` and read their
   page `people/<slug>.md`. The page holds their notes from every opportunity
   they've been part of, not just this one.
5. Work out the session(s). One file per interview session — one
   conversation with one set of people. A loop day with three sessions with
   different interviewers is three sessions, three files. For each session,
   get:
   - **date:** the scheduled date; if it isn't scheduled yet, today's date;
   - **who:** the interviewer's name; for several interviewers in the same
     session, their names joined with "and" ("Dana Reyes and Sam Ortiz");
     only if names aren't known yet, a short label ("recruiter screen").

   Then get each session's file:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" interview-file "<Company>" "<Role>" --date <YYYY-MM-DD> --who "<who>"
   ```
   It prints the file's path, creating it (and its link in `notes.md`) the
   first time. If the file already has content — an earlier prep session for
   the same interview — read it and build on it rather than starting over.

## Briefing Contents

Open with one line saying this is a best guess at the conversation, not a
script.

1. **Who they're likely talking to** — from `contacts.md` and each person's
   page, plus what's known about their role and priorities from `notes.md`
   and earlier interview files.
2. **Likely questions** — grounded in the JD and this stage of the
   process (a recruiter screen asks different things than a CEO round).
3. **Suggested talking points** — drawn from `career/profile.md` and
   `career/resume/master_resume.md`, matched to what this specific
   interviewer likely cares about. When a likely question matches an entry
   in `career/talking_points.md`, use that settled answer and say it's the
   settled one; don't re-derive it. Don't invent accomplishments to fit — if
   there's a gap between what they'll probably ask and what the user has to
   offer, name it and help them think through how to answer honestly.
4. **Questions the user should ask** — grounded in `career/trajectory.md`
   must-haves/must-nots that this stage of the process can actually
   surface information about (e.g. reporting line, team structure).
5. **Glossary** — see Define Every Term.

### Define Every Term

Never name a tool, metric, acronym, vendor, service or method without
saying what it is. Saying a term in an interview invites a follow-up
question about it, so the user must be able to explain anything the
briefing puts in their mouth.

- On first use, define it inline in plain words (a short parenthetical).
- End the briefing with a **Glossary**: each technical term with one line on
  what it is and an "if asked, say…" line the user could say aloud.
- Mark terms that are background only (useful to understand, not worth
  saying aloud) as such.

## Rehearsal

When the user rehearses answers with you, save each agreed answer **in
full** — the user's own phrasing with the agreed changes folded in, not a
summary of the fixes — under a `## Rehearsed answers` heading in the
session's file, as soon as each one is settled. Before saying prep is done,
check that every answer worked out in the conversation is in the file.

## Talking Points

`career/talking_points.md` holds the user's settled answers to questions
that come up in every interview, whatever the company (e.g. "Why did you
leave your last role?"). Answers specific to one opportunity stay in that
interview's file.

When an answer is settled — in prep or rehearsal — for a question that
would come up in any interview, offer to add it to
`career/talking_points.md`, or to update the existing entry. Write to it
only with the user's OK. Create the file on the first OK. Entry format:

```
## "<The question, as interviewers ask it>"

**Last updated:** YYYY-MM-DD. Sources: <files / transcripts, with timestamps>.

<The user's position, if it matters to the answer.>

<The answer.>

<Optional: why earlier versions misfired, with sources.>
```

New files start with a `# Talking Points` heading. Every claim in an answer
must trace to `career/profile.md`, `career/resume/master_resume.md`, a
transcript, or something the user said. Existing entries that don't match
this shape exactly are fine; don't reformat them unasked.

## Output

1. Write the briefing into the session's file under a `## Prep (<date>)`
   heading (today's date). For a loop, write each session's briefing into
   its own file; each file stands on its own, so repeat shared context
   briefly rather than pointing to another file.
2. In the chat, give a short summary and the file path(s).
