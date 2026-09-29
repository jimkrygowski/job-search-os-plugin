# job-search-os (Claude Code plugin)

A fork of [job-search-os](https://github.com/jimkrygowski/job-search-os) restructured as a Claude Code plugin — the code is installed and updated by Claude Code, and your data lives in a folder you own, completely separate from it.

An agentic system for running a job search with the same rigor you'd bring to any other engineering problem. Built on [Claude Code](https://claude.com/claude-code), it turns a job search into a structured pipeline — grounded in actual research rather than generic AI life-coach platitudes, and engineered with the guardrails, tests, and separation of concerns you'd expect from production software.

## Why this exists

I'm Jim Krygowski, an engineering executive with 20+ years running and scaling engineering orgs — most recently as a senior engineering leader before a layoff put me back on the market in 2026. I've hired for and sat on the other side of a lot of searches. What I haven't done is run my own job search with any real system behind it — in past searches a well organized inbox sufficed.

While I was at Jellyfish I built myself a chief of staff agent system to help take some of toil out of my job. That experience opened my eyes to the possibilities of personal productivity systems built around an LLM. I've spoken to a lot of folks who are on the market now and have a deep appreciation for the labor that goes into the job search. I've read a lot about using chatbots to write cover letters but I wanted more. An assistant and coach capable of tackling the process end to end: candidate profile and target-role definition as real artifacts, a pipeline tracker to stay focused, opportunity based research and planning and research-grounded coaching instead of vibes. I also built this using Claude and as much as was reasonable followed good engineering practice in the construction of the agent, the building of test coverage and code review that I'd want in any software product I built or used.

I'm sharing this work for anyone who's interested in getting a boost in managing their job search. The code was written by an agent working to my specifications, under continuous review and revision. It's a fair sample of how I think about building software: what I choose to make rigorous, what I choose to leave simple, and where I draw the line between "good enough" and "worth getting right."

If you know someone looking for CTO, VP Engineering, Head of Engineering or Senior Director role don't hesitate to reach out to me via my [LinkedIn](https://linkedin.com/in/jimkrygowski).

## Install

Requires [Claude Code](https://claude.com/claude-code) and Python 3. The optional [dashboard](#dashboard) also needs Node 22.18 or newer.

```
/plugin marketplace add jimkrygowski/job-search-os-plugin
/plugin install job-search-os@job-search-os
```

Then make a folder for your search (e.g. `~/job-search`), start Claude Code in it, and say you want to get started — or run `/job-search-os:bootstrap`. Bootstrap turns that folder into your *workspace*, checks for Python, and walks you through building your profile, defining your target role, and setting your compensation target. Everything after that happens through normal conversation, as long as you start Claude in your workspace.

### Coming from job-search-os

If you've been using the original repo, create your new workspace folder, start Claude Code there, and run `/job-search-os:migrate`. It copies everything under the old checkout's `state/` into the workspace — refusing to overwrite anything already there, and never modifying the old checkout.

## What it actually does

Fifteen skills, each a focused piece of the search. Invoke them by name (`/job-search-os:<skill>`) or just ask for what you want in a session started in your workspace:

| Skill | What it does |
|---|---|
| `bootstrap` | First-time setup — creates your workspace, checks the Python preflight, then walks a new user through `build-profile`, `define-trajectory`, and comp-target setup |
| `build-profile` | Guided conversation to build a real candidate profile: career history, best/worst jobs and bosses, and the patterns underneath them |
| `define-trajectory` | Defines (and later revisits) the target role, shaped as a Mnookin Two-Pager — see below |
| `offer-negotiator` | Compensation coaching end to end — builds your target, preps first-contact talking points, breaks down a real offer with equity run through `option_value.py`, plans the counter, and hands the final call to `career-coach` |
| `score-opportunity` | Scores a pasted job description against your actual must-haves/must-nots, criterion by criterion — not a vibe check |
| `tailor-resume` | Tailors a resume and cover letter from your master resume — never invents experience to fit a JD |
| `company-research` | Researches a target company, every finding tagged with a source |
| `interview-prep` | Briefing before a call — who you're talking to, likely questions, honest talking points including where you have a real gap |
| `interview-review` | Turns a call transcript into structured feedback and advances the pipeline |
| `career-coach` | A structured coaching session grounded in evidence-graded psychology frameworks — see below |
| `morning-scan` | A daily pipeline/email/calendar scan, run on demand — not a background job |
| `file-unemployment-claim` | Walks the weekly unemployment certification — **Massachusetts DUA only** |
| `migrate` | Imports data from an original job-search-os checkout into a workspace |
| `dashboard` | Opens a local, read-only web dashboard of your search — see below |
| `backfill-history` | Reconstructs past stage history from your notes (once), so the dashboard can show full paths |

Plus one command, `/job-search-os:summarize-call`, which turns a call transcript into structured notes.

## Dashboard

`/job-search-os:dashboard` starts a small web server on `127.0.0.1` (never reachable from another machine) and opens a read-only view of your workspace in the browser:

- **Where opportunities go** — a Sankey from how each opportunity arrived (referral, recruiter, job alert, …) through the stages it reached to how it ended, or where it's sitting now. Opportunities with no activity for 21+ days show as *stalled*.
- **Stage conversion and time in stage** — how many moved past each stage (still-open ones excluded from the rate) and median / p75 days spent there, with small samples flagged as such.
- **Activity by week** — opportunities added, advanced and closed.

Filter by date added, source and status; click any node, link or row to see the opportunities behind it, then any one of them for its timeline and `notes.md`. Every chart has a table view.

It's powered by `tracker_events.jsonl`, which the tracker appends to on every stage change. For opportunities from before that log existed, run `/job-search-os:backfill-history` once: it reconstructs past history from your notes (asking you when the evidence is ambiguous, never inventing dates), and the Sankey draws reconstructed history striped so it's never confused with recorded history.

The server runs TypeScript directly on Node 22.18+ with no npm install and no runtime dependencies; charts use vendored [d3](https://d3js.org) and d3-sankey, so nothing is fetched from the internet. It stops itself after two idle hours.

## Grounded in real frameworks

Three things this system leans on that most "AI job search assistant" projects don't bother with:

**The coaching is evidence-graded, not aspirational.** `career-coach` draws on seven frameworks — Schein's Career Anchors, Self-Determination Theory, Ibarra's Working Identity, Opportunity Fit Assessment, Career Capital, Regret Minimization, Ikigai — and every one of them ships with a companion [research review](skills/career-coach/research.md) that grades its actual evidence quality, cites the primary literature, and says plainly when a framework is a practitioner heuristic dressed up as science. Self-Determination Theory gets used with confidence — 40+ years of replicated peer-reviewed research. Ikigai gets used as a conversation starter and nothing more — it's a Western blog invention from 2011, misattributed to Japan ever since. The skill doesn't pretend otherwise, and neither does this README.

**The trajectory format comes from a real methodology.** `define-trajectory` builds a "Mnookin Two-Pager" — a concept from Phyl Terry's *Never Search Alone*, shaped as a genuine, shareable pitch document rather than internal notes. The system also implements Terry's Listening Tour idea directly: real feedback from an interview or a networking conversation is treated as a trigger to revisit the trajectory, not just a calendar-based staleness check. What's deliberately *not* here is Terry's Job Search Council — a peer accountability group is a real human structure, and no amount of agentic tooling should pretend to substitute for one.

**Comp advice is sourced the same way, and equity math doesn't get freehanded.** `offer-negotiator` ships its own evidence-graded [research review](skills/offer-negotiator/research.md) — negotiation tactics and equity mechanics each rated for how solid the underlying evidence actually is, same treatment `career-coach` gets, right down to flagging where the research is genuinely contested (e.g. gender and negotiation outcomes) rather than picking the more comfortable narrative. And instead of letting an LLM eyeball what a stock grant is worth, `tools/option_value.py` computes it deterministically — a real, tested calculation for face value, preference-stack haircuts, exit-probability ranges, and illiquidity discounts, with every default constant citing exactly which part of the research backs it.

## Built like software, not a prompt

A few things worth pointing at directly if you're evaluating engineering judgment rather than just features:

- **Code and data are structurally separated.** The plugin is installed and updated by Claude Code; everything personal — your profile, your pipeline, your tracker — lives in a *workspace*, any folder marked with a `.job-search-os.json` file. Tools find the workspace by walking up from the current directory (the way git finds `.git`), so a plugin update cannot touch or conflict with your data — it never lived alongside the code. Keep the workspace in its own **private** git repo if you want history. This fork exists because the original separated engine and data only by a gitignored folder inside the same repo; a plugin makes the boundary physical.
- **Everything activates only where it should.** The persona, guardrails, and setup nudges are injected by a SessionStart hook only when Claude is started inside a workspace. Anywhere else, the plugin stays quiet.
- **Agents are provided tools for common tasks.** For example, `tools/tracker.py` is the sole writer of the pipeline state, with a real file lock around every read-modify-write cycle — proven with a test that fires 8 concurrent writes at it and checks none get silently dropped. This exists because LLMs are by nature non-deterministic and rolling the dice each session by letting the LLM figure out how to edit the tracker is a recipe for corrupted files.
- **Guardrails are honest about what's structural versus what's a promise.** Inside a workspace, a plugin PreToolUse hook denies the Gmail connector's send, reply, and forward tools — that one's enforced, not just instructed, and it fails closed. It covers only those Gmail tools; sending through any other route (e.g. browser automation) is blocked by instruction only. The other guardrails (never invent experience, never assert an unsupported claim as fact) are instruction-level too, and the system says so rather than overclaiming a guarantee it can't back up.
- **Real code review happened — by an adversarial agent, not the agent that wrote the code.** The original system was built via spec → implementation plan → independent implementer/reviewer passes on every task, plus whole-branch reviews that caught real cross-task bugs before merge. An external review pass later caught a genuine concurrency bug and a date-parsing bug that silently dropped messages — both fixed, both covered by regression tests. This fork's spec and plan are in [`docs/superpowers/`](docs/superpowers/).
- **Stdlib only.** Every Python tool and test has zero pip dependencies, and the dashboard server uses only Node built-ins (its npm packages are TypeScript and type definitions, used at development time only; the compiled browser code is committed). No supply chain to audit for a tool that manages your job search pipeline.

## Layout

The plugin (this repo):

```
.claude-plugin/
  plugin.json                  plugin manifest
  marketplace.json             this repo is also its own marketplace
skills/                        the fifteen skills above (+ their research reviews)
commands/summarize-call.md     turns a call transcript into structured notes
hooks/hooks.json               SessionStart (persona + setup check), PreToolUse (Gmail send guard)
guidance/persona.md            persona and guardrails injected in a workspace
tools/
  workspace.py                 finds / creates the workspace
  tracker.py                   sole writer of tracker.md, locked, tested
  score_table.py               deterministic opportunity score table
  option_value.py              deterministic equity valuation calculator
  gmail_extract.py             extracts new content from a saved Gmail thread
  check_bootstrap_state.py     setup-completeness check
  session_start.py, guard_send.py   hook entry points
  migrate.py                   imports an original job-search-os state/
  run_tests.sh                 full test suite + static checks
dashboard/
  server/                      Node server (TypeScript, built-ins only): export -> derive -> HTTP
  shared/                      /api/data types + chart aggregation, used by server tests and browser
  web/                         index.html, style.css, src/ (TypeScript), dist/ (compiled, committed), vendor/ (d3)
  fixtures/                    fake workspace + golden export used by both test suites
```

Your workspace (anywhere you like, never inside the plugin):

```
.job-search-os.json            marks the folder as a workspace
career/
  profile.md                   your background (built by build-profile)
  trajectory.md                your target role, Mnookin Two-Pager shape
  comp_target.md               walk-away numbers, comp priorities, deal-breakers
  job_alert_sources.md         your job alert email sources
  resume/master_resume.md      your source-of-truth resume
opportunity/<company>/<role>/  per-opportunity JD, contacts, notes, tailored resume, transcripts
tracker.md / tracker_closed.md active / closed pipeline state
tracker_events.jsonl           every stage change, appended by the tracker (feeds the dashboard)
```

## List it in your own marketplace

The plugin lives at this repo's root, so any marketplace can list it with a `github` source:

```json
{
  "name": "job-search-os",
  "source": { "source": "github", "repo": "jimkrygowski/job-search-os-plugin", "ref": "v0.2.0" }
}
```

Omit `ref` to track the default branch. Releases are tagged `vX.Y.Z`, matching the `version` in `.claude-plugin/plugin.json`. Keep the entry name `job-search-os` — it's the install id and the prefix on every skill.

## Development

```
tools/run_tests.sh             # Python + dashboard tests, static checks, stale-build check
claude plugin validate .       # manifest + marketplace validation
cd dashboard && npm run build  # after changing dashboard/web/src or shared/; commit web/dist
```

The dashboard needs Node 22.18+; `run_tests.sh` runs `npm ci` in `dashboard/` the first time. To look at it with fake data: `python3 dashboard/fixtures/make_fixture.py` regenerates the fixture; copy `dashboard/fixtures/workspace` somewhere, add a `.job-search-os.json` (`{"schema": 1}`), and run `node dashboard/server/main.ts --workspace <copy>`.

To try changes live, create a scratch workspace (`python3 tools/workspace.py init /tmp/ws`), `cd` into it, and run `claude --plugin-dir /path/to/this/repo`. See `CLAUDE.md` for the rules that keep code and state apart.

## License

[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
— free for any noncommercial purpose. Running your own job search with it counts,
including a search for paid employment; so does use by charities, schools, and
government. Selling it, or building a commercial product or service on it, does
not.

Not an open source license: the Open Source Definition forbids restricting
commercial use, and this does restrict it.

## About me

I was most recently a Director of Engineering at Jellyfish, where I headed up the teams building the AI platform and features on top of it. Before that I led a 55-person multi-geo engineering org at Charles River Development, and, earlier, was the first engineering hire at Linkable Networks, where I built and owned engineering and operations from zero through the company's acquisition. I'm looking for my next engineering leadership role, ideally partnering closely CEO, CTO to CPO and working to develop strategy and translate it to engineering delivery. I'm open to remote or hybrid. In the meantime, I'm also open to short-term consulting or advisory engagements, engineering leadership, org design, AI/agentic infrastructure strategy, so if you know of something that could use a hand, I'd welcome the conversation.

[linkedin.com/in/jimkrygowski](https://linkedin.com/in/jimkrygowski)
