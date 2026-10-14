#!/usr/bin/env python3
"""Storage for the relationships tracker.

Person pages (people/<slug>.md), the append-only people_events.jsonl and
the generated opportunity/*/*/contacts.md files are read and written only
through this module; people.py is its CLI.
"""
import datetime
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import tracker  # noqa: E402
import workspace  # noqa: E402

FIELD_ORDER = ["name", "org", "title", "email", "relationship", "cadence", "next_touch", "roles", "aliases"]
# Also the row order of a generated contacts.md.
ROLES = ["recruiter", "hiring", "connector", "peer", "panelist", "other"]
CHANNELS = ["call", "email", "meeting", "message", "other"]
INTRO_STATUSES = ["offered", "made", "met", "closed"]
INTRO_RESULTS = ["led_to_opportunity", "led_to_intros", "dead_end"]

_KEY = re.compile(r"[a-z_]+")
_SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
_OPP_SLUG = re.compile(r"[a-z0-9_]+/[a-z0-9_]+")
_CADENCE = re.compile(r"[1-9][0-9]*d")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EMAIL = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")


class PeopleError(Exception):
    """A user-facing error. people.py prints it and exits 1; nothing has been written."""


@dataclass
class Role:
    role: str
    opportunity: str = ""  # "<company>/<role>" folder slug; "" for a bare role

    def __str__(self) -> str:
        return f"{self.role} @ {self.opportunity}" if self.opportunity else self.role


@dataclass
class Person:
    slug: str
    name: str
    org: str = ""
    title: str = ""
    email: str = ""
    relationship: str = "no"
    cadence: str = "none"
    next_touch: str = ""
    roles: list = field(default_factory=list)    # list[Role]
    aliases: list = field(default_factory=list)  # list[str]
    body: str = "\n## Notes\n"


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_date(value: str, what: str = "date") -> datetime.date:
    if not _DATE.fullmatch(value):
        raise PeopleError(f"{what} must be YYYY-MM-DD, got {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise PeopleError(f"{what} must be YYYY-MM-DD, got {value!r}") from None


def parse_role(text: str) -> Role:
    role, sep, opp = (part.strip() for part in text.partition("@"))
    role = role.lower()
    if role not in ROLES:
        raise PeopleError(f"unknown role {role!r} in {text!r}; valid: {', '.join(ROLES)}")
    if sep and not _OPP_SLUG.fullmatch(opp):
        raise PeopleError(f"{opp!r} is not an opportunity slug like northwind_motors/vp_of_engineering")
    return Role(role, opp)


def check_field(key: str, value: str) -> None:
    """Validates one field value as it would be written to a page."""
    if "\n" in value or "\r" in value:
        raise PeopleError(f"{key} must be a single line")
    if key == "name" and not value.strip():
        raise PeopleError("name is required")
    if key == "email" and value and not _EMAIL.fullmatch(value):
        raise PeopleError(f"email {value!r} is not an email address")
    if key == "relationship" and value not in ("yes", "no"):
        raise PeopleError(f"relationship must be yes or no, got {value!r}")
    if key == "cadence" and value != "none" and not _CADENCE.fullmatch(value):
        raise PeopleError(f"cadence must be <N>d (e.g. 21d) or none, got {value!r}")
    if key == "next_touch" and value:
        parse_date(value, "next_touch")
    if key == "roles":
        for item in split_list(value):
            parse_role(item)


def _values(p: Person) -> dict[str, str]:
    return {"name": p.name, "org": p.org, "title": p.title, "email": p.email,
            "relationship": p.relationship, "cadence": p.cadence, "next_touch": p.next_touch,
            "roles": ", ".join(str(r) for r in p.roles), "aliases": ", ".join(p.aliases)}


def check_person(p: Person) -> None:
    for key, value in _values(p).items():
        check_field(key, value)
    for alias in p.aliases:
        if "," in alias:
            raise PeopleError(f"alias {alias!r} may not contain a comma")


def parse_page(text: str, slug: str, where: str) -> Person:
    lines = text.split("\n")
    if lines[0].rstrip("\r") != "---":
        raise PeopleError(f"{where}:1: a person page must start with a '---' field block")
    end = next((n for n in range(1, len(lines)) if lines[n].rstrip("\r") == "---"), None)
    if end is None:
        raise PeopleError(f"{where}: the field block has no closing '---'")
    values: dict[str, str] = {}
    for n in range(1, end):
        line = lines[n].rstrip("\r")
        key, sep, value = line.partition(":")
        if not sep or not _KEY.fullmatch(key):
            raise PeopleError(f"{where}:{n + 1}: expected 'key: value', got {line!r}")
        if key not in FIELD_ORDER:
            raise PeopleError(f"{where}:{n + 1}: unknown key {key!r}; known keys: {', '.join(FIELD_ORDER)}")
        if key in values:
            raise PeopleError(f"{where}:{n + 1}: {key!r} appears twice")
        value = value.strip()
        if value:
            try:
                check_field(key, value)
            except PeopleError as e:
                raise PeopleError(f"{where}:{n + 1}: {e}") from None
        values[key] = value
    if not values.get("name"):
        raise PeopleError(f"{where}: 'name' is required")
    return Person(
        slug=slug, name=values["name"], org=values.get("org", ""), title=values.get("title", ""),
        email=values.get("email", ""), relationship=values.get("relationship") or "no",
        cadence=values.get("cadence") or "none", next_touch=values.get("next_touch", ""),
        roles=[parse_role(r) for r in split_list(values.get("roles", ""))],
        aliases=split_list(values.get("aliases", "")),
        body="\n".join(lines[end + 1:]))


def serialize_page(p: Person) -> str:
    values = _values(p)
    block = [f"{key}: {values[key]}" for key in FIELD_ORDER if values[key]]
    return "\n".join(["---", *block, "---"]) + "\n" + p.body


# --- workspace files -------------------------------------------------------

def root() -> Path:
    return workspace.require_root()


def people_dir() -> Path:
    return root() / "people"


def events_path() -> Path:
    return root() / "people_events.jsonl"


def page_path(slug: str) -> Path:
    return people_dir() / f"{slug}.md"


def locked():
    """Held for every people.py command. people.py may take the tracker's
    lock while holding this one; tracker.py never takes this one."""
    return tracker.file_lock(root() / ".people.lock", holder="people.py")


def load_people() -> dict[str, Person]:
    """Every person page. Files starting with "_" are not person pages
    (room for an index); any other unreadable page is an error."""
    folder = people_dir()
    if not folder.is_dir():
        return {}
    people = {}
    for path in sorted(folder.glob("*.md")):
        if path.name.startswith("_"):
            continue
        if not _SLUG.fullmatch(path.stem):
            raise PeopleError(f"people/{path.name}: not a person page name (lowercase letters, digits "
                              "and _ only); rename it, or start it with _ if it isn't a person")
        people[path.stem] = parse_page(path.read_text(encoding="utf-8"), path.stem, f"people/{path.name}")
    return people


def save_person(p: Person) -> None:
    check_person(p)
    people_dir().mkdir(parents=True, exist_ok=True)
    page_path(p.slug).write_text(serialize_page(p), encoding="utf-8")


def delete_person(slug: str) -> None:
    page_path(slug).unlink()


# --- event log ---------------------------------------------------------------

def append_event(event: dict) -> None:
    record = {"ts": event.get("ts") or tracker.now_ts(), **event,
              "inferred": event.get("inferred", False)}
    with events_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events() -> tuple[list[dict], list[str]]:
    path = events_path()
    if not path.exists():
        return [], []
    events, warnings = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"line {n} of people_events.jsonl is not valid JSON")
            continue
        if not isinstance(event, dict) or not {"ts", "type"} <= event.keys():
            warnings.append(f"line {n} of people_events.jsonl is missing ts or type")
            continue
        events.append(event)
    return events, warnings


def merged_into(events: list[dict]) -> dict[str, str]:
    """Dropped slug -> surviving slug, following chains (a into b, b into c)."""
    direct = {e["detail"]["from"]: e["person"] for e in events
              if e["type"] == "person" and e.get("action") == "merge"}
    out = {}
    for start in direct:
        slug, seen = start, {start}
        while slug in direct and direct[slug] not in seen:
            slug = direct[slug]
            seen.add(slug)
        out[start] = slug
    return out


def used_slugs(people: dict[str, Person], events: list[dict]) -> set[str]:
    """Slugs that may never be handed out again: current pages plus every
    slug the event log mentions (merged-away people included)."""
    used = set(people)
    for e in events:
        for key in ("person", "from", "to"):
            value = e.get(key)
            if isinstance(value, str) and value and not value.startswith("org:"):
                used.add(value)
        detail = e.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("from"), str):
            used.add(detail["from"])
    return used


def allocate_slug(name: str, used: set[str]) -> str:
    base = tracker.slugify(name)
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}_{n}", n + 1
    return slug


def describe(p: Person) -> str:
    return f"{p.slug}  {p.name}" + (f" ({p.org})" if p.org else "")


def resolve(text: str, people: dict[str, Person], merges: dict[str, str]) -> Person:
    """A <person> argument: slug (or merged-away slug), then email, then
    exact name, then alias, all case-insensitive. Never fuzzy."""
    key = text.strip()
    slug = merges.get(key, key)
    if slug in people:
        return people[slug]
    wanted = key.casefold()
    tests = (lambda p: bool(p.email) and p.email.casefold() == wanted,
             lambda p: p.name.casefold() == wanted,
             lambda p: any(a.casefold() == wanted for a in p.aliases))
    for test in tests:
        hits = sorted((p for p in people.values() if test(p)), key=lambda p: p.slug)
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise PeopleError(f"{text!r} matches more than one person — use a slug:\n"
                              + "\n".join(f"  {describe(p)}" for p in hits))
    raise PeopleError(f"no one matches {text!r} (try: people.py find)")


# --- reading the log ---------------------------------------------------------

def stall_days() -> int:
    try:
        config = json.loads((root() / workspace.MARKER).read_text())
    except (OSError, json.JSONDecodeError):
        return 21
    dashboard = config.get("dashboard") if isinstance(config, dict) else None
    value = dashboard.get("stallDays") if isinstance(dashboard, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 21


def touches_of(slug: str, events: list[dict], merges: dict[str, str]) -> list[dict]:
    hits = [e for e in events if e["type"] == "touch" and merges.get(e.get("person"), e.get("person")) == slug]
    return sorted(hits, key=lambda e: e["ts"])


def last_touches(events: list[dict], merges: dict[str, str]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for e in events:
        if e["type"] != "touch":
            continue
        slug = merges.get(e.get("person"), e.get("person"))
        if slug not in latest or e["ts"] >= latest[slug]["ts"]:
            latest[slug] = e
    return latest


def intro_states(events: list[dict], merges: dict[str, str]) -> dict[str, dict]:
    """Current state of every intro: its latest event, with from/to/for/note
    carried forward from earlier events and people resolved through merges."""
    intros: dict[str, dict] = {}
    for e in sorted((e for e in events if e["type"] == "intro"), key=lambda e: e["ts"]):
        i = intros.setdefault(e["intro"], {"id": e["intro"], "from": "", "to": "", "for": "",
                                           "note": "", "offered": e["ts"], "history": []})
        i["history"].append({"status": e["status"], "ts": e["ts"]})
        for key in ("from", "to", "for", "note", "result", "opportunity"):
            if e.get(key):
                i[key] = e[key]
        i["status"], i["updated"], i["inferred"] = e["status"], e["ts"], e.get("inferred", False)
    for i in intros.values():
        i["from"] = merges.get(i["from"], i["from"])
        if not i["to"].startswith("org:"):
            i["to"] = merges.get(i["to"], i["to"])
    return intros


def next_intro_id(intros: dict[str, dict]) -> str:
    numbers = [int(k[2:]) for k in intros if k.startswith("i-") and k[2:].isdigit()]
    return f"i-{max(numbers, default=0) + 1}"


# --- generated contacts.md -----------------------------------------------------

GENERATED = "<!-- generated by people.py — edit people/ pages via people.py, not this file -->"
HAND_WRITTEN = "contacts.hand-written.md"


def opportunities_of(p: Person) -> set[str]:
    return {r.opportunity for r in p.roles if r.opportunity}


def linked_opportunities(people: dict[str, Person]) -> set[str]:
    return set().union(*(opportunities_of(p) for p in people.values()))


def render_contacts(opp: str, known: dict[str, dict], people: dict[str, Person]) -> str:
    info = known.get(opp)
    title = f"{info['company']} / {info['role']}" if info else opp
    rows = sorted((ROLES.index(r.role), p.name.casefold(), p.slug, p.name, r.role)
                  for p in people.values() for r in p.roles if r.opportunity == opp)
    lines = [f"# Contacts — {title}", "", GENERATED, "", "| Name | Role | Page |", "| --- | --- | --- |"]
    lines += [f"| {tracker.escape_cell(name)} | {role} | [[people/{slug}]] |"
              for _, _, slug, name, role in rows]
    return "\n".join(lines) + "\n"


def write_contacts(opp: str, known: dict[str, dict], people: dict[str, Person]) -> bool:
    """Regenerates one opportunity's contacts.md. A contacts.md people.py
    didn't generate is first appended to contacts.hand-written.md beside it,
    so its text survives. Returns True if the file changed."""
    folder = root() / "opportunity" / opp
    path = folder / "contacts.md"
    new = render_contacts(opp, known, people)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == new:
        return False
    folder.mkdir(parents=True, exist_ok=True)
    if old is not None and GENERATED not in old:
        backup = folder / HAND_WRITTEN
        prior = backup.read_text(encoding="utf-8") if backup.exists() else ""
        backup.write_text(prior + ("\n\n" if prior else "") + old, encoding="utf-8")
    path.write_text(new, encoding="utf-8")
    return True


def sync_contacts(opps, known: dict[str, dict], people: dict[str, Person]) -> list[str]:
    return [opp for opp in sorted(opps) if write_contacts(opp, known, people)]
