#!/usr/bin/env python3
"""Regenerate dashboard/fixtures/workspace and export.json.

The fixture is fake data (about 30 opportunities) used by the Python export
contract test, the TypeScript tests and manual checks. It deliberately
includes the awkward cases: inferred history, rows with no events, a legacy
and an unmapped stage, a closed-then-re-added opportunity, an orphan event,
a malformed log line, and notes containing HTML.

The workspace is stored WITHOUT a .job-search-os.json marker so this repo is
never mistaken for a workspace; tests copy it and add the marker.

Run from anywhere: python3 dashboard/fixtures/make_fixture.py
"""
import datetime
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import tracker  # noqa: E402

BASE = datetime.date(2026, 6, 1)

# (company, role, source, [(stage, day offset), ...], end, flags)
# end: ("active", last_activity_offset) or ("closed", outcome, day offset)
# flags: "inferred" = all events backfilled; "noevents" = v0.1 row, no log
OPPS = [
    ("Acme Robotics", "VP Engineering", "Referral",
     [("Identified", 0), ("Applied", 2), ("Recruiter Screen", 9), ("Hiring Manager", 16),
      ("Interview Loop", 27), ("Offer", 40)], ("closed", "Accepted", 52), ""),
    ("Bluefin Health", "Head of Platform", "Recruiter Inbound",
     [("Recruiter Screen", 3), ("Hiring Manager", 10), ("Interview Loop", 21)],
     ("closed", "Rejected", 30), ""),
    ("Cobalt Labs", "Director of Engineering", "Applied Cold",
     [("Identified", 1), ("Applied", 4)], ("closed", "Ghosted", 45), "inferred"),
    ("Driftwood", "VP Engineering", "Job Alert",
     [("Identified", 5), ("Applied", 6)], ("closed", "Rejected", 20), ""),
    ("Ember Analytics", "CTO", "Warm Intro",
     [("Identified", 8), ("Hiring Manager", 14), ("Interview Loop", 29), ("Offer", 44)],
     ("closed", "Declined Offer", 50), ""),
    ("Fjord Systems", "Head of Engineering", "Applied Cold",
     [("Identified", 10), ("Applied", 11)], ("closed", "Ghosted", 50), ""),
    ("Garnet Pay", "VP Engineering", "Referral",
     [("Identified", 12), ("Applied", 13), ("Recruiter Screen", 18)],
     ("closed", "Withdrew", 25), "inferred"),
    ("Harbor AI", "Director, Platform", "Job Alert",
     [("Identified", 15), ("Applied", 16)], ("closed", "Rejected", 22), ""),
    ("Ionic", "VP Engineering", "Recruiter Inbound",
     [("Recruiter Screen", 18), ("Hiring Manager", 26)], ("closed", "Rejected", 33), ""),
    ("Juniper Bio", "Head of Data Platform", "Applied Cold",
     [("Identified", 20), ("Applied", 21), ("Recruiter Screen", 35)],
     ("closed", "Rejected", 38), ""),
    ("Kestrel", "VP Engineering", "Warm Intro",
     [("Identified", 22), ("Recruiter Screen", 25), ("Hiring Manager", 31),
      ("Interview Loop", 44)], ("closed", "Rejected", 55), ""),
    ("Lumen Energy", "Director of Engineering", "Job Alert",
     [("Identified", 25), ("Applied", 26)], ("closed", "Ghosted", 70), ""),
    ("Northwind", "Engineering Manager", "Applied Cold",
     [("Identified", 26), ("Applied", 27)], ("closed", "Rejected", 34), ""),
    ("Orbit Freight", "VP Engineering", "Referral",
     [("Identified", 30), ("Applied", 31), ("Recruiter Screen", 38), ("Hiring Manager", 45)],
     ("closed", "Withdrew", 58), ""),
    ("Pinecone Works", "CTO", "Other",
     [("Identified", 33), ("Applied", 36)], ("closed", "Rejected", 60), ""),
    ("Quarry", "Head of Engineering", "Job Alert",
     [("Identified", 40), ("Applied", 41)], ("closed", "Ghosted", 80), ""),
    # Active
    ("Redwood Cloud", "VP Engineering", "Referral",
     [("Identified", 60), ("Applied", 62), ("Recruiter Screen", 70), ("Hiring Manager", 78),
      ("Interview Loop", 95)], ("active", 115), ""),
    ("Saffron", "Director of Engineering", "Recruiter Inbound",
     [("Recruiter Screen", 75), ("Hiring Manager", 84)], ("active", 112), ""),
    ("Tidewater", "Head of Platform", "Warm Intro",
     [("Identified", 80), ("Applied", 81), ("Recruiter Screen", 90)], ("active", 90), ""),
    ("Umbra Security", "VP Engineering", "Applied Cold",
     [("Identified", 85), ("Applied", 86)], ("active", 86), ""),
    ("Vantage Maps", "CTO", "Warm Intro",
     [("Identified", 90), ("Applied", 92), ("Recruiter Screen", 100), ("Hiring Manager", 106),
      ("Interview Loop", 110), ("Offer", 116)], ("active", 116), ""),
    ("Willow Learning", "VP Engineering", "Job Alert",
     [("Identified", 95), ("Applied", 96)], ("active", 108), ""),
    ("Xylem Data", "Director, Data Engineering", "Referral",
     [("Identified", 100), ("Recruiter Screen", 105)], ("active", 111), ""),
    ("Yarrow", "Head of Engineering", "Applied Cold",
     [("Identified", 104), ("Applied", 105)], ("active", 105), ""),
    ("Zephyr Mobility", "VP Engineering", "Job Alert",
     [("Identified", 110)], ("active", 110), ""),
    ('Bed | Bath, "Inc"', "VP Engineering", "Other",
     [("Identified", 112), ("Applied", 113)], ("active", 113), ""),
    ("Northwind", "Engineering Manager", "Referral",
     [("Identified", 100), ("Applied", 101), ("Recruiter Screen", 109)], ("active", 109), ""),
    # v0.1 rows with no event history and a blank Source
    ("Aurora Retail", "VP Engineering", "",
     [("Applied", 70)], ("active", 70), "noevents"),
    ("Basalt", "Head of Engineering", "",
     [("Phone Screen", 88)], ("active", 99), "noevents"),
    ("Cirrus", "CTO", "",
     [("Networking", 96)], ("active", 96), "noevents"),
]

NOTES = {
    "Acme Robotics": (
        "# Acme Robotics — VP Engineering\n\n"
        "## Interview Review (2026-06-28)\n\n"
        "- **Strong** on org design; *weaker* on cost modeling.\n"
        "- Follow up with [the recruiter](https://example.com/recruiter).\n\n"
        "```\noffer: base 250k\n```\n"
    ),
    "Bluefin Health": (
        "# Bluefin Health\n\n"
        "Pasted from the JD: <script>alert('xss')</script> and <img src=x onerror=alert(1)>\n\n"
        "[bad link](javascript:alert(1))\n"
    ),
}


def ts(day: int) -> str:
    return (BASE + datetime.timedelta(days=day)).isoformat() + "T10:00:00"


def date(day: int) -> str:
    return (BASE + datetime.timedelta(days=day)).isoformat()


def build(root: Path) -> None:
    active, closed, events = [], [], []
    for company, role, source, path, end, flags in OPPS:
        row = {
            "Company": company, "Role": role, "Stage": path[-1][0],
            "Last Activity": date(end[1] if end[0] == "active" else end[2]),
            "Next Action": "", "Next Action Date": "", "Source": source,
        }
        if end[0] == "active":
            active.append(row)
        else:
            closed.append({**row, "Outcome": end[1]})
        if flags == "noevents":
            continue
        inferred = flags == "inferred"
        first_stage, first_day = path[0]
        events.append({"ts": ts(first_day), "company": company, "role": role, "type": "add",
                       "to": first_stage, "source": source, "inferred": inferred})
        for (prev, _), (stage, day) in zip(path, path[1:]):
            events.append({"ts": ts(day), "company": company, "role": role, "type": "stage",
                           "from": prev, "to": stage, "inferred": inferred})
        if end[0] == "closed":
            events.append({"ts": ts(end[2]), "company": company, "role": role, "type": "close",
                           "from": path[-1][0], "outcome": end[1], "inferred": inferred})
    events.sort(key=lambda e: e["ts"])
    # An orphan event (its row was hand-deleted) and a corrupt line.
    events.insert(5, {"ts": ts(7), "company": "Deleted Co", "role": "PM", "type": "add",
                      "to": "Identified", "source": "Other", "inferred": False})

    tracker.write_table(root / "tracker.md", active, tracker.ACTIVE_TITLE)
    tracker.write_table(root / "tracker_closed.md", closed, tracker.CLOSED_TITLE,
                        tracker.CLOSED_COLUMNS)
    lines = [json.dumps(e) for e in events]
    lines.insert(12, '{"ts": "2026-06-20T10:00:00", "company": "Truncated')
    (root / "tracker_events.jsonl").write_text("\n".join(lines) + "\n")

    for company, role, *_ in OPPS:
        folder = root / "opportunity" / tracker.slugify(company) / tracker.slugify(role)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "notes.md").write_text(
            NOTES.get(company, f"# {company} — {role}\n\n- Notes go here.\n"))


def main() -> None:
    ws = HERE / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir()
    build(ws)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "ws"
        shutil.copytree(ws, copy)
        (copy / ".job-search-os.json").write_text('{"schema": 1}\n')
        out = subprocess.run([sys.executable, str(TOOLS / "tracker.py"), "export", "--json"],
                             cwd=copy, check=True, capture_output=True, text=True).stdout
    (HERE / "export.json").write_text(out)
    print(f"wrote {ws} and {HERE / 'export.json'}")


if __name__ == "__main__":
    main()
