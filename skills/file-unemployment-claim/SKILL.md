---
name: file-unemployment-claim
description: Use when the user needs to file their weekly Massachusetts unemployment (DUA) certification, or asks to "file unemployment," "do my weekly claim," or similar. Massachusetts DUA only — for any other state, say this skill doesn't cover it. Walks the unemployment.mass.gov weekly certification flow, pulling work search activities from tracker.md.
---

# File Unemployment Claim (MA DUA Weekly Certification)

## Scope

**Massachusetts only.** This covers the MA DUA weekly certification at
unemployment.mass.gov. If the user files in any other state, say so and
stop.

This covers the **recurring weekly certification** on an already-active MA
DUA claim (unemployment.mass.gov) — not the initial claim filing. If the
dashboard ever shows no active claim or asks to start a *new* claim rather
than certify a week, stop and check with the user before proceeding — that's a different, higher-stakes flow this
skill doesn't cover.

## Hard limits (never cross these, even if asked)

- **Never type into any password field.** MyMassGov login requires the user
  to enter their own email/password.
- **Never type into the Signature field on the final "Confirm submission"
  page.** That's a legal e-signature attestation — the user types their own name.
- **Never click the final Submit** on "Confirm submission" without the
  user explicitly telling you to (e.g., "submit it," "go ahead"). Everything
  before that (checkboxes, radio answers, work-search entries) can proceed
  with their general go-ahead for the session, but the actual submission is
  a separate, irreversible confirmation.
- Confirm the Yes/No answers on the "Weekly questions" step with the
  user explicitly before selecting them — they're factual attestations under
  penalty of law (capable of work, available for work, work-search
  completed, unreported earnings). Don't infer or guess these.

## Step-by-step flow

1. **Navigate to** `https://unemployment.mass.gov/claimants/_/`.
   - If you see "It appears you have duplicated a browser tab or window...
     For security, this is not allowed," click **"Click here to start
     over."** This is normal — it happens when a prior session tab was
     left open/closed uncleanly, not a real problem.
2. **Log in.** Click **"Log in or Create your account with MyMassGov"** →
   lands on the MyMassGov login screen. Hand off to the user to enter email
   + password themselves, then wait for them to confirm they're through (including
   any MFA prompt).
3. **Dashboard.** Confirm there's a "Claim for week ending [date]" card
   with status "Ready to request benefits." Click **"Request benefits."**
4. **"What you will need"** — informational screen listing the week being
   certified and required items (earned wages if any, proof of 3 work
   search activities). Click **Next**.

   **Before continuing past this screen**, pull candidate work search
   activities for that week from `tracker.md` (and
   `tracker_closed.md` if the tracker was pruned) — look for:
   - Any opportunity with an "Applied" stage and a date in the target week
   - Any networking activity from the calendar or tracker notes (coffees,
     warm-intro outreach, referral requests) dated in that week
   Present 3 (plus a backup) to the user with dates/companies before filling
   the work search log, per the guardrail above.
5. **"Qualification requirements"** — check "I understand the previous
   information," click **Next**.
6. **"Weekly questions"** — four Yes/No radios:
   - Were you capable of working?
   - Were you available to work?
   - Did you complete 3 work search activities?
   - Did you work/earn money or receive other unreported income?
   Confirm each answer with the user (see Hard limits), click the radios, then
   **Next**. When verifying a click landed correctly, zoom into the
   Yes/No pair — the selected option has a blue underline; don't rely on
   the cursor position or a black focus box as the indicator.

   **Selecting "No" is unreliable — verify every answer before Next.**
   The horizontal Yes/No pairs have a click-target offset: the "No"
   element's ref resolves to a point that still falls inside "Yes,"
   roughly one button width off. Clicking "Yes" (the left option) works;
   clicking "No" silently selects "Yes" instead, and the tool reports
   success either way. An explicit coordinate on "No" failed too.

   So after clicking, zoom each row and confirm the blue underline sits
   under the intended option. If "No" won't take after **two** attempts,
   stop and ask the user to click that row themselves, then re-verify — don't
   keep clicking. These are sworn attestations, and question 4 answered
   "Yes" falsely claims unreported income.

   The vertically-stacked radios on the Work search log step do not have
   this problem; ref clicks land correctly there.

   The **Review** step (8) shows all four answers as text. Treat that as
   the authoritative check before submission, not the radio styling.
7. **"Work search log"** — click **"Add work search activity"** once per
   activity (3 minimum). Each entry:
   - Radio: "Applied for a job" (needs Date, Company, Position),
     "Interviewed for a job," "Worked with a MassHire Career Center,"
     "Registered for work with an employment/placement agency," or
     "Other job search activities" (needs only a Date — no description
     field exists for this category).
   - **Known quirk:** the Company field sometimes silently fails to
     accept typed text on the first attempt (shows "Required" placeholder
     still after typing). Always screenshot/zoom to verify text actually
     landed before moving on; if it didn't, click the field again and
     retype.
   - Date fields accept typed `MM/DD/YYYY` and auto-reformat to
     `DD-Mon-YYYY` on blur — click elsewhere after typing and verify the
     reformat happened (confirms the value registered).
   Click **Next** once all 3+ entries are filled and verified.
8. **"Review"** — read-only summary of Weekly questions + Work search log.
   Verify it matches what was entered. Click **Next**.
9. **"Confirm submission"** — legal attestation text, then a **Signature**
   field (type first + last name) and a **Submit** button below it. Hand
   off the Signature field to the user (see Hard limits). Once they confirm
   it's signed, ask explicitly whether to submit, or let them click Submit
   themselves if they're still in the browser.
10. **Verify success** on the dashboard: the certified week's card should
    change from "Ready to request benefits" to **"Processing"** (or later,
    "Paid"), and "Weeks remaining"/"Benefits remaining" should decrement
    accordingly.

## After submission

Nothing needs to be written back to the job-search-os tracker — this is a
DUA-side action, not a pipeline opportunity. If a work search activity
used in the filing wasn't already in `tracker.md` (e.g., a
networking event that never got logged), consider whether it's worth
adding there too, but don't duplicate DUA's own record-keeping into the
workspace.
