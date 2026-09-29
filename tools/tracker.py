#!/usr/bin/env python3
"""CLI for reading and writing the workspace's tracker.md / tracker_closed.md.

This is the only code that should ever write these files. Skills call it
via `python3 tools/tracker.py <command> ...` rather than editing the
markdown tables directly, to avoid corrupting pipeline state.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# v0.1 tables have only LEGACY_COLUMNS; they still load (missing cells read
# as "") and are rewritten with the full column set on their next write.
LEGACY_COLUMNS = ["Company", "Role", "Stage", "Last Activity", "Next Action", "Next Action Date"]
ACTIVE_COLUMNS = LEGACY_COLUMNS + ["Source"]
CLOSED_COLUMNS = ACTIVE_COLUMNS + ["Outcome"]

# The canonical pipeline, in order. The dashboard reads these via
# `export --json` rather than hard-coding them.
STAGES = ["Identified", "Applied", "Recruiter Screen", "Hiring Manager", "Interview Loop", "Offer"]
OUTCOMES = ["Accepted", "Rejected", "Withdrew", "Ghosted", "Declined Offer"]
SOURCES = ["Referral", "Recruiter Inbound", "Applied Cold", "Warm Intro", "Job Alert", "Other"]

# Stage names used before the ladder was fixed (lowercased). Anything not
# here is reported, never guessed.
LEGACY_STAGES = {
    "new": "Identified", "lead": "Identified", "sourced": "Identified",
    "application submitted": "Applied",
    "screen": "Recruiter Screen", "phone screen": "Recruiter Screen",
    "recruiter call": "Recruiter Screen", "recruiter": "Recruiter Screen",
    "hm": "Hiring Manager", "hiring manager screen": "Hiring Manager",
    "hiring manager interview": "Hiring Manager", "hm screen": "Hiring Manager",
    "onsite": "Interview Loop", "on-site": "Interview Loop", "loop": "Interview Loop",
    "interview": "Interview Loop", "interviewing": "Interview Loop",
    "panel": "Interview Loop", "final round": "Interview Loop",
    "offer received": "Offer", "offer stage": "Offer",
}

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import workspace  # noqa: E402

# All personal state lives in the user's workspace (see workspace.py), never
# alongside this code. Paths are resolved per call, not at import time.
ACTIVE_TITLE = "Active Opportunities"
CLOSED_TITLE = "Closed Opportunities"


def state_root() -> Path:
    return workspace.require_root()


def active_path() -> Path:
    return state_root() / "tracker.md"


def closed_path() -> Path:
    return state_root() / "tracker_closed.md"


def events_path() -> Path:
    return state_root() / "tracker_events.jsonl"


def lock_path() -> Path:
    return state_root() / ".tracker.lock"


def slugify(text: str) -> str:
    """Deterministic filesystem-safe slug for a Company or Role string.

    Every skill that touches an opportunity folder resolves its path
    through this function (via `opportunity_path` / the `opportunity-path`
    CLI command) rather than slugifying independently in prose — that's
    what keeps "VP Engineering" and "VP  Engineering" (or a different
    skill's own guess at the transform) from silently creating two
    different folders for the same opportunity.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_").lower()
    return slug or "unnamed"


def opportunity_path(company: str, role: str) -> Path:
    return state_root() / "opportunity" / slugify(company) / slugify(role)


def _match(value: str, allowed: list[str]) -> str | None:
    for a in allowed:
        if a.lower() == value.strip().lower():
            return a
    return None


def canonical_stage(name: str) -> str | None:
    return _match(name, STAGES) or LEGACY_STAGES.get(name.strip().lower())


def _fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def require_stage(name: str) -> str:
    stage = canonical_stage(name)
    if stage:
        return stage
    if _match(name, OUTCOMES):
        _fail(f"{name!r} is an outcome, not a stage — use `close --outcome {name!r}`")
    _fail(f"unknown stage {name!r}; valid stages: {', '.join(STAGES)}")


def require_choice(value: str, allowed: list[str], what: str) -> str:
    match = _match(value, allowed)
    if match is None:
        _fail(f"unknown {what} {value!r}; valid: {', '.join(allowed)}")
    return match


def workspace_sources() -> list[str]:
    """The workspace's own source list (`"sources"` in .job-search-os.json),
    or SOURCES. Lets a workspace split e.g. "Job Alert" by feed without the
    plugin hard-coding anyone's job boards."""
    try:
        cfg = json.loads((state_root() / workspace.MARKER).read_text())
    except (OSError, json.JSONDecodeError):
        return SOURCES
    if not isinstance(cfg, dict) or "sources" not in cfg:
        return SOURCES
    value = cfg["sources"]
    ok = (isinstance(value, list) and value
          and all(isinstance(v, str) and v.strip() for v in value)
          and len({v.strip().lower() for v in value}) == len(value))
    if not ok:
        _fail(f'"sources" in {workspace.MARKER} must be a non-empty list of distinct names, '
              f"got {value!r}")
    return [v.strip() for v in value]


def now_ts() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def append_event(event: dict) -> None:
    """Append one line to tracker_events.jsonl. Callers hold locked() and
    call this only after the table write succeeded."""
    record = {"ts": event.get("ts") or now_ts(), **event,
              "inferred": event.get("inferred", False)}
    with events_path().open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_events() -> tuple[list[dict], list[str]]:
    path = events_path()
    if not path.exists():
        return [], []
    events, warnings = [], []
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"line {n} of tracker_events.jsonl is not valid JSON")
            continue
        if not isinstance(event, dict) or not {"ts", "company", "role", "type"} <= event.keys():
            warnings.append(f"line {n} of tracker_events.jsonl is missing required fields")
            continue
        events.append(event)
    return events, warnings


@contextmanager
def locked(timeout: float = 10.0):
    """Mutual exclusion for read-modify-write cycles against tracker.md /
    tracker_closed.md. Concurrent invocations (e.g. morning-scan recording
    several calendar events in parallel) would otherwise race: both read
    the same snapshot, and the later write silently clobbers the earlier
    one. Uses exclusive file creation (portable across platforms) rather
    than fcntl/msvcrt, to stay stdlib-only without a POSIX-only import.
    """
    lock = lock_path()
    start = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() - start > timeout:
                print(
                    f"error: could not acquire {lock} within {timeout}s "
                    "— another tracker.py process may be stuck; if you're sure "
                    "none is running, delete the lock file manually",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def unescape_cell(value: str) -> str:
    return value.replace("\\|", "|").strip()


def split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    parts = []
    current = ""
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if ch == "\\" and i + 1 < len(stripped) and stripped[i + 1] == "|":
            current += "\\|"
            i += 2
            continue
        if ch == "|":
            parts.append(current.strip())
            current = ""
            i += 1
            continue
        current += ch
        i += 1
    parts.append(current.strip())
    return parts


def parse_table(text: str, columns: list[str] = ACTIVE_COLUMNS) -> list[dict]:
    lines = [line for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [unescape_cell(c) for c in split_row(lines[0])]
    if header != columns[:len(header)] or len(header) < len(LEGACY_COLUMNS):
        raise ValueError(f"Unrecognized tracker header: {lines[0]!r}")
    rows = []
    for line in lines[2:]:  # skip header + separator
        cells = split_row(line)
        if len(cells) != len(header):
            raise ValueError(
                f"Malformed row (expected {len(header)} columns, got {len(cells)}): {line!r}"
            )
        row = {col: "" for col in columns}
        row.update({col: unescape_cell(cell) for col, cell in zip(header, cells)})
        rows.append(row)
    return rows


def serialize_table(rows: list[dict], title: str, columns: list[str] = ACTIVE_COLUMNS) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [f"# {title}", "", header, separator]
    for row in rows:
        cells = [escape_cell(row.get(col, "")) for col in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def read_table(path: Path, columns: list[str] = ACTIVE_COLUMNS) -> list[dict]:
    if not path.exists():
        return []
    return parse_table(path.read_text(), columns)


def write_table(path: Path, rows: list[dict], title: str, columns: list[str] = ACTIVE_COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_table(rows, title, columns))


def find_row(rows, company, role):
    """Matches by slug, not raw string equality — so "VP Engineering" and
    "VP  Engineering" are treated as the same opportunity here too, not
    just when resolving the folder path. Without this, cmd_add's
    duplicate check would let slug-collision variants through as two
    separate active rows even though opportunity_path() resolves both to
    the identical folder."""
    target_company, target_role = slugify(company), slugify(role)
    for row in rows:
        if slugify(row["Company"]) == target_company and slugify(row["Role"]) == target_role:
            return row
    return None


def today() -> str:
    return datetime.date.today().isoformat()


def require_row(rows, company, role):
    row = find_row(rows, company, role)
    if row is None:
        print(f"error: {company} / {role} not found in tracker.md", file=sys.stderr)
        sys.exit(1)
    return row


def cmd_add(args):
    stage = require_stage(args.stage)
    source = require_choice(args.source, workspace_sources(), "source")
    with locked():
        rows = read_table(active_path())
        if find_row(rows, args.company, args.role):
            print(
                f"error: {args.company} / {args.role} already exists in tracker.md "
                "— use update-status",
                file=sys.stderr,
            )
            sys.exit(1)
        rows.append({
            "Company": args.company,
            "Role": args.role,
            "Stage": stage,
            "Last Activity": args.last_activity or today(),
            "Next Action": args.next_action or "",
            "Next Action Date": args.next_action_date or "",
            "Source": source,
        })
        write_table(active_path(), rows, ACTIVE_TITLE)
        append_event({"company": args.company, "role": args.role, "type": "add",
                      "to": stage, "source": source})
    print(f"added {args.company} / {args.role}")


def cmd_update_status(args):
    stage = require_stage(args.stage)
    with locked():
        rows = read_table(active_path())
        row = require_row(rows, args.company, args.role)
        # A legacy name ("Screen") is the same stage as its canonical form;
        # only a real move is a stage change.
        previous = canonical_stage(row["Stage"]) or row["Stage"]
        row["Stage"] = stage
        if args.next_action is not None:
            row["Next Action"] = args.next_action
        if args.next_action_date is not None:
            row["Next Action Date"] = args.next_action_date
        row["Last Activity"] = args.last_activity or today()
        write_table(active_path(), rows, ACTIVE_TITLE)
        if previous != stage:
            append_event({"company": row["Company"], "role": row["Role"], "type": "stage",
                          "from": previous, "to": stage})
    print(f"updated {args.company} / {args.role} -> {stage}")


def cmd_record_event(args):
    with locked():
        rows = read_table(active_path())
        row = require_row(rows, args.company, args.role)
        row["Next Action"] = args.event
        row["Next Action Date"] = args.date
        row["Last Activity"] = today()
        write_table(active_path(), rows, ACTIVE_TITLE)
    print(f"recorded event for {args.company} / {args.role}: {args.event} ({args.date})")


def cmd_close(args):
    outcome = require_choice(args.outcome, OUTCOMES, "outcome")
    with locked():
        rows = read_table(active_path())
        row = require_row(rows, args.company, args.role)
        rows.remove(row)
        write_table(active_path(), rows, ACTIVE_TITLE)

        closed_rows = read_table(closed_path(), CLOSED_COLUMNS)
        closed_rows.append({**row, "Outcome": outcome})
        write_table(closed_path(), closed_rows, CLOSED_TITLE, CLOSED_COLUMNS)
        append_event({"company": row["Company"], "role": row["Role"], "type": "close",
                      "from": canonical_stage(row["Stage"]) or row["Stage"], "outcome": outcome})

    notes_dir = opportunity_path(args.company, args.role)
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_path = notes_dir / "notes.md"
    with notes_path.open("a") as f:
        f.write(f"\n- **Closed ({today()}):** {outcome} — {args.reason}\n")

    print(f"closed {args.company} / {args.role}: {outcome}")


def cmd_set_source(args):
    source = require_choice(args.source, workspace_sources(), "source")
    with locked():
        for path, title, columns in ((active_path(), ACTIVE_TITLE, ACTIVE_COLUMNS),
                                     (closed_path(), CLOSED_TITLE, CLOSED_COLUMNS)):
            rows = read_table(path, columns)
            row = find_row(rows, args.company, args.role)
            if row is not None:
                row["Source"] = source
                write_table(path, rows, title, columns)
                append_event({"company": row["Company"], "role": row["Role"],
                              "type": "source", "source": source})
                break
        else:
            _fail(f"{args.company} / {args.role} not found in tracker.md or tracker_closed.md")
    print(f"set source for {args.company} / {args.role}: {source}")


def cmd_amend_closed(args):
    """Corrects Stage/Outcome on an already-closed row (the most recent one,
    if an opportunity was closed more than once). A correction of the record,
    not a pipeline move, so it writes no event."""
    if args.stage is None and args.outcome is None:
        _fail("amend-closed needs --stage and/or --outcome")
    stage = require_stage(args.stage) if args.stage is not None else None
    outcome = require_choice(args.outcome, OUTCOMES, "outcome") if args.outcome is not None else None
    with locked():
        rows = read_table(closed_path(), CLOSED_COLUMNS)
        target = (slugify(args.company), slugify(args.role))
        matches = [r for r in rows if (slugify(r["Company"]), slugify(r["Role"])) == target]
        if not matches:
            _fail(f"{args.company} / {args.role} not found in tracker_closed.md")
        row = matches[-1]
        if stage is not None:
            row["Stage"] = stage
        if outcome is not None:
            row["Outcome"] = outcome
        write_table(closed_path(), rows, CLOSED_TITLE, CLOSED_COLUMNS)
    print(f"amended {args.company} / {args.role}: stage={row['Stage']} outcome={row['Outcome']}")


def cmd_remove(args):
    """Takes a row that isn't a real opportunity (e.g. a networking contact)
    out of the tracker entirely. Its folder is kept; the reason goes in notes."""
    with locked():
        rows = read_table(active_path())
        row = require_row(rows, args.company, args.role)
        rows.remove(row)
        write_table(active_path(), rows, ACTIVE_TITLE)
        append_event({"company": row["Company"], "role": row["Role"], "type": "remove"})
    notes_dir = opportunity_path(args.company, args.role)
    notes_dir.mkdir(parents=True, exist_ok=True)
    with (notes_dir / "notes.md").open("a") as f:
        f.write(f"\n- **Removed from tracker ({today()}):** {args.reason}\n")
    print(f"removed {args.company} / {args.role}")


def _export_row(row: dict, warnings: list[str], closed: bool, sources: list[str]) -> dict:
    if row["Source"] and row["Source"] not in sources:
        warnings.append(f"{row['Company']} / {row['Role']}: source {row['Source']!r} is not in "
                        f"your sources list ({', '.join(sources)})")
    stage = canonical_stage(row["Stage"])
    if stage is None:
        stage = row["Stage"]
        warnings.append(
            f"{row['Company']} / {row['Role']}: unrecognized stage {stage!r} "
            f"(valid: {', '.join(STAGES)})")
    out = {
        "company": row["Company"],
        "role": row["Role"],
        "slug": f"{slugify(row['Company'])}/{slugify(row['Role'])}",
        "stage": stage,
        "source": row["Source"],
        "last_activity": row["Last Activity"],
        "next_action": row["Next Action"],
        "next_action_date": row["Next Action Date"],
    }
    if closed:
        out["outcome"] = row["Outcome"]
    return out


def export_data() -> dict:
    """Everything the dashboard needs, as plain JSON. This is the
    dashboard's only view of tracker state — it never parses the markdown."""
    with locked():
        active = read_table(active_path())
        closed = read_table(closed_path(), CLOSED_COLUMNS)
        events, event_warnings = read_events()
    warnings: list[str] = []
    sources = workspace_sources()
    data = {
        "schema": 1,
        "stages": STAGES,
        "outcomes": OUTCOMES,
        "sources": sources,
        "active": [_export_row(r, warnings, closed=False, sources=sources) for r in active],
        "closed": [_export_row(r, warnings, closed=True, sources=sources) for r in closed],
        "events": events,
    }
    data["warnings"] = event_warnings + warnings
    return data


def cmd_export(args):
    json.dump(export_data(), sys.stdout, indent=2, ensure_ascii=False)
    print()


def _validate_backfill_entry(entry, known, sources) -> str | None:
    """Returns an error message, or None. Normalizes names in place."""
    if not isinstance(entry, dict):
        return f"not an object: {entry!r}"
    label = f"{entry.get('company')} / {entry.get('role')}"
    if (slugify(str(entry.get("company", ""))), slugify(str(entry.get("role", "")))) not in known:
        return f"{label}: not in tracker.md or tracker_closed.md"
    try:
        datetime.datetime.fromisoformat(str(entry.get("ts")))
    except ValueError:
        return f"{label}: ts {entry.get('ts')!r} is not an ISO date/time"
    kind = entry.get("type")
    stage_fields = {"add": ["to"], "stage": ["from", "to"], "close": ["from"], "source": []}.get(kind)
    if stage_fields is None:
        return f"{label}: unknown type {kind!r} (add, stage, close, source)"
    for field in stage_fields:
        stage = canonical_stage(str(entry.get(field, "")))
        if stage is None:
            return f"{label}: unknown stage {entry.get(field)!r} in {field!r}"
        entry[field] = stage
    if kind == "close":
        outcome = _match(str(entry.get("outcome", "")), OUTCOMES)
        if outcome is None:
            return f"{label}: unknown outcome {entry.get('outcome')!r}"
        entry["outcome"] = outcome
    if kind == "source" or (kind == "add" and "source" in entry):
        source = _match(str(entry.get("source", "")), sources)
        if source is None:
            return f"{label}: unknown source {entry.get('source')!r}"
        entry["source"] = source
    return None


def _event_key(e: dict) -> tuple:
    return (slugify(e["company"]), slugify(e["role"]), e["type"], e.get("from"),
            e.get("to"), e.get("outcome"), e.get("source"), str(e["ts"])[:10])


def cmd_backfill(args):
    try:
        entries = json.loads(Path(args.events_file).read_text())
    except (OSError, json.JSONDecodeError) as e:
        _fail(f"can't read {args.events_file}: {e}")
    if not isinstance(entries, list):
        _fail("backfill input must be a JSON list")
    with locked():
        active = read_table(active_path())
        closed = read_table(closed_path(), CLOSED_COLUMNS)
        known = {(slugify(r["Company"]), slugify(r["Role"])) for r in active + closed}
        sources = workspace_sources()
        errors = [err for err in (_validate_backfill_entry(e, known, sources) for e in entries) if err]
        if errors:
            _fail("backfill rejected, nothing written:\n  " + "\n  ".join(errors))

        existing, _ = read_events()
        seen = {_event_key(e) for e in existing}
        added = sources_set = 0
        active_dirty = closed_dirty = False
        for entry in entries:
            if entry["type"] == "source":
                # Fills a blank Source only; a Source the user set wins.
                filled = False
                for rows in (active, closed):
                    row = find_row(rows, entry["company"], entry["role"])
                    if row is not None and not row["Source"]:
                        row["Source"] = entry["source"]
                        filled = True
                        if rows is active:
                            active_dirty = True
                        else:
                            closed_dirty = True
                if not filled:
                    continue
                sources_set += 1
            key = _event_key(entry)
            if key in seen:
                continue
            seen.add(key)
            fields = {k: entry[k] for k in ("from", "to", "outcome", "source") if k in entry}
            append_event({"ts": entry["ts"], "company": entry["company"], "role": entry["role"],
                          "type": entry["type"], **fields, "inferred": True})
            added += 1
        if active_dirty:
            write_table(active_path(), active, ACTIVE_TITLE)
        if closed_dirty:
            write_table(closed_path(), closed, CLOSED_TITLE, CLOSED_COLUMNS)
    print(f"backfill: {added} added, {len(entries) - added} already present, "
          f"{sources_set} blank sources filled")


def cmd_list(args):
    path = closed_path() if args.closed else active_path()
    title = CLOSED_TITLE if args.closed else ACTIVE_TITLE
    columns = CLOSED_COLUMNS if args.closed else ACTIVE_COLUMNS
    with locked():
        rows = read_table(path, columns)
    print(serialize_table(rows, title, columns))


def cmd_opportunity_path(args):
    print(opportunity_path(args.company, args.role))


def build_parser():
    parser = argparse.ArgumentParser(description="Manage tracker.md / tracker_closed.md")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("company")
    p_add.add_argument("role")
    p_add.add_argument("--stage", required=True)
    p_add.add_argument("--source", required=True, help="one of the workspace sources (see export --json)")
    p_add.add_argument("--next-action", default="")
    p_add.add_argument("--next-action-date", default="")
    p_add.add_argument("--last-activity")
    p_add.set_defaults(func=cmd_add)

    p_update = sub.add_parser("update-status")
    p_update.add_argument("company")
    p_update.add_argument("role")
    p_update.add_argument("--stage", required=True)
    p_update.add_argument("--next-action")
    p_update.add_argument("--next-action-date")
    p_update.add_argument("--last-activity")
    p_update.set_defaults(func=cmd_update_status)

    p_event = sub.add_parser("record-event")
    p_event.add_argument("company")
    p_event.add_argument("role")
    p_event.add_argument("--event", required=True)
    p_event.add_argument("--date", required=True)
    p_event.set_defaults(func=cmd_record_event)

    p_close = sub.add_parser("close")
    p_close.add_argument("company")
    p_close.add_argument("role")
    p_close.add_argument("--reason", required=True)
    p_close.add_argument("--outcome", required=True, help=" | ".join(OUTCOMES))
    p_close.set_defaults(func=cmd_close)

    p_source = sub.add_parser("set-source")
    p_source.add_argument("company")
    p_source.add_argument("role")
    p_source.add_argument("--source", required=True, help="one of the workspace sources (see export --json)")
    p_source.set_defaults(func=cmd_set_source)

    p_list = sub.add_parser("list")
    p_list.add_argument("--closed", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_amend = sub.add_parser("amend-closed")
    p_amend.add_argument("company")
    p_amend.add_argument("role")
    p_amend.add_argument("--stage")
    p_amend.add_argument("--outcome", help=" | ".join(OUTCOMES))
    p_amend.set_defaults(func=cmd_amend_closed)

    p_remove = sub.add_parser("remove")
    p_remove.add_argument("company")
    p_remove.add_argument("role")
    p_remove.add_argument("--reason", required=True)
    p_remove.set_defaults(func=cmd_remove)

    p_export = sub.add_parser("export")
    p_export.add_argument("--json", action="store_true", required=True)
    p_export.set_defaults(func=cmd_export)

    p_backfill = sub.add_parser("backfill")
    p_backfill.add_argument("--events-file", required=True)
    p_backfill.set_defaults(func=cmd_backfill)

    p_path = sub.add_parser("opportunity-path")
    p_path.add_argument("company")
    p_path.add_argument("role")
    p_path.set_defaults(func=cmd_opportunity_path)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
