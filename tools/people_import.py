#!/usr/bin/env python3
"""One-time import of hand-written contacts.md files and networking.md into
person pages: `people.py import --draft` proposes, the user edits the draft,
`people.py import --apply <draft>` writes."""
import datetime
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import people_store as store  # noqa: E402
import tracker  # noqa: E402
from people_store import Person, PeopleError  # noqa: E402

DRAFT_NAME = "people-import-draft.md"
NETWORKING = "networking.md"
NETWORKING_BACKUP = "networking.hand-written.md"
NETWORKING_POINTER = "<!-- moved to people/ by people.py import -->"
PEOPLE_COLUMNS = ["#", "Name", "Org", "Title", "Email", "Roles", "Relationship", "Cadence", "Next touch", "Sources"]
INTRO_COLUMNS = ["From", "To", "For", "Result"]
CADENCE_DAYS = {"recruiter": 21, "connector": 30, "peer": 45}

_EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DATE_IN_TEXT = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FIELD_LINE = re.compile(r"^(?:[-*]\s+)?\*{0,2}([A-Za-z][A-Za-z /-]{0,30}?)\*{0,2}:\*{0,2}\s*(.*)$")
_PERSON_BULLET = re.compile(r"^[-*]\s+\*\*(.+?)\*\*\s*(?:—|–|-|:)\s*(.*)$")
_SEPARATOR_CELL = re.compile(r":?-{3,}:?")
_ROLE_PATTERNS = [
    ("recruiter", r"\b(recruit\w*|talent|sourc(?:er|ing)|headhunter|search firm)\b"),
    ("connector", r"\b(referr\w*|intro\w*|connector|champion|mutual|connected)\b"),
    ("hiring", r"\b(hiring|would report|reports? to|ceo|cto|cpo|coo|founder|co-founder)\b"),
    ("panelist", r"\b(panel\w*|interview\w*)\b"),
    ("peer", r"\b(peer|friend|colleague|network\w*)\b"),
]
# Words that mark a heading as structure ("## Hiring team"), not a person.
NOT_PEOPLE = {"contacts", "contact", "notes", "team", "hiring", "process", "people", "panel", "interviewers",
              "interview", "recruiters", "recruiter", "other", "others", "background", "summary", "overview",
              "network", "networking", "leadership", "connections", "mutual", "key", "open", "questions",
              "next", "steps", "status", "history", "update", "company", "role", "about", "sources",
              "links", "references", "timeline"}
PARTICLES = {"de", "da", "del", "della", "der", "di", "du", "la", "le", "van", "von", "bin", "al"}


@dataclass
class Candidate:
    name: str
    source: str               # "<file>:<line>"
    file: str
    opportunity: str = ""     # tracker slug; "" for networking.md or a folder the tracker doesn't know
    org: str = ""
    title: str = ""
    email: str = ""
    role_text: str = ""
    notes: str = ""

    def add_note(self, line: str) -> None:
        self.notes = f"{self.notes}\n{line}" if self.notes else line


@dataclass
class Row:
    num: int
    name: str
    org: str = ""
    title: str = ""
    email: str = ""
    roles: list = field(default_factory=list)   # list[str]; "?" allowed until apply
    relationship: str = "no"
    cadence: str = "none"
    next_touch: str = ""
    sources: list = field(default_factory=list)


@dataclass
class IntroRow:
    frm: str     # "#<row>"
    to: str      # "org:<Org>" or "#<row>"
    for_: str
    result: str


def find_email(text: str) -> str:
    m = _EMAIL_IN_TEXT.search(text)
    return m.group(0).rstrip(".") if m else ""


def looks_like_name(text: str) -> bool:
    words = re.sub(r"\(.*?\)", "", text).split()
    if not 1 <= len(words) <= 5:
        return False
    if {w.lower().strip(".,:;'") for w in words} & NOT_PEOPLE:
        return False
    return all(w[0].isupper() or w.lower() in PARTICLES for w in words)


def split_heading(title: str) -> tuple[str, str]:
    parts = re.split(r"\s+[—–-]\s+", title, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def _norm(label: str) -> str:
    return re.sub(r"[^a-z ]", "", label.lower()).strip()


def field_kind(label: str) -> str | None:
    h = _norm(label)
    if h in ("email", "email address"):
        return "email"
    if h in ("title", "position", "job title"):
        return "title"
    if h.startswith("role"):
        return "role"
    if h in ("company", "org", "organization", "organisation", "employer"):
        return "org"
    return None


def column_kind(header: str) -> str | None:
    h = _norm(header)
    if h in ("name", "contact", "person", "who"):
        return "name"
    if h.startswith("role at"):
        return "title"
    if h.startswith("note") or h.startswith("mutual") or h == "context":
        return "notes"
    if h in ("relationship", "part in process"):
        return "role"
    return field_kind(header)


def guess_role(c: Candidate) -> str:
    text = (c.role_text or f"{c.title} {c.notes}").lower()
    for role, pattern in _ROLE_PATTERNS:
        if re.search(pattern, text):
            return role
    return "?"


def absorb_line(c: Candidate, line: str) -> None:
    m = _FIELD_LINE.match(line)
    kind = field_kind(m.group(1)) if m else None
    value = m.group(2).strip() if m else ""
    if kind == "email":
        found = find_email(value)
        if found and not c.email:
            c.email = found
        if found and value != found:
            c.add_note(line)  # keeps extra text such as a second address
        return
    if kind == "title" and not c.title:
        c.title = value
        return
    if kind == "org":
        c.org = value
        return
    if kind == "role":
        c.role_text = f"{c.role_text} {value}".strip()
    c.add_note(line)


def parse_table_block(block, rel, first, opp, org):
    """(candidates, unparsed) for a table with a Name column, else None."""
    header = [tracker.unescape_cell(cell) for cell in tracker.split_row(block[0])]
    kinds = [column_kind(h) for h in header]
    if "name" not in kinds:
        return None
    cands, unparsed = [], []
    for k, line in enumerate(block[1:], start=1):
        n = first + k
        cells = [tracker.unescape_cell(cell) for cell in tracker.split_row(line)]
        if all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells):
            continue
        if len(cells) != len(header):
            unparsed.append(f"{rel}:{n}: {line}")
            continue
        c = Candidate(name="", source=f"{rel}:{n}", file=rel, opportunity=opp, org=org)
        for head, kind, value in zip(header, kinds, cells):
            if not value:
                continue
            if kind == "name":
                c.name = value
            elif kind == "title":
                c.title = value
            elif kind == "org":
                c.org = value
            elif kind == "email":
                c.email = find_email(value)
                if c.email and value != c.email:
                    c.add_note(f"{head}: {value}")
            elif kind == "notes":
                c.add_note(value)
            else:
                if kind == "role":
                    c.role_text = value
                c.add_note(f"{head}: {value}")
        if c.name:
            cands.append(c)
        else:
            unparsed.append(f"{rel}:{n}: {line}")
    return cands, unparsed


def parse_contacts(text: str, rel: str, opp: str = "", org: str = ""):
    """People in one hand-written file: table rows, `## Name` sections and
    `- **Name** — …` bullets. Every other non-blank line is reported."""
    lines = text.splitlines()
    cands, unparsed = [], []
    current = None
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        n = i + 1
        if not stripped or stripped.startswith("<!--"):
            i += 1
            continue
        if stripped.startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            block = [line.strip() for line in lines[i:j]]
            parsed = parse_table_block(block, rel, n, opp, org)
            if parsed is not None:
                cands += parsed[0]
                unparsed += parsed[1]
            elif current is not None:
                for line in block:
                    current.add_note(line)
            else:
                unparsed += [f"{rel}:{n + k}: {line}" for k, line in enumerate(block)
                             if not all(_SEPARATOR_CELL.fullmatch(cell) for cell in tracker.split_row(line))]
            i = j
            continue
        heading = _HEADING.match(stripped)
        if heading:
            current = None
            if len(heading.group(1)) >= 2:
                name, rest = split_heading(heading.group(2))
                if looks_like_name(name):
                    current = Candidate(name=name, source=f"{rel}:{n}", file=rel, opportunity=opp,
                                        org=org, title=rest)
                    cands.append(current)
        elif current is not None:
            absorb_line(current, stripped)
        else:
            bullet = _PERSON_BULLET.match(stripped)
            if bullet and looks_like_name(bullet.group(1)) and field_kind(bullet.group(1)) is None:
                rest = bullet.group(2).strip()
                c = Candidate(name=bullet.group(1).strip(), source=f"{rel}:{n}", file=rel, opportunity=opp,
                              org=org, email=find_email(rest), role_text=rest)
                c.add_note(rest)
                cands.append(c)
            else:
                unparsed.append(f"{rel}:{n}: {stripped}")
        i += 1
    return cands, unparsed


def collect(root: Path, known: dict):
    """Candidates from every hand-written contacts.md (generated ones are
    skipped) and networking.md, the unparsed lines, and the tracker
    opportunities those contacts.md files belong to."""
    cands, unparsed, opps = [], [], []
    base = root / "opportunity"
    for path in sorted(base.glob("*/*/contacts.md")):
        text = path.read_text(encoding="utf-8")
        if store.GENERATED in text:
            continue
        rel = path.relative_to(root).as_posix()
        folder = "/".join(path.parent.relative_to(base).parts)
        info = known.get(folder)
        found, skipped = parse_contacts(text, rel, folder if info else "", info["company"] if info else "")
        cands += found
        unparsed += skipped
        if info:
            opps.append(folder)
    net = root / NETWORKING
    if net.exists() and NETWORKING_POINTER not in (text := net.read_text(encoding="utf-8")):
        found, skipped = parse_contacts(text, NETWORKING)
        for c in found:  # "## Name — Org - Role"
            if " - " in c.title:
                c.org, c.title = (part.strip() for part in c.title.split(" - ", 1))
        cands += found
        unparsed += skipped
    return cands, unparsed, opps


def group_candidates(cands: list[Candidate]) -> list[list[Candidate]]:
    """Same email -> same person; same exact name + same org -> same person."""
    parent = list(range(len(cands)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    first_seen = {}
    for i, c in enumerate(cands):
        keys = [("name", c.name.casefold(), c.org.casefold())]
        if c.email:
            keys.append(("email", c.email.casefold()))
        for key in keys:
            if key in first_seen:
                a, b = find(first_seen[key]), find(i)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                first_seen[key] = i
    groups: dict[int, list[Candidate]] = {}
    for i, c in enumerate(cands):
        groups.setdefault(find(i), []).append(c)
    return list(groups.values())


def _valid_date(text: str) -> bool:
    try:
        datetime.date.fromisoformat(text)
        return True
    except ValueError:
        return False


def make_rows(cands: list[Candidate], today: datetime.date) -> list[Row]:
    rows = []
    for group in group_candidates(cands):
        roles = []
        for c in group:
            guess = guess_role(c)
            if guess == "?" and not c.opportunity:
                guess = "peer"  # networking.md, or an opportunity the tracker no longer has
            item = f"{guess} @ {c.opportunity}" if c.opportunity else guess
            if item not in roles:
                roles.append(item)
        orgs = Counter(c.org for c in group if c.org)
        row = Row(num=0, name=group[0].name, org=orgs.most_common(1)[0][0] if orgs else "",
                  title=next((c.title for c in group if c.title), ""),
                  email=next((c.email for c in group if c.email), ""),
                  roles=roles, sources=[c.source for c in group])
        days = [CADENCE_DAYS[item.split(" @ ")[0]] for item in roles if item.split(" @ ")[0] in CADENCE_DAYS]
        if days:
            row.relationship, row.cadence = "yes", f"{min(days)}d"
            dates = [d for c in group for d in _DATE_IN_TEXT.findall(f"{c.role_text} {c.notes}") if _valid_date(d)]
            if dates:
                latest = datetime.date.fromisoformat(max(dates))
                row.next_touch = (latest + datetime.timedelta(days=min(days))).isoformat()
        rows.append(row)
    today_text = today.isoformat()
    rows.sort(key=lambda r: (0, r.next_touch, r.name.casefold()) if r.next_touch and r.next_touch < today_text
              else (1, "", r.name.casefold()))
    for num, row in enumerate(rows, start=1):
        row.num = num
    return rows


def same_person_suggestions(rows: list[Row]) -> list[tuple[int, int, str]]:
    out = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            low, high = sorted((a.num, b.num))
            if a.name.casefold() == b.name.casefold():
                out.append((low, high, "same name"))
            elif (a.email and b.email and a.email.split("@")[1].casefold() == b.email.split("@")[1].casefold()
                  and a.name.split()[0].casefold() == b.name.split()[0].casefold()):
                out.append((low, high, "same first name and email domain"))
    return sorted(out)


def proposed_intros(rows: list[Row], known: dict) -> list[IntroRow]:
    """A connector on an opportunity means an intro that led to it."""
    out = []
    for row in rows:
        for item in row.roles:
            role, _, opp = item.partition(" @ ")
            if role == "connector" and opp in known:
                out.append(IntroRow(frm=f"#{row.num}", to=f"org:{known[opp]['company']}", for_=opp,
                                    result="led_to_opportunity"))
    return out


def _table(columns: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    return lines + ["| " + " | ".join(tracker.escape_cell(cell) for cell in row) + " |" for row in rows]


def render_draft(draft_id, rows, suggestions, intros, unparsed) -> str:
    out = ["# People import draft", "", f"<!-- people.py import draft {draft_id} -->", "",
           "Review this draft, then run `people.py import --apply people-import-draft.md`.", "",
           "- Replace every `?` in Roles with one of: " + ", ".join(store.ROLES) + ".",
           "- Delete a row to leave that person out.",
           "- Tick a box under *Same person?* (`[x]`) to merge those rows into the lower-numbered one.",
           "- Rows with a Next touch before today come first.", "",
           "## People", ""]
    out += _table(PEOPLE_COLUMNS, [[str(r.num), r.name, r.org, r.title, r.email, ", ".join(r.roles),
                                    r.relationship, r.cadence, r.next_touch, "; ".join(r.sources)] for r in rows])
    out += ["", "## Same person?", ""]
    out += [f"- [ ] {a} = {b} — {why}" for a, b, why in suggestions] or ["(none)"]
    out += ["", "## Intros (inferred)", ""]
    out += _table(INTRO_COLUMNS, [[i.frm, i.to, i.for_, i.result] for i in intros])
    out += ["", "## Unparsed", ""]
    out += [f"- {line}" for line in unparsed] or ["(none)"]
    return "\n".join(out) + "\n"


def _sections(text: str) -> dict[str, list[tuple[int, str]]]:
    sections, name = {}, None
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            name = line[3:].strip()
            sections[name] = []
        elif name is not None:
            sections[name].append((n, line))
    return sections


def _parse_table(lines, columns, what):
    table = [(n, line.strip()) for n, line in lines if line.strip().startswith("|")]
    if not table:
        return []
    n0, header = table[0]
    if [tracker.unescape_cell(cell) for cell in tracker.split_row(header)] != columns:
        raise PeopleError(f"{DRAFT_NAME}:{n0}: the {what} table's columns must be: {' | '.join(columns)}")
    rows = []
    for n, line in table[1:]:
        cells = [tracker.unescape_cell(cell) for cell in tracker.split_row(line)]
        if all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells):
            continue
        if len(cells) != len(columns):
            raise PeopleError(f"{DRAFT_NAME}:{n}: expected {len(columns)} cells, got {len(cells)}")
        rows.append((n, dict(zip(columns, cells))))
    return rows


def parse_draft(text: str):
    m = re.search(r"<!-- people\.py import draft (d-\d{8}T\d{6}) -->", text)
    if not m:
        raise PeopleError("not a people.py import draft (its id line is missing)")
    sections = _sections(text)
    if "People" not in sections:
        raise PeopleError("the draft has no '## People' section")
    rows = _parse_table(sections["People"], PEOPLE_COLUMNS, "People")
    merges = []
    for n, line in sections.get("Same person?", []):
        tick = re.match(r"\s*[-*]\s*\[[xX]\]\s*#?(\d+)\s*=\s*#?(\d+)", line)
        if tick:
            merges.append((n, int(tick.group(1)), int(tick.group(2))))
    intros = _parse_table(sections.get("Intros (inferred)", []), INTRO_COLUMNS, "Intros")
    return m.group(1), rows, merges, intros


def write_draft(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    root = store.root()
    with store.locked():
        known = tracker.known_opportunities()
        cands, unparsed, _ = collect(root, known)
    if not cands:
        raise PeopleError("nothing to import: no hand-written contacts.md or networking.md entries found")
    rows = make_rows(cands, today)
    draft_id = f"d-{datetime.datetime.now():%Y%m%dT%H%M%S}"
    text = render_draft(draft_id, rows, same_person_suggestions(rows), proposed_intros(rows, known), unparsed)
    (root / DRAFT_NAME).write_text(text, encoding="utf-8")
    overdue = sum(1 for r in rows if r.next_touch and r.next_touch < today.isoformat())
    unknown = sum(1 for r in rows if any(item.startswith("?") for item in r.roles))
    return (f"wrote {DRAFT_NAME}: {len(rows)} people from {len({c.file for c in cands})} files; "
            f"{unknown} need a role (?), {overdue} overdue, {len(unparsed)} unparsed lines")
