---
name: interview-review
description: Use when a user has a call/interview transcript to review. Produces structured feedback, writes it into that interview's own file under prep/ (the same file interview-prep uses), and advances the tracker stage.
---

# Interview Review

## Purpose

Turn a call transcript into structured feedback and move the pipeline
state forward.

## Session Start

Identify which opportunity this call was for, and resolve its folder via
`python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" opportunity-path "<Company>" "<Role>"` — never
construct the path yourself from the typed Company/Role. If the
transcript needs cleaning up first (a raw recording, not yet summarized),
run the `summarize-call` command on it first.

Read `career/talking_points.md` if it exists (the user's settled answers
to questions that come up in every interview).

Then find this session's interview file. One file per interview session —
one conversation with one set of people; a loop day with several sessions
has one file per session, so review each session's transcript into its
own file.

1. List the `prep/` folder inside the resolved opportunity folder. Look for
   the file prepped for this session: same interviewer(s), **any date** —
   it may have been prepped before the call was scheduled, or the call was
   rescheduled. Read it: the prep is useful context for the review.
2. Get the file's path with:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" interview-file "<Company>" "<Role>" --date <YYYY-MM-DD> --who "<who>"
   ```
   - exactly one file matches: pass that file's date and `who` (the `who`
     is in its `# Interview:` header line);
   - none matches: pass the call's date and the interviewer's name (several
     interviewers in one session: names joined with "and"). This creates the
     file and its link in `notes.md`;
   - it's unclear which file it is: ask the user before calling.

## Review Contents

1. **What was covered** — brief factual summary.
2. **What went well / what to improve** — direct, specific feedback, not
   generic encouragement. Cite specific moments in the transcript.
3. **New information learned** — anything that changes the picture of
   this opportunity (comp signal, team structure, timeline, concerns
   raised by the interviewer). This is exactly the kind of signal that
   might mean `career/trajectory.md` needs a revisit — flag it explicitly
   if it contradicts a stated must-have or must-not, and suggest running
   `define-trajectory` in revisit mode if so.
4. **Recommended next stage / next action.** The stage must be one of
   the canonical stages, in order: Identified, Applied, Recruiter Screen, Hiring Manager, Interview Loop, Offer.
   (`tracker.py` rejects anything else.) An outcome — the process ended —
   is not a stage; see Guardrails.

## Output

1. Write the review into the session's interview file under a
   `## Review (<date>)` heading (the call's date). Include a line noting the
   source transcript, e.g. `Source: transcripts/<filename>`. Don't write the
   review into `notes.md` — the file is already linked from there.
2. Save the transcript itself to that folder's `transcripts/`
   subdirectory if it isn't already there.
3. Advance the tracker:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/tools/tracker.py" update-status "<Company>" "<Role>" \
     --stage "<new stage>" --next-action "<next action>" \
     --next-action-date "<date, if known>"
   ```

4. Record the people on the call:
   - For each attendee, check `people.py find "<name>"`. Add anyone new with their role on this opportunity:
     `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" add "<Name>" --org "<Org>" --title "<Title>" --role "<role>@<opportunity slug>"`
   - Log the call for every attendee:
     `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" touch "<person>" --channel call --date <call date> --note "<stage>"` (`--channel meeting` if in person).
   - If someone offered an intro, record it with `people.py intro offer` (see the persona's People section).

## Talking Points

If the transcript shows an answer from `career/talking_points.md`
misfiring, or a new answer to a question that would come up in any
interview landing well, quote the moment and offer to update or add the
entry (format: see the `interview-prep` skill's Talking Points section).
Write to it only with the user's OK.

## Guardrails

- Feedback must cite the transcript, not general impressions.
- Prep is a best guess. Judge each answer against the
  question actually asked. Don't fault the user for not using prep material — stories they
  didn't tell, prepped questions that never came up — when the
  conversation went somewhere the prep didn't anticipate.
- Call something a miss only when the transcript shows a clear, specific
  opening for it, and quote that moment. Don't say an interviewer asked,
  raised or invited something unless the transcript shows them doing so.
- `career/talking_points.md` is prep material, not a checklist: never grade
  the user against it.
- Never call `tracker.py close` from this skill — closing is a pipeline
  decision the user makes explicitly, not an automatic consequence of a
  bad interview.
