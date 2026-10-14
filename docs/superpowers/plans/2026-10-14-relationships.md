# Relationships Tracker v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every person in the job search one page, give relationships a follow-up rhythm, and track intros as a pipeline, with each opportunity's `contacts.md` generated from the people pages.

**Architecture:** Three stdlib-only Python modules in `tools/`:
- `people_store.py` holds the page format, the event log, slugs, follow-up and intro rules, and `contacts.md` generation.
- `people.py` is the CLI and the only entry point skills call.
- `people_import.py` is the one-time migration from hand-written `contacts.md` files and `networking.md`.

`tracker.py` gains a reusable file lock and a list of known opportunities. Skills and the persona switch from hand-editing `contacts.md` to calling `people.py`.

**Tech Stack:** Python 3.10+ stdlib (`unittest`, `dataclasses`, `argparse`, `json`, `re`). No dashboard changes.

**Spec:** `docs/superpowers/specs/2026-10-04-relationships-design.md`

## Global Constraints

- Python tools and tests are stdlib only. Every tool sets `sys.dont_write_bytecode = True` before importing a sibling module.
- `people.py` is the sole writer of `people/`, `people_events.jsonl` and the generated `contacts.md`. `tracker.py` stays the sole writer of the tracker files.
- Skills call tools only as `python3 "${CLAUDE_PLUGIN_ROOT}/tools/<x>.py"` (`tools/run_tests.sh` enforces this).
- Field keys, in this order: `name` (required), `org`, `title`, `email`, `relationship` (`yes`/`no`, default `no`), `cadence` (`<N>d` or `none`, default `none`), `next_touch` (`YYYY-MM-DD` or empty), `roles`, `aliases`.
- Roles: `recruiter | connector | hiring | peer | panelist | other`. `contacts.md` row order: recruiter, hiring, connector, peer, panelist, other, then name.
- Slugs come from `tracker.slugify` (lowercase, `_` separators). A slug never changes; collisions get `_2`, `_3`…
- Event types: `person` (`add`/`update`/`merge`/`role`), `touch` (channels `call`/`email`/`meeting`/`message`/`other`), `intro` (`offered`/`made`/`met`/`closed`; results `led_to_opportunity`/`led_to_intros`/`dead_end`). Every event has `ts`, `type`, `inferred`.
- `stallDays` is `dashboard.stallDays` in `.job-search-os.json`, default 21.
- Every validation happens before any write. Errors print `error: …` to stderr and exit 1.
- No real people, companies or emails in the repo: tests and examples use invented data (Northwind Motors, Bluefin Security, `example.com`).
- Never send anything. Skills draft only.

## Plan decisions beyond the spec

The spec leaves these open, or real data forced a choice. Each is pinned by a test in the task named.

1. `intro offer` takes `--to <person>` or `--to-org "<Org>"` rather than one `--to` that guesses (Task 7).
2. Follow-up rule: a touch on day D sets `next_touch = max(D + cadence, current next_touch)`. This gives the spec's behavior (an explicit later date survives, an earlier one is replaced) without storing whether a date was explicit. It also means a backdated touch never pulls `next_touch` earlier. With `cadence: none`, a touch clears a `next_touch` on or before D (Task 6).
3. `touch` is idempotent. A second identical touch (same person, channel, day and note) is a no-op, so running morning-scan twice in a day doesn't double-count (Task 6).
4. Dates for `touch` and `intro` may not be in the future, and an intro step may not predate its last step (Tasks 6 and 7).
5. Before the first generation of a `contacts.md` that `people.py` didn't write, the file is appended to `contacts.hand-written.md` beside it, so nothing is lost (Task 4).
6. Files in `people/` whose names start with `_` are not person pages. This leaves room for the future index (Task 3).
7. Import also reads `## Name` heading sections with `Email:` lines and `- **Field:** value` bullets, because most real `contacts.md` files use that shape, not only tables (Task 10).
8. Import proposes intros only from connector roles: a connector on an opportunity means an intro that `led_to_opportunity`. *Same person?* suggestions come from an identical name or the same first name plus email domain. Free-text notes aren't mined for intros or alias hints (Task 10).
9. Import refuses rows that duplicate an existing page (same email, or same name and org). Opportunity folders not in the tracker get bare roles, and their `contacts.md` is left as is (Task 11).
10. `merge` fills the kept person's blank org/title/email from the dropped one. Values that differ are listed under `## Merged from <name>` (Task 8).
11. `emails` requires `--active` or `--opportunity` (Task 5).

## Review Focus

1. **A hand-written `contacts.md` is overwritten** the first time `people.py` touches that opportunity, before or without an import. Expect the old text preserved in `contacts.hand-written.md`. Pinned in Task 4.
2. **A new person gets a merged-away slug.** After a merge removes `d_reyes`, someone later added as "D. Reyes" must not get `d_reyes` back, or the old touches and intros would attach to them. Pinned in Task 3 (allocation avoids slugs seen in events) and Task 8.
3. **Morning-scan runs twice in a day** and logs each email touch twice, pushing `next_touch` and inflating counts. Expect the second run to be a no-op. Pinned in Task 6.
4. **A non-person file lands in `people/`** (an index, an Obsidian scratch note). Expect `_`-prefixed files to be ignored; anything else fails every command with the file and line named, writing nothing. Pinned in Task 3.
5. **The user logs an old conversation** (`touch --date` last month). Expect `next_touch` not to move earlier, and a mistyped future date to be rejected. Pinned in Task 6.

---

### Task 1: tracker.py — reusable lock and known opportunities

**Files:**
- Modify: `tools/tracker.py` (`locked()`, `_export_row`; new `file_lock`, `opportunity_slug`, `known_opportunities`)
- Test: `tools/test_tracker.py`

**Interfaces:**
- Produces:
  - `tracker.file_lock(lock: Path, timeout: float = 10.0, holder: str = "tracker.py")`, a context manager.
  - `tracker.opportunity_slug(company: str, role: str) -> str`, giving `"<slugify(company)>/<slugify(role)>"`.
  - `tracker.known_opportunities() -> dict[str, dict]`, mapping slug to `{"company", "role", "active": bool}`. The most recent row wins and an active row beats a closed one.

- [ ] **Step 1: Write the failing tests** (append to `tools/test_tracker.py`)

```python
class KnownOpportunitiesTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        workspace.init_root(".")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _row(self, company, role):
        return {"Company": company, "Role": role, "Stage": "Applied", "Last Activity": "2026-09-01",
                "Next Action": "", "Next Action Date": "", "Source": "Other"}

    def test_slug_format(self):
        self.assertEqual(tracker.opportunity_slug("Northwind Motors", "VP of Engineering"),
                         "northwind_motors/vp_of_engineering")

    def test_active_and_closed_rows_are_known_and_active_wins(self):
        tracker.write_table(tracker.active_path(), [self._row("Northwind Motors", "VP of Engineering")],
                            tracker.ACTIVE_TITLE)
        tracker.write_table(tracker.closed_path(), [
            {**self._row("Northwind Motors", "VP of Engineering"), "Outcome": "Rejected"},
            {**self._row("Bluefin Security", "Head of Platform"), "Outcome": "Passed"},
        ], tracker.CLOSED_TITLE, tracker.CLOSED_COLUMNS)
        known = tracker.known_opportunities()
        self.assertEqual(known["northwind_motors/vp_of_engineering"],
                         {"company": "Northwind Motors", "role": "VP of Engineering", "active": True})
        self.assertFalse(known["bluefin_security/head_of_platform"]["active"])

    def test_empty_workspace_has_no_opportunities(self):
        self.assertEqual(tracker.known_opportunities(), {})

    def test_file_lock_on_another_path_does_not_block_the_tracker_lock(self):
        with tracker.file_lock(Path(".people.lock"), holder="people.py"):
            with tracker.locked(timeout=0.5):
                pass
        self.assertFalse(Path(".people.lock").exists())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_tracker.KnownOpportunitiesTest -v` (from the repo root)
Expected: FAIL, `AttributeError: module 'tracker' has no attribute 'opportunity_slug'` (and `file_lock`, `known_opportunities`).

- [ ] **Step 3: Implement**

Replace `locked()` in `tools/tracker.py` with a generic lock plus the tracker's own:

```python
@contextmanager
def file_lock(lock: Path, timeout: float = 10.0, holder: str = "tracker.py"):
    """Exclusive-create lock file (portable, stdlib-only). Used for the
    tracker's lock and, by people.py, for its own."""
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
                    f"— another {holder} process may be stuck; if you're sure "
                    "none is running, delete the lock file manually",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def locked(timeout: float = 10.0):
    """Mutual exclusion for read-modify-write cycles against tracker.md /
    tracker_closed.md. Concurrent invocations (e.g. morning-scan recording
    several calendar events in parallel) would otherwise race: both read
    the same snapshot, and the later write silently clobbers the earlier
    one. Uses exclusive file creation (portable across platforms) rather
    than fcntl/msvcrt, to stay stdlib-only without a POSIX-only import.
    """
    with file_lock(lock_path(), timeout):
        yield
```

After `opportunity_path`, add:

```python
def opportunity_slug(company: str, role: str) -> str:
    """The "<company>/<role>" key used by export and by people.py roles."""
    return f"{slugify(company)}/{slugify(role)}"


def known_opportunities() -> dict[str, dict]:
    """Every opportunity in tracker.md or tracker_closed.md by slug. For a
    repeat application the latest row wins, and an active row beats closed."""
    with locked():
        active = read_table(active_path())
        closed = read_table(closed_path(), CLOSED_COLUMNS)
    known = {}
    for rows, is_active in ((closed, False), (active, True)):
        for row in rows:
            known[opportunity_slug(row["Company"], row["Role"])] = {
                "company": row["Company"], "role": row["Role"], "active": is_active}
    return known
```

In `_export_row`, replace the `"slug"` line with `"slug": opportunity_slug(row["Company"], row["Role"]),`.

- [ ] **Step 4: Run the tracker tests**

Run: `python3 -m unittest tools.test_tracker -v`
Expected: all PASS (including the existing concurrency and lock-leak tests).

- [ ] **Step 5: Commit**

```bash
git add tools/tracker.py tools/test_tracker.py
git commit -m "tracker: reusable file lock and known_opportunities for people.py"
```

---

### Task 2: people_store.py — the person page format

**Files:**
- Create: `tools/people_store.py`
- Test: `tools/test_people_store.py`

**Interfaces:**
- Produces:
  - Constants `FIELD_ORDER`, `ROLES`, `CHANNELS`, `INTRO_STATUSES`, `INTRO_RESULTS`.
  - `class PeopleError(Exception)`.
  - `@dataclass Role(role: str, opportunity: str = "")`, where `str(role)` gives `"recruiter @ a/b"` or `"peer"`.
  - `@dataclass Person(slug, name, org="", title="", email="", relationship="no", cadence="none", next_touch="", roles: list[Role], aliases: list[str], body="\n## Notes\n")`.
  - `split_list(value) -> list[str]`, `parse_date(value, what="date") -> datetime.date` and `parse_role(text) -> Role`.
  - `check_field(key, value) -> None` and `check_person(p) -> None`, both raising `PeopleError`.
  - `parse_page(text, slug, where) -> Person` and `serialize_page(p) -> str`.

- [ ] **Step 1: Write the failing tests** (`tools/test_people_store.py`)

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import people_store as store  # noqa: E402
from people_store import Person, PeopleError, Role  # noqa: E402

CANONICAL = """---
name: Dana Reyes
org: Northwind Motors
title: Senior Manager, Technical Recruiting
email: dana.reyes@example.com
relationship: yes
cadence: 21d
next_touch: 2026-10-23
roles: recruiter @ northwind_motors/vp_of_engineering, connector @ bluefin_security/head_of_platform
aliases: Dana Reyes-Kim
---

## Notes
Met at a meetup.
"""


class PageFormatTest(unittest.TestCase):
    def test_canonical_page_round_trips_byte_for_byte(self):
        p = store.parse_page(CANONICAL, "dana_reyes", "people/dana_reyes.md")
        self.assertEqual(store.serialize_page(p), CANONICAL)

    def test_parsed_fields(self):
        p = store.parse_page(CANONICAL, "dana_reyes", "x")
        self.assertEqual(p.slug, "dana_reyes")
        self.assertEqual(p.title, "Senior Manager, Technical Recruiting")
        self.assertEqual(p.roles, [Role("recruiter", "northwind_motors/vp_of_engineering"),
                                   Role("connector", "bluefin_security/head_of_platform")])
        self.assertEqual(p.aliases, ["Dana Reyes-Kim"])
        self.assertEqual(p.body, "\n## Notes\nMet at a meetup.\n")

    def test_person_round_trips_through_text(self):
        p = Person(slug="lee_park", name="Lée Park, Jr.", org="Bluefin, Inc.", email="lee+jobs@example.com",
                   roles=[Role("peer")], aliases=["Lee P."])
        self.assertEqual(store.parse_page(store.serialize_page(p), "lee_park", "x"), p)

    def test_body_preserved_with_dashes_trailing_space_and_crlf(self):
        body = "\n## Notes\n---\ntrailing   \r\n---\n\n\n"
        p = Person(slug="a", name="A", body=body)
        self.assertEqual(store.parse_page(store.serialize_page(p), "a", "x").body, body)

    def test_unset_keys_omitted_and_order_fixed(self):
        p = Person(slug="a", name="A", email="a@example.com")
        self.assertEqual(store.serialize_page(p),
                         "---\nname: A\nemail: a@example.com\nrelationship: no\ncadence: none\n---\n\n## Notes\n")

    def test_hand_written_order_and_missing_defaults_are_accepted(self):
        p = store.parse_page("---\nemail: a@example.com\nname: A\n---\nbody", "a", "x")
        self.assertEqual((p.name, p.relationship, p.cadence, p.body), ("A", "no", "none", "body"))

    def assertPageError(self, text, *fragments):
        with self.assertRaises(PeopleError) as cm:
            store.parse_page(text, "a", "people/a.md")
        for fragment in fragments:
            self.assertIn(fragment, str(cm.exception))

    def test_errors_name_file_and_line(self):
        self.assertPageError("---\nname: A\nnot a field line\n---\n", "people/a.md:3", "key: value")
        self.assertPageError("---\nname: A\nfavorite: x\n---\n", "people/a.md:3", "unknown key 'favorite'")
        self.assertPageError("---\nname: A\ncadence: weekly\n---\n", "people/a.md:3", "cadence")
        self.assertPageError("---\nname: A\nrelationship: maybe\n---\n", "people/a.md:3", "yes or no")
        self.assertPageError("---\nname: A\nnext_touch: 10/23\n---\n", "people/a.md:3", "YYYY-MM-DD")
        self.assertPageError("---\nname: A\nemail: not on file\n---\n", "people/a.md:3", "email")
        self.assertPageError("---\nname: A\nroles: boss @ a/b\n---\n", "people/a.md:3", "unknown role 'boss'")
        self.assertPageError("---\nname: A\nroles: peer @ Acme\n---\n", "people/a.md:3", "slug")
        self.assertPageError("---\nname: A\nname: B\n---\n", "people/a.md:3", "twice")
        self.assertPageError("---\norg: Acme\n---\n", "people/a.md", "'name' is required")
        self.assertPageError("---\nname: A\n", "no closing")
        self.assertPageError("name: A\n", "people/a.md:1", "'---'")

    def test_check_person_rejects_multiline_and_comma_alias(self):
        with self.assertRaises(PeopleError):
            store.check_person(Person(slug="a", name="A", title="two\nlines"))
        with self.assertRaises(PeopleError):
            store.check_person(Person(slug="a", name="A", aliases=["Reyes, Dana"]))
        with self.assertRaises(PeopleError):
            store.check_person(Person(slug="a", name=" "))

    def test_parse_role_accepts_compact_cli_form(self):
        self.assertEqual(store.parse_role("Recruiter@northwind_motors/vp_of_engineering"),
                         Role("recruiter", "northwind_motors/vp_of_engineering"))
        self.assertEqual(str(store.parse_role("peer")), "peer")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people_store -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'people_store'`.

- [ ] **Step 3: Implement** (`tools/people_store.py`)

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people_store -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people_store.py tools/test_people_store.py
git commit -m "people_store: person page field block format"
```

---

### Task 3: people_store.py — pages on disk, events, slugs, lookup

**Files:**
- Modify: `tools/people_store.py` (append)
- Create: `tools/people_testkit.py` (shared test workspace, used by Tasks 3–11)
- Test: `tools/test_people_store.py` (append)

**Interfaces:**
- Consumes: `tracker.file_lock`, `tracker.now_ts`, `tracker.slugify` (Task 1); `Person`, `parse_page`, `serialize_page`, `check_person` (Task 2).
- Produces:
  - Paths: `root() -> Path`, `people_dir() -> Path`, `events_path() -> Path`, `page_path(slug) -> Path`, and `locked()` (context manager, `.people.lock`).
  - Pages: `load_people() -> dict[str, Person]`, `save_person(p)` and `delete_person(slug)`.
  - Events: `append_event(event: dict)`, `read_events() -> tuple[list[dict], list[str]]`, `merged_into(events) -> dict[str, str]` (dropped slug to surviving slug, chains followed) and `used_slugs(people, events) -> set[str]`.
  - Slugs and lookup: `allocate_slug(name, used) -> str`, `describe(p) -> str` (`"slug  Name (Org)"`) and `resolve(text, people, merges) -> Person`.
  - Event queries: `stall_days() -> int`, `touches_of(slug, events, merges) -> list[dict]`, `last_touches(events, merges) -> dict[str, dict]`, `intro_states(events, merges) -> dict[str, dict]` and `next_intro_id(intros) -> str`.
  - `people_testkit.WorkspaceTestCase` with `root`, `tracker()`, `people()`, `people_error()`, `page()`, `contacts()`, `events()` and `set_config()`, plus constants `NW`, `BF`.

- [ ] **Step 1: Create the test kit** (`tools/people_testkit.py`)

```python
"""Shared setup for the people tests: a temp workspace holding two tracker
opportunities (Northwind Motors / VP of Engineering, active; Bluefin
Security / Head of Platform, active), and helpers to run the tools in it.
Invented data only."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).parent
sys.path.insert(0, str(TOOLS))
import workspace  # noqa: E402

NW = "northwind_motors/vp_of_engineering"
BF = "bluefin_security/head_of_platform"


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        os.chdir(self.root)
        workspace.init_root(".")
        self.tracker("add", "Northwind Motors", "VP of Engineering", "--stage", "Applied", "--source", "Other")
        self.tracker("add", "Bluefin Security", "Head of Platform", "--stage", "Identified", "--source", "Other")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _run(self, tool, *args):
        return subprocess.run([sys.executable, str(TOOLS / tool), *args], capture_output=True, text=True)

    def tracker(self, *args):
        result = self._run("tracker.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def people(self, *args):
        result = self._run("people.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def people_error(self, *args):
        result = self._run("people.py", *args)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        return result.stderr

    def page(self, slug):
        return (self.root / "people" / f"{slug}.md").read_text()

    def contacts(self, opp):
        return (self.root / "opportunity" / opp / "contacts.md").read_text()

    def events(self):
        path = self.root / "people_events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def set_config(self, **values):
        marker = self.root / workspace.MARKER
        config = json.loads(marker.read_text())
        config.update(values)
        marker.write_text(json.dumps(config))
```

- [ ] **Step 2: Write the failing tests** (append to `tools/test_people_store.py`, above the `__main__` guard)

```python
from people_testkit import WorkspaceTestCase  # noqa: E402  (put with the other imports at the top)


class StoreOnDiskTest(WorkspaceTestCase):
    def test_no_people_dir_means_no_people(self):
        self.assertEqual(store.load_people(), {})

    def test_save_then_load(self):
        p = Person(slug="dana_reyes", name="Dana Reyes", email="dana.reyes@example.com")
        store.save_person(p)
        self.assertEqual(store.load_people(), {"dana_reyes": p})

    def test_hand_edited_page_is_reread(self):
        store.save_person(Person(slug="dana_reyes", name="Dana Reyes"))
        path = self.root / "people" / "dana_reyes.md"
        path.write_text(path.read_text().replace("name: Dana Reyes", "name: Dana Reyes\ntitle: Recruiter")
                        + "Hand-written line.\n")
        p = store.load_people()["dana_reyes"]
        self.assertEqual(p.title, "Recruiter")
        self.assertTrue(p.body.endswith("Hand-written line.\n"))

    def test_underscore_files_are_not_people(self):
        (self.root / "people").mkdir()
        (self.root / "people" / "_index.md").write_text("# Index\n")
        self.assertEqual(store.load_people(), {})

    def test_malformed_page_names_file_and_line(self):
        (self.root / "people").mkdir()
        (self.root / "people" / "dana_reyes.md").write_text("---\nname: Dana\nbogus\n---\n")
        with self.assertRaises(PeopleError) as cm:
            store.load_people()
        self.assertIn("people/dana_reyes.md:3", str(cm.exception))

    def test_file_name_that_is_not_a_slug_is_an_error(self):
        (self.root / "people").mkdir()
        (self.root / "people" / "Dana Reyes.md").write_text("---\nname: Dana\n---\n")
        with self.assertRaises(PeopleError) as cm:
            store.load_people()
        self.assertIn("Dana Reyes.md", str(cm.exception))

    def test_events_round_trip_and_bad_lines_warn(self):
        store.append_event({"type": "touch", "person": "a", "channel": "email", "note": ""})
        with store.events_path().open("a") as f:
            f.write("not json\n{\"type\": \"touch\"}\n")
        events, warnings = store.read_events()
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["inferred"])
        self.assertEqual(len(warnings), 2)

    def test_allocate_slug_numbers_collisions(self):
        self.assertEqual(store.allocate_slug("Dana Reyes", set()), "dana_reyes")
        self.assertEqual(store.allocate_slug("Dana Reyes", {"dana_reyes"}), "dana_reyes_2")
        self.assertEqual(store.allocate_slug("Dana Reyes", {"dana_reyes", "dana_reyes_2"}), "dana_reyes_3")

    def test_used_slugs_include_slugs_only_in_events(self):
        events = [{"ts": "x", "type": "person", "person": "dana_reyes", "action": "merge",
                   "detail": {"from": "dana_reyes_2"}}]
        self.assertEqual(store.used_slugs({}, events), {"dana_reyes", "dana_reyes_2"})

    def test_merged_into_follows_chains(self):
        events = [{"ts": "1", "type": "person", "person": "b", "action": "merge", "detail": {"from": "a"}},
                  {"ts": "2", "type": "person", "person": "c", "action": "merge", "detail": {"from": "b"}}]
        self.assertEqual(store.merged_into(events), {"a": "c", "b": "c"})

    def _people(self):
        return {p.slug: p for p in [
            Person(slug="dana_reyes", name="Dana Reyes", org="Northwind Motors", email="Dana@Example.com",
                   aliases=["Dana Reyes-Kim"]),
            Person(slug="dana_reyes_2", name="Dana Reyes", org="Bluefin Security"),
            Person(slug="lee_park", name="Lee Park")]}

    def test_resolve_by_slug_email_name_alias(self):
        people = self._people()
        self.assertEqual(store.resolve("lee_park", people, {}).slug, "lee_park")
        self.assertEqual(store.resolve("dana@example.COM", people, {}).slug, "dana_reyes")
        self.assertEqual(store.resolve("lee park", people, {}).slug, "lee_park")
        self.assertEqual(store.resolve("Dana Reyes-Kim", people, {}).slug, "dana_reyes")

    def test_resolve_merged_away_slug_finds_survivor(self):
        self.assertEqual(store.resolve("old_slug", self._people(), {"old_slug": "lee_park"}).slug, "lee_park")

    def test_resolve_ambiguous_lists_candidates_with_org(self):
        with self.assertRaises(PeopleError) as cm:
            store.resolve("Dana Reyes", self._people(), {})
        self.assertIn("dana_reyes  Dana Reyes (Northwind Motors)", str(cm.exception))
        self.assertIn("dana_reyes_2  Dana Reyes (Bluefin Security)", str(cm.exception))

    def test_resolve_never_fuzzy(self):
        with self.assertRaises(PeopleError):
            store.resolve("Dana", self._people(), {})

    def test_stall_days(self):
        self.assertEqual(store.stall_days(), 21)
        self.set_config(dashboard={"stallDays": 30})
        self.assertEqual(store.stall_days(), 30)
        self.set_config(dashboard={"stallDays": "soon"})
        self.assertEqual(store.stall_days(), 21)

    def test_intro_states_take_latest_event_and_resolve_merges(self):
        events = [
            {"ts": "2026-09-01T09:00:00", "type": "intro", "intro": "i-1", "status": "offered",
             "from": "old", "to": "org:Bluefin Security", "for": "", "note": "coffee"},
            {"ts": "2026-09-05T09:00:00", "type": "intro", "intro": "i-1", "status": "made"},
        ]
        i = store.intro_states(events, {"old": "lee_park"})["i-1"]
        self.assertEqual((i["status"], i["from"], i["to"], i["updated"], i["offered"]),
                         ("made", "lee_park", "org:Bluefin Security", "2026-09-05T09:00:00",
                          "2026-09-01T09:00:00"))
        self.assertEqual(store.next_intro_id({"i-1": i, "i-9": i}), "i-10")
        self.assertEqual(store.next_intro_id({}), "i-1")

    def test_touches_resolve_merges(self):
        events = [{"ts": "2026-09-01T09:00:00", "type": "touch", "person": "old", "channel": "email", "note": ""},
                  {"ts": "2026-09-03T09:00:00", "type": "touch", "person": "lee_park", "channel": "call", "note": ""}]
        merges = {"old": "lee_park"}
        self.assertEqual(len(store.touches_of("lee_park", events, merges)), 2)
        self.assertEqual(store.last_touches(events, merges)["lee_park"]["channel"], "call")
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people_store -v`
Expected: the new tests ERROR with `AttributeError: module 'people_store' has no attribute 'load_people'` (etc.).

- [ ] **Step 4: Implement** (append to `tools/people_store.py`)

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tools.test_people_store -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/people_store.py tools/test_people_store.py tools/people_testkit.py
git commit -m "people_store: pages on disk, event log, slugs, lookup"
```

---

### Task 4: people_store.py — generated contacts.md

**Files:**
- Modify: `tools/people_store.py` (append)
- Test: `tools/test_people_store.py` (append)

**Interfaces:**
- Consumes: `tracker.escape_cell`, the shape of `tracker.known_opportunities()` (Task 1), and `Person`/`Role` and `root()` (Tasks 2–3).
- Produces:
  - Constants `GENERATED` (the comment line) and `HAND_WRITTEN = "contacts.hand-written.md"`.
  - `opportunities_of(p) -> set[str]` and `linked_opportunities(people) -> set[str]`.
  - `render_contacts(opp, known, people) -> str`.
  - `write_contacts(opp, known, people) -> bool` (True if the file changed).
  - `sync_contacts(opps, known, people) -> list[str]` (the opportunities whose file changed).

- [ ] **Step 1: Write the failing tests** (append to `tools/test_people_store.py`)

```python
from people_testkit import BF, NW  # noqa: E402  (put with the other imports at the top)


class ContactsTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.known = {NW: {"company": "Northwind Motors", "role": "VP of Engineering", "active": True}}
        self.people = {p.slug: p for p in [
            Person(slug="zoe_ng", name="Zoe Ng", roles=[Role("panelist", NW)]),
            Person(slug="ann_bo", name="Ann | Bo", roles=[Role("panelist", NW), Role("connector", NW)]),
            Person(slug="dana_reyes", name="Dana Reyes", roles=[Role("recruiter", NW), Role("peer")]),
            Person(slug="lee_park", name="Lee Park", roles=[Role("hiring", BF)]),
        ]}

    def test_render(self):
        self.assertEqual(store.render_contacts(NW, self.known, self.people), (
            "# Contacts — Northwind Motors / VP of Engineering\n\n"
            f"{store.GENERATED}\n\n"
            "| Name | Role | Page |\n| --- | --- | --- |\n"
            "| Dana Reyes | recruiter | [[people/dana_reyes]] |\n"
            "| Ann \\| Bo | connector | [[people/ann_bo]] |\n"
            "| Ann \\| Bo | panelist | [[people/ann_bo]] |\n"
            "| Zoe Ng | panelist | [[people/zoe_ng]] |\n"))

    def test_render_without_people_or_tracker_row(self):
        text = store.render_contacts("gone_co/cto", {}, {})
        self.assertTrue(text.startswith("# Contacts — gone_co/cto\n"))
        self.assertTrue(text.endswith("| Name | Role | Page |\n| --- | --- | --- |\n"))

    def test_linked_opportunities_ignore_bare_roles(self):
        self.assertEqual(store.linked_opportunities(self.people), {NW, BF})

    def test_first_write_keeps_hand_written_file(self):
        folder = self.root / "opportunity" / NW
        folder.mkdir(parents=True)
        (folder / "contacts.md").write_text("# Contacts\n\n## Dana Reyes\nRecruiter.\n")
        self.assertTrue(store.write_contacts(NW, self.known, self.people))
        self.assertEqual((folder / store.HAND_WRITTEN).read_text(), "# Contacts\n\n## Dana Reyes\nRecruiter.\n")
        self.assertIn(store.GENERATED, (folder / "contacts.md").read_text())
        # A later regeneration doesn't back up the generated file.
        self.people["zoe_ng"].name = "Zoe Ng-Lam"
        self.assertTrue(store.write_contacts(NW, self.known, self.people))
        self.assertEqual((folder / store.HAND_WRITTEN).read_text(), "# Contacts\n\n## Dana Reyes\nRecruiter.\n")

    def test_unchanged_content_is_not_rewritten(self):
        store.write_contacts(NW, self.known, self.people)
        self.assertFalse(store.write_contacts(NW, self.known, self.people))

    def test_sync_creates_missing_folders_and_reports_changes(self):
        changed = store.sync_contacts({NW, BF}, self.known, self.people)
        self.assertEqual(changed, sorted([BF, NW]))
        self.assertTrue((self.root / "opportunity" / BF / "contacts.md").exists())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people_store.ContactsTest -v`
Expected: ERROR, `AttributeError: module 'people_store' has no attribute 'render_contacts'`.

- [ ] **Step 3: Implement** (append to `tools/people_store.py`)

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people_store -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people_store.py tools/test_people_store.py
git commit -m "people_store: generated contacts.md with hand-written backup"
```

---
### Task 5: people.py — add, update, role, show, find, emails, sync-contacts

**Files:**
- Create: `tools/people.py`
- Test: `tools/test_people.py`

**Interfaces:**
- Consumes: all of `people_store` from Tasks 2–4; `tracker.known_opportunities()` (Task 1).
- Produces:
  - `people.State(people, events, merges, known)` and `load_state() -> State`.
  - `require_opportunities(roles, known)`, `find_duplicate(st, name, org, email, skip="") -> Person | None`, `label(slug_or_org, people) -> str` and `format_intro(i, people, today=None) -> str`.
  - `build_parser()` and `main(argv=None)`.
  - Subcommands added here: `add`, `update`, `role`, `show`, `find`, `emails`, `sync-contacts`. Tasks 6–9 and 11 add the rest to `build_parser()`.

- [ ] **Step 1: Write the failing tests** (`tools/test_people.py`)

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import people_store as store  # noqa: E402
from people_testkit import BF, NW, WorkspaceTestCase  # noqa: E402


class AddTest(WorkspaceTestCase):
    def test_add_writes_page_event_and_contacts(self):
        out = self.people("add", "Dana Reyes", "--org", "Northwind Motors", "--title", "Recruiter",
                          "--email", "dana.reyes@example.com", "--role", f"recruiter@{NW}",
                          "--relationship", "yes", "--cadence", "21d", "--next-touch", "2026-10-23")
        self.assertIn("dana_reyes", out)
        self.assertEqual(self.page("dana_reyes"), (
            "---\nname: Dana Reyes\norg: Northwind Motors\ntitle: Recruiter\n"
            "email: dana.reyes@example.com\nrelationship: yes\ncadence: 21d\nnext_touch: 2026-10-23\n"
            f"roles: recruiter @ {NW}\n---\n\n## Notes\n"))
        [event] = self.events()
        self.assertEqual((event["type"], event["person"], event["action"]), ("person", "dana_reyes", "add"))
        self.assertIn("| Dana Reyes | recruiter | [[people/dana_reyes]] |", self.contacts(NW))

    def test_unknown_opportunity_writes_nothing(self):
        err = self.people_error("add", "Dana Reyes", "--role", "recruiter@nope/cto")
        self.assertIn("not an opportunity in the tracker", err)
        self.assertFalse((self.root / "people").exists())
        self.assertEqual(self.events(), [])

    def test_invalid_field_writes_nothing(self):
        self.people_error("add", "Dana Reyes", "--email", "not on file")
        self.people_error("add", "Dana Reyes", "--cadence", "weekly")
        self.assertFalse((self.root / "people").exists())

    def test_duplicates_are_refused_and_named(self):
        self.people("add", "Dana Reyes", "--org", "Northwind Motors", "--email", "dana.reyes@example.com")
        self.assertIn("dana_reyes", self.people_error("add", "D. Reyes", "--email", "DANA.REYES@example.com"))
        self.assertIn("dana_reyes", self.people_error("add", "dana reyes", "--org", "northwind motors"))

    def test_same_name_other_org_gets_numbered_slug(self):
        self.people("add", "Dana Reyes", "--org", "Northwind Motors")
        self.assertIn("dana_reyes_2", self.people("add", "Dana Reyes", "--org", "Bluefin Security"))


class UpdateAndRoleTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.people("add", "Dana Reyes", "--org", "Northwind Motors", "--email", "dana.reyes@example.com",
                    "--role", f"recruiter@{NW}")

    def _hand_edit_contacts(self):
        path = self.root / "opportunity" / NW / "contacts.md"
        path.write_text(path.read_text() + "hand edit\n")

    def test_field_change_leaves_contacts_alone(self):
        self._hand_edit_contacts()
        self.people("update", "dana_reyes", "--title", "Director of Recruiting", "--org", "Northwind")
        self.assertIn("title: Director of Recruiting", self.page("dana_reyes"))
        self.assertIn("hand edit", self.contacts(NW))

    def test_rename_keeps_slug_regenerates_contacts_and_old_name_resolves(self):
        self._hand_edit_contacts()
        self.people("update", "dana_reyes", "--name", "Dana Reyes-Kim")
        page = self.page("dana_reyes")
        self.assertIn("name: Dana Reyes-Kim", page)
        self.assertIn("aliases: Dana Reyes", page)
        self.assertNotIn("hand edit", self.contacts(NW))
        self.assertIn("| Dana Reyes-Kim | recruiter |", self.contacts(NW))
        self.assertIn("dana_reyes", self.people("show", "Dana Reyes"))

    def test_update_to_another_persons_email_is_refused(self):
        self.people("add", "Lee Park", "--email", "lee.park@example.com")
        self.assertIn("dana_reyes", self.people_error("update", "lee_park", "--email", "dana.reyes@example.com"))

    def test_update_needs_a_change(self):
        self.assertIn("nothing to update", self.people_error("update", "dana_reyes"))

    def test_role_add_and_drop_regenerate_both_opportunities(self):
        self.people("role", "dana_reyes", "--add", f"connector@{BF}", "--drop", f"recruiter@{NW}")
        self.assertIn("| Dana Reyes | connector |", self.contacts(BF))
        self.assertNotIn("Dana Reyes", self.contacts(NW))
        self.assertEqual(self.events()[-1]["action"], "role")

    def test_dropping_a_role_they_do_not_have_fails(self):
        self.assertIn("has no role", self.people_error("role", "dana_reyes", "--drop", f"peer@{NW}"))


class ReadCommandsTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.people("add", "Dana Reyes", "--org", "Northwind Motors", "--email", "dana.reyes@example.com",
                    "--role", f"recruiter@{NW}")
        self.people("add", "Lee Park", "--email", "lee.park@example.com", "--relationship", "yes")
        self.people("add", "Sam Ortiz", "--email", "sam.ortiz@example.com", "--role", f"hiring@{BF}")
        self.people("add", "Kim Vo", "--role", f"panelist@{NW}")
        self.people("update", "lee_park", "--name", "Lee Park")  # no-op rename: no alias added

    def test_show(self):
        out = self.people("show", "dana.reyes@example.com")
        for fragment in ("Dana Reyes  [dana_reyes]", "org: Northwind Motors", f"recruiter @ {NW}",
                         "Recent touches: none", "Open intros: none", "people/dana_reyes.md"):
            self.assertIn(fragment, out)
        self.assertNotIn("aliases", self.people("show", "lee_park"))

    def test_find_matches_name_org_email(self):
        self.assertIn("dana_reyes", self.people("find", "northwind"))
        self.assertIn("lee_park", self.people("find", "LEE.PARK@"))
        self.assertIn("no one matches", self.people("find", "zzz"))

    def test_emails_active(self):
        self.tracker("close", "Bluefin Security", "Head of Platform", "--outcome", "Passed", "--reason", "x")
        self.assertEqual(self.people("emails", "--active").split(),
                         ["dana.reyes@example.com", "lee.park@example.com"])

    def test_emails_for_one_opportunity(self):
        self.assertEqual(self.people("emails", "--opportunity", BF).split(), ["sam.ortiz@example.com"])

    def test_emails_needs_a_scope(self):
        self.assertNotEqual(self._run("people.py", "emails").returncode, 0)

    def test_sync_contacts_rebuilds_every_linked_opportunity(self):
        (self.root / "opportunity" / NW / "contacts.md").unlink()
        self.assertIn(NW, self.people("sync-contacts"))
        self.assertIn("| Kim Vo | panelist |", self.contacts(NW))

    def test_malformed_page_fails_every_command_naming_the_line(self):
        (self.root / "people" / "dana_reyes.md").write_text("---\nname: Dana\nbogus\n---\n")
        self.assertIn("people/dana_reyes.md:3", self.people_error("show", "lee_park"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people -v`
Expected: every test FAILs (`people.py` doesn't exist; exit code 2 from Python).

- [ ] **Step 3: Implement** (`tools/people.py`)

```python
#!/usr/bin/env python3
"""CLI for the relationships tracker: people pages, touches and intros.

The only code that writes people/, people_events.jsonl and the generated
opportunity/*/*/contacts.md files. Skills call it as
`python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" <command> ...`.
"""
import argparse
import datetime
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import people_store as store  # noqa: E402
import tracker  # noqa: E402
from people_store import Person, PeopleError, Role  # noqa: E402


@dataclass
class State:
    people: dict
    events: list
    merges: dict
    known: dict


def load_state() -> State:
    """Everything a command needs, read once. Call with store.locked() held."""
    events, _ = store.read_events()
    return State(store.load_people(), events, store.merged_into(events), tracker.known_opportunities())


def require_opportunities(roles, known) -> None:
    for r in roles:
        if r.opportunity and r.opportunity not in known:
            raise PeopleError(f"{r.opportunity!r} is not an opportunity in the tracker "
                              "(slugs: tracker.py export --json)")


def find_duplicate(st: State, name: str, org: str, email: str, skip: str = "") -> Person | None:
    for p in st.people.values():
        if p.slug == skip:
            continue
        if email and p.email.casefold() == email.casefold():
            return p
        if p.name.casefold() == name.casefold() and p.org.casefold() == org.casefold():
            return p
    return None


def label(slug_or_org: str, people: dict) -> str:
    if slug_or_org.startswith("org:"):
        return slug_or_org[4:]
    p = people.get(slug_or_org)
    return p.name if p else slug_or_org


def format_intro(i: dict, people: dict, today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    since = i["updated"][:10]
    age = (today - datetime.date.fromisoformat(since)).days
    text = f"{i['id']}  {label(i['from'], people)} → {label(i['to'], people)}  {i['status']}"
    if i.get("result"):
        text += f" ({i['result']}" + (f": {i['opportunity']}" if i.get("opportunity") else "") + ")"
    if i.get("for"):
        text += f"  for {i['for']}"
    return text + f"  {age}d since {since}"


def cmd_add(args):
    with store.locked():
        st = load_state()
        roles = []
        for text in args.role:
            role = store.parse_role(text)
            if role not in roles:
                roles.append(role)
        require_opportunities(roles, st.known)
        name, org, email = args.name.strip(), args.org.strip(), args.email.strip()
        dup = find_duplicate(st, name, org, email)
        if dup:
            raise PeopleError(f"already have {store.describe(dup)} — use update or role")
        p = Person(slug=store.allocate_slug(name, store.used_slugs(st.people, st.events)),
                   name=name, org=org, title=args.title.strip(), email=email,
                   relationship=args.relationship, cadence=args.cadence, next_touch=args.next_touch,
                   roles=roles)
        store.save_person(p)
        store.append_event({"type": "person", "person": p.slug, "action": "add", "detail": {}})
        st.people[p.slug] = p
        store.sync_contacts(store.opportunities_of(p), st.known, st.people)
    print(f"added {store.describe(p)}")


UPDATE_FIELDS = ("name", "org", "title", "email", "relationship", "cadence", "next_touch")


def cmd_update(args):
    changes = {key: getattr(args, key).strip() for key in UPDATE_FIELDS if getattr(args, key) is not None}
    if not changes:
        raise PeopleError("nothing to update (pass at least one field flag)")
    with store.locked():
        st = load_state()
        p = store.resolve(args.person, st.people, st.merges)
        new = {key: changes.get(key, getattr(p, key)) for key in UPDATE_FIELDS}
        dup = find_duplicate(st, new["name"], new["org"], new["email"], skip=p.slug)
        if dup:
            raise PeopleError(f"that would duplicate {store.describe(dup)}")
        renamed = new["name"] != p.name
        if renamed:
            old = p.name
            p.aliases = [a for a in p.aliases if a.casefold() != new["name"].casefold()]
            if old.casefold() not in {a.casefold() for a in p.aliases}:
                p.aliases.append(old)
        for key, value in changes.items():
            setattr(p, key, value)
        store.save_person(p)
        store.append_event({"type": "person", "person": p.slug, "action": "update", "detail": changes})
        if renamed:
            store.sync_contacts(store.opportunities_of(p), st.known, st.people)
    print(f"updated {store.describe(p)}")


def cmd_role(args):
    if not args.add and not args.drop:
        raise PeopleError("role needs --add and/or --drop")
    with store.locked():
        st = load_state()
        p = store.resolve(args.person, st.people, st.merges)
        adds = [store.parse_role(r) for r in args.add]
        drops = [store.parse_role(r) for r in args.drop]
        require_opportunities(adds, st.known)
        for r in drops:
            if r not in p.roles:
                raise PeopleError(f"{p.slug} has no role {r}")
        before = store.opportunities_of(p)
        p.roles = [r for r in p.roles if r not in drops]
        for r in adds:
            if r not in p.roles:
                p.roles.append(r)
        store.save_person(p)
        store.append_event({"type": "person", "person": p.slug, "action": "role",
                            "detail": {"add": [str(r) for r in adds], "drop": [str(r) for r in drops]}})
        store.sync_contacts(before | store.opportunities_of(p), st.known, st.people)
    print(f"roles for {p.slug}: " + (", ".join(str(r) for r in p.roles) or "none"))


def cmd_show(args):
    with store.locked():
        st = load_state()
        p = store.resolve(args.person, st.people, st.merges)
        touches = store.touches_of(p.slug, st.events, st.merges)[-10:]
        intros = [i for i in store.intro_states(st.events, st.merges).values()
                  if i["status"] != "closed" and p.slug in (i["from"], i["to"])]
    print(f"{p.name}  [{p.slug}]")
    for key in ("org", "title", "email"):
        if getattr(p, key):
            print(f"  {key}: {getattr(p, key)}")
    print(f"  relationship: {p.relationship}  cadence: {p.cadence}  next touch: {p.next_touch or '—'}")
    if p.roles:
        print("  roles: " + ", ".join(str(r) for r in p.roles))
    if p.aliases:
        print("  aliases: " + ", ".join(p.aliases))
    print("Recent touches:" if touches else "Recent touches: none")
    for t in reversed(touches):
        print(f"  {t['ts'][:10]}  {t['channel']}" + (f"  {t['note']}" if t.get("note") else ""))
    print("Open intros:" if intros else "Open intros: none")
    for i in intros:
        print("  " + format_intro(i, st.people))
    print(f"Page: people/{p.slug}.md")


def cmd_find(args):
    wanted = args.text.casefold()
    with store.locked():
        people = store.load_people()
    hits = [p for p in people.values()
            if any(wanted in value.casefold() for value in (p.name, p.org, p.email, *p.aliases))]
    for p in sorted(hits, key=lambda p: p.slug):
        print(store.describe(p) + (f"  {p.email}" if p.email else ""))
    if not hits:
        print(f"no one matches {args.text!r}")


def cmd_emails(args):
    with store.locked():
        st = load_state()
    active = {slug for slug, info in st.known.items() if info["active"]}
    found: dict[str, str] = {}
    for p in st.people.values():
        if not p.email:
            continue
        if args.opportunity:
            hit = args.opportunity in store.opportunities_of(p)
        else:
            hit = p.relationship == "yes" or bool(store.opportunities_of(p) & active)
        if hit:
            found.setdefault(p.email.casefold(), p.email)
    for email in sorted(found.values(), key=str.casefold):
        print(email)


def cmd_sync_contacts(args):
    with store.locked():
        st = load_state()
        opps = {args.opportunity} if args.opportunity else store.linked_opportunities(st.people)
        changed = store.sync_contacts(opps, st.known, st.people)
    print("regenerated: " + (", ".join(changed) or "nothing changed"))


def build_parser():
    parser = argparse.ArgumentParser(description="People, follow-ups and intros")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("name")
    p_add.add_argument("--org", default="")
    p_add.add_argument("--title", default="")
    p_add.add_argument("--email", default="")
    p_add.add_argument("--role", action="append", default=[], help="ROLE@<company>/<role> or a bare ROLE")
    p_add.add_argument("--relationship", choices=["yes", "no"], default="no")
    p_add.add_argument("--cadence", default="none", help="<N>d or none")
    p_add.add_argument("--next-touch", dest="next_touch", default="")
    p_add.set_defaults(func=cmd_add)

    p_update = sub.add_parser("update")
    p_update.add_argument("person")
    for key in UPDATE_FIELDS:
        p_update.add_argument("--" + key.replace("_", "-"), dest=key)
    p_update.set_defaults(func=cmd_update)

    p_role = sub.add_parser("role")
    p_role.add_argument("person")
    p_role.add_argument("--add", action="append", default=[])
    p_role.add_argument("--drop", action="append", default=[])
    p_role.set_defaults(func=cmd_role)

    p_show = sub.add_parser("show")
    p_show.add_argument("person")
    p_show.set_defaults(func=cmd_show)

    p_find = sub.add_parser("find")
    p_find.add_argument("text")
    p_find.set_defaults(func=cmd_find)

    p_emails = sub.add_parser("emails")
    scope = p_emails.add_mutually_exclusive_group(required=True)
    scope.add_argument("--active", action="store_true",
                       help="people linked to an active opportunity, plus relationship: yes")
    scope.add_argument("--opportunity")
    p_emails.set_defaults(func=cmd_emails)

    p_sync = sub.add_parser("sync-contacts")
    p_sync.add_argument("--opportunity")
    p_sync.set_defaults(func=cmd_sync_contacts)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except PeopleError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

(`json` and `re` are used by Tasks 6 and 9; leave the imports.)

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people.py tools/test_people.py
git commit -m "people.py: add, update, role, show, find, emails, sync-contacts"
```

---

### Task 6: touches, the follow-up rule and `due`

**Files:**
- Modify: `tools/people_store.py` (append `event_ts`, `apply_touch`, `due_people`)
- Modify: `tools/people.py` (add `cmd_touch`, `cmd_due`, `parse_within`; register `touch`, `due`)
- Test: `tools/test_people_store.py`, `tools/test_people.py` (append)

**Interfaces:**
- Consumes: `touches_of`, `last_touches`, `intro_states`, `stall_days` (Task 3).
- Produces:
  - `store.event_ts(day: str | None, today: datetime.date | None = None) -> str`.
  - `store.apply_touch(p: Person, day: datetime.date) -> None`.
  - `store.due_people(people, today, within_days) -> list[Person]`.
  - The `touch <person> --channel C [--date D] [--note N]` command.
  - The `due [--within Nd]` command, which prints three sections: `Due relationships:`, `Stalled intros:` and `Open intros:`, or `Nothing due.`.

- [ ] **Step 1: Write the failing tests**

Append to `tools/test_people_store.py`:

```python
import datetime  # noqa: E402  (put with the other imports at the top)


class FollowUpRuleTest(unittest.TestCase):
    D = datetime.date(2026, 10, 1)

    def _person(self, **fields):
        return Person(slug="a", name="A", relationship="yes", cadence="21d", **fields)

    def test_touch_sets_next_touch_from_cadence(self):
        p = self._person()
        store.apply_touch(p, self.D)
        self.assertEqual(p.next_touch, "2026-10-22")

    def test_later_explicit_date_survives(self):
        p = self._person(next_touch="2026-12-01")
        store.apply_touch(p, self.D)
        self.assertEqual(p.next_touch, "2026-12-01")

    def test_earlier_date_is_replaced(self):
        p = self._person(next_touch="2026-10-05")
        store.apply_touch(p, self.D)
        self.assertEqual(p.next_touch, "2026-10-22")

    def test_backdated_touch_never_pulls_next_touch_earlier(self):
        p = self._person()
        store.apply_touch(p, self.D)
        store.apply_touch(p, datetime.date(2026, 9, 1))
        self.assertEqual(p.next_touch, "2026-10-22")

    def test_cadence_none_clears_a_date_that_has_been_met(self):
        p = self._person(next_touch="2026-09-30")
        p.cadence = "none"
        store.apply_touch(p, self.D)
        self.assertEqual(p.next_touch, "")
        p.next_touch = "2026-11-01"
        store.apply_touch(p, self.D)
        self.assertEqual(p.next_touch, "2026-11-01")

    def test_not_a_relationship_is_untouched(self):
        p = Person(slug="a", name="A", cadence="21d", next_touch="2026-09-01")
        store.apply_touch(p, self.D)
        self.assertEqual(p.next_touch, "2026-09-01")

    def test_event_ts(self):
        today = datetime.date(2026, 10, 14)
        self.assertEqual(store.event_ts("2026-10-01", today), "2026-10-01T09:00:00")
        with self.assertRaises(PeopleError):
            store.event_ts("2026-10-15", today)

    def test_due_people_window_and_order(self):
        today = datetime.date(2026, 10, 14)
        people = {p.slug: p for p in [
            Person(slug="late", name="Late", relationship="yes", next_touch="2026-10-01"),
            Person(slug="today", name="Today", relationship="yes", next_touch="2026-10-14"),
            Person(slug="edge", name="Edge", relationship="yes", next_touch="2026-10-17"),
            Person(slug="out", name="Out", relationship="yes", next_touch="2026-10-18"),
            Person(slug="no", name="No", relationship="no", next_touch="2026-10-01"),
            Person(slug="never", name="Never", relationship="yes"),
        ]}
        self.assertEqual([p.slug for p in store.due_people(people, today, 3)], ["late", "today", "edge"])
        self.assertEqual([p.slug for p in store.due_people(people, today, 0)], ["late", "today"])
```

Append to `tools/test_people.py`:

```python
import concurrent.futures  # noqa: E402  (put with the other imports at the top)
import datetime  # noqa: E402
import subprocess  # noqa: E402

TODAY = datetime.date.today()


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


class TouchTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.people("add", "Dana Reyes", "--email", "dana.reyes@example.com", "--relationship", "yes",
                    "--cadence", "21d")

    def test_touch_logs_event_and_rolls_next_touch(self):
        self.people("touch", "dana.reyes@example.com", "--channel", "email", "--date", days_ago(5),
                    "--note", "Re: coffee")
        event = self.events()[-1]
        self.assertEqual((event["type"], event["person"], event["channel"], event["note"]),
                         ("touch", "dana_reyes", "email", "Re: coffee"))
        self.assertEqual(event["ts"], f"{days_ago(5)}T09:00:00")
        expected = (TODAY + datetime.timedelta(days=16)).isoformat()
        self.assertIn(f"next_touch: {expected}", self.page("dana_reyes"))

    def test_touch_today_uses_the_current_time(self):
        self.people("touch", "dana_reyes", "--channel", "call")
        self.assertTrue(self.events()[-1]["ts"].startswith(TODAY.isoformat() + "T"))
        self.assertNotEqual(self.events()[-1]["ts"], f"{TODAY.isoformat()}T09:00:00")

    def test_same_touch_twice_is_logged_once(self):
        for _ in range(2):
            self.people("touch", "dana_reyes", "--channel", "email", "--date", days_ago(1), "--note", "Re: x")
        self.assertEqual(sum(e["type"] == "touch" for e in self.events()), 1)

    def test_future_date_is_rejected(self):
        tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
        self.assertIn("future", self.people_error("touch", "dana_reyes", "--channel", "call", "--date", tomorrow))

    def test_concurrent_touches_do_not_clobber(self):
        names = [f"Person {i}" for i in range(8)]
        for name in names:
            self.people("add", name, "--relationship", "yes", "--cadence", "30d")

        def touch(name):
            return subprocess.run([sys.executable, str(Path(__file__).parent / "people.py"), "touch", name,
                                   "--channel", "email"], capture_output=True, text=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
            results = list(pool.map(touch, names))
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sum(e["type"] == "touch" for e in self.events()), len(names))
        expected = (TODAY + datetime.timedelta(days=30)).isoformat()
        for name in names:
            self.assertIn(f"next_touch: {expected}", self.page(name.lower().replace(" ", "_")))


class DueTest(WorkspaceTestCase):
    def test_nothing_due(self):
        self.assertEqual(self.people("due").strip(), "Nothing due.")

    def test_overdue_first_with_last_touch(self):
        self.people("add", "Soon Person", "--relationship", "yes", "--next-touch",
                    (TODAY + datetime.timedelta(days=2)).isoformat())
        self.people("add", "Late Person", "--relationship", "yes", "--cadence", "21d")
        self.people("touch", "late_person", "--channel", "email", "--date", days_ago(30))
        out = self.people("due", "--within", "3d")
        self.assertLess(out.index("Late Person"), out.index("Soon Person"))
        self.assertIn("9d overdue", out)
        self.assertIn(f"last touch {days_ago(30)} (email)", out)
        self.assertIn("due in 2d", out)
        self.assertNotIn("Soon Person", self.people("due"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people_store.FollowUpRuleTest tools.test_people.TouchTest tools.test_people.DueTest -v`
Expected: the store tests ERROR with `AttributeError: … 'apply_touch'`, and the CLI tests FAIL with `invalid choice: 'touch'`.

- [ ] **Step 3: Implement**

Append to `tools/people_store.py`:

```python
# --- follow-ups ------------------------------------------------------------------

def event_ts(day: str | None, today: datetime.date | None = None) -> str:
    """Timestamp for an event on `day` (default today): the current time for
    today, 09:00 for an earlier day. A future day is an error."""
    today = today or datetime.date.today()
    when = parse_date(day, "--date") if day else today
    if when > today:
        raise PeopleError(f"--date {when} is in the future")
    return tracker.now_ts() if when == today else f"{when.isoformat()}T09:00:00"


def apply_touch(p: Person, day: datetime.date) -> None:
    """The follow-up rule: next_touch = max(day + cadence, current next_touch).
    With cadence none, a next_touch on or before the touch is cleared."""
    if p.relationship != "yes":
        return
    current = parse_date(p.next_touch, "next_touch") if p.next_touch else None
    if p.cadence == "none":
        if current is not None and current <= day:
            p.next_touch = ""
        return
    proposed = day + datetime.timedelta(days=int(p.cadence[:-1]))
    if current is None or proposed > current:
        p.next_touch = proposed.isoformat()


def due_people(people: dict[str, Person], today: datetime.date, within_days: int) -> list[Person]:
    horizon = (today + datetime.timedelta(days=within_days)).isoformat()
    hits = [p for p in people.values() if p.relationship == "yes" and p.next_touch and p.next_touch <= horizon]
    return sorted(hits, key=lambda p: (p.next_touch, p.slug))
```

In `tools/people.py`, add after `cmd_sync_contacts`:

```python
def cmd_touch(args):
    with store.locked():
        st = load_state()
        p = store.resolve(args.person, st.people, st.merges)
        ts = store.event_ts(args.date)
        day = ts[:10]
        for t in store.touches_of(p.slug, st.events, st.merges):
            if t["ts"][:10] == day and t["channel"] == args.channel and (t.get("note") or "") == args.note:
                print(f"already logged: {p.name}, {args.channel}, {day}")
                return
        store.apply_touch(p, datetime.date.fromisoformat(day))
        store.save_person(p)
        store.append_event({"ts": ts, "type": "touch", "person": p.slug,
                            "channel": args.channel, "note": args.note})
    print(f"touched {p.name} ({args.channel}, {day}); next touch {p.next_touch or 'none'}")


def parse_within(text: str) -> int:
    m = re.fullmatch(r"(\d+)d?", text.strip())
    if not m:
        raise PeopleError(f"--within must look like 3d, got {text!r}")
    return int(m.group(1))


def cmd_due(args):
    within = parse_within(args.within)
    today = datetime.date.today()
    with store.locked():
        st = load_state()
        intros = store.intro_states(st.events, st.merges)
        stall = store.stall_days()
    due = store.due_people(st.people, today, within)
    last = store.last_touches(st.events, st.merges)
    open_intros = sorted((i for i in intros.values() if i["status"] != "closed"), key=lambda i: i["updated"])
    stalled = [i for i in open_intros
               if (today - datetime.date.fromisoformat(i["updated"][:10])).days >= stall]
    waiting = [i for i in open_intros if i not in stalled]
    if not (due or open_intros):
        print("Nothing due.")
        return
    if due:
        print("Due relationships:")
        for p in due:
            delta = (datetime.date.fromisoformat(p.next_touch) - today).days
            when = f"{-delta}d overdue" if delta < 0 else ("due today" if delta == 0 else f"due in {delta}d")
            t = last.get(p.slug)
            tail = f" — last touch {t['ts'][:10]} ({t['channel']})" if t else " — no touches logged"
            print(f"  {p.next_touch}  {when}  {store.describe(p)}{tail}")
    if stalled:
        print(f"Stalled intros (no movement in {stall}+ days):")
        for i in stalled:
            print("  " + format_intro(i, st.people, today))
    if waiting:
        print("Open intros:")
        for i in waiting:
            print("  " + format_intro(i, st.people, today))
```

Register both in `build_parser()`, before `return parser`:

```python
    p_touch = sub.add_parser("touch")
    p_touch.add_argument("person")
    p_touch.add_argument("--channel", required=True, choices=store.CHANNELS)
    p_touch.add_argument("--date")
    p_touch.add_argument("--note", default="")
    p_touch.set_defaults(func=cmd_touch)

    p_due = sub.add_parser("due")
    p_due.add_argument("--within", default="0d")
    p_due.set_defaults(func=cmd_due)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people_store tools.test_people -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people_store.py tools/people.py tools/test_people_store.py tools/test_people.py
git commit -m "people: touches, follow-up rule, due"
```

---

### Task 7: intros

**Files:**
- Modify: `tools/people.py` (add `cmd_intro_offer`, `cmd_intro_advance`, `cmd_intro_close`, `cmd_intro_list`; register `intro` with sub-commands)
- Test: `tools/test_people.py` (append)

**Interfaces:**
- Consumes: `intro_states`, `next_intro_id`, `event_ts` and `stall_days` (Tasks 3 and 6); `require_opportunities`, `format_intro` and `cmd_due` (Tasks 5–6).
- Produces the intro commands:
  - `intro offer <from> (--to <person> | --to-org <Org>) [--for opp] [--date D] [--note N]`, which prints the new id.
  - `intro made|met <id> [--date D]`.
  - `intro close <id> --result R [--opportunity opp] [--date D]`.
  - `intro list [--open]`.

- [ ] **Step 1: Write the failing tests** (append to `tools/test_people.py`)

```python
class IntroTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.people("add", "Dana Reyes", "--org", "Northwind Motors")
        self.people("add", "Lee Park", "--org", "Bluefin Security")

    def offer(self, *extra):
        return self.people("intro", "offer", "dana_reyes", *extra).strip()

    def test_offer_prints_sequential_ids(self):
        self.assertEqual(self.offer("--to", "lee_park"), "i-1")
        self.assertEqual(self.offer("--to-org", "Bluefin Security"), "i-2")
        event = self.events()[-1]
        self.assertEqual((event["status"], event["from"], event["to"]), ("offered", "dana_reyes", "org:Bluefin Security"))

    def test_offer_for_an_opportunity_adds_the_connector_role(self):
        self.offer("--to-org", "Bluefin Security", "--for", BF)
        self.assertIn(f"connector @ {BF}", self.page("dana_reyes"))
        self.assertIn("| Dana Reyes | connector |", self.contacts(BF))

    def test_offer_for_unknown_opportunity_writes_nothing(self):
        before = len(self.events())
        self.people_error("intro", "offer", "dana_reyes", "--to", "lee_park", "--for", "nope/cto")
        self.assertEqual(len(self.events()), before)

    def test_offer_needs_exactly_one_target_and_not_self(self):
        self.assertNotEqual(self._run("people.py", "intro", "offer", "dana_reyes").returncode, 0)
        self.assertIn("themselves", self.people_error("intro", "offer", "dana_reyes", "--to", "dana_reyes"))

    def test_lifecycle_forward_only(self):
        self.offer("--to", "lee_park", "--date", days_ago(10))
        self.people("intro", "made", "i-1", "--date", days_ago(8))
        self.assertIn("forward", self.people_error("intro", "made", "i-1"))
        self.assertIn("before", self.people_error("intro", "met", "i-1", "--date", days_ago(9)))
        self.people("intro", "met", "i-1")
        self.assertIn("forward", self.people_error("intro", "made", "i-1"))

    def test_skip_forward_is_allowed(self):
        self.offer("--to", "lee_park")
        self.people("intro", "met", "i-1")
        self.assertEqual(self.events()[-1]["status"], "met")

    def test_close_rules(self):
        self.offer("--to", "lee_park")
        self.assertIn("--opportunity", self.people_error("intro", "close", "i-1", "--result", "led_to_opportunity"))
        self.people_error("intro", "close", "i-1", "--result", "led_to_opportunity", "--opportunity", "nope/cto")
        self.people("intro", "close", "i-1", "--result", "led_to_opportunity", "--opportunity", BF)
        self.assertEqual((self.events()[-1]["result"], self.events()[-1]["opportunity"]), ("led_to_opportunity", BF))
        self.assertIn("closed", self.people_error("intro", "made", "i-1"))
        self.assertIn("closed", self.people_error("intro", "close", "i-1", "--result", "dead_end"))

    def test_unknown_intro(self):
        self.assertIn("i-9", self.people_error("intro", "made", "i-9"))

    def test_list(self):
        self.offer("--to", "lee_park")
        self.offer("--to-org", "Bluefin Security")
        self.people("intro", "close", "i-2", "--result", "dead_end")
        out = self.people("intro", "list")
        self.assertIn("i-1  Dana Reyes → Lee Park  offered", out)
        self.assertIn("i-2  Dana Reyes → Bluefin Security  closed (dead_end)", out)
        self.assertNotIn("i-2", self.people("intro", "list", "--open"))

    def test_due_separates_stalled_from_open(self):
        self.offer("--to", "lee_park", "--date", days_ago(30))
        self.offer("--to-org", "Bluefin Security", "--date", days_ago(2))
        out = self.people("due")
        self.assertLess(out.index("Stalled intros"), out.index("i-1"))
        self.assertLess(out.index("Open intros"), out.index("i-2"))
        self.set_config(dashboard={"stallDays": 40})
        self.assertNotIn("Stalled", self.people("due"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people.IntroTest -v`
Expected: FAIL, `invalid choice: 'intro'`.

- [ ] **Step 3: Implement** (in `tools/people.py`, after `cmd_due`)

```python
def _intro(intros: dict, intro_id: str) -> dict:
    i = intros.get(intro_id)
    if i is None:
        raise PeopleError(f"no intro {intro_id!r} (see: people.py intro list)")
    if i["status"] == "closed":
        raise PeopleError(f"{intro_id} is closed ({i.get('result')}); closed intros don't change")
    return i


def _intro_ts(i: dict, day: str | None) -> str:
    ts = store.event_ts(day)
    if ts[:10] < i["updated"][:10]:
        raise PeopleError(f"--date {ts[:10]} is before {i['id']}'s last step ({i['updated'][:10]})")
    return ts


def cmd_intro_offer(args):
    with store.locked():
        st = load_state()
        frm = store.resolve(args.person, st.people, st.merges)
        if args.to:
            to = store.resolve(args.to, st.people, st.merges).slug
            if to == frm.slug:
                raise PeopleError("a person can't introduce themselves")
        else:
            org = args.to_org.strip()
            if not org or "\n" in org:
                raise PeopleError("--to-org needs an organization name")
            to = f"org:{org}"
        connector = Role("connector", args.for_) if args.for_ else None
        if connector:
            require_opportunities([connector], st.known)
        ts = store.event_ts(args.date)
        intro_id = store.next_intro_id(store.intro_states(st.events, st.merges))
        if connector and connector not in frm.roles:
            frm.roles.append(connector)
            store.save_person(frm)
            store.append_event({"type": "person", "person": frm.slug, "action": "role",
                                "detail": {"add": [str(connector)], "drop": []}})
            store.sync_contacts({args.for_}, st.known, st.people)
        store.append_event({"ts": ts, "type": "intro", "intro": intro_id, "status": "offered",
                            "from": frm.slug, "to": to, "for": args.for_ or "", "note": args.note})
    print(intro_id)


def cmd_intro_advance(args):
    with store.locked():
        st = load_state()
        i = _intro(store.intro_states(st.events, st.merges), args.id)
        order = store.INTRO_STATUSES
        if order.index(args.status) <= order.index(i["status"]):
            raise PeopleError(f"{args.id} is already {i['status']}; intros only move forward "
                              f"({' → '.join(order)})")
        ts = _intro_ts(i, args.date)
        store.append_event({"ts": ts, "type": "intro", "intro": args.id, "status": args.status})
    print(f"{args.id}: {args.status}")


def cmd_intro_close(args):
    with store.locked():
        st = load_state()
        i = _intro(store.intro_states(st.events, st.merges), args.id)
        if args.result == "led_to_opportunity":
            if not args.opportunity:
                raise PeopleError("led_to_opportunity needs --opportunity <company>/<role>")
            require_opportunities([Role("other", args.opportunity)], st.known)
        ts = _intro_ts(i, args.date)
        store.append_event({"ts": ts, "type": "intro", "intro": args.id, "status": "closed",
                            "result": args.result,
                            "opportunity": args.opportunity if args.result == "led_to_opportunity" else ""})
    print(f"{args.id}: closed ({args.result})")


def cmd_intro_list(args):
    with store.locked():
        st = load_state()
        intros = store.intro_states(st.events, st.merges)
    shown = [i for i in intros.values() if not args.open or i["status"] != "closed"]
    for i in sorted(shown, key=lambda i: int(i["id"][2:])):
        print(format_intro(i, st.people))
    if not shown:
        print("no intros")
```

Register in `build_parser()`, before `return parser`:

```python
    p_intro = sub.add_parser("intro")
    intro_sub = p_intro.add_subparsers(dest="intro_command", required=True)
    p_offer = intro_sub.add_parser("offer")
    p_offer.add_argument("person", help="who is making the intro")
    target = p_offer.add_mutually_exclusive_group(required=True)
    target.add_argument("--to", help="a person")
    target.add_argument("--to-org", dest="to_org", help="an organization, when there's no one person yet")
    p_offer.add_argument("--for", dest="for_", help="<company>/<role> opportunity it's for")
    p_offer.add_argument("--date")
    p_offer.add_argument("--note", default="")
    p_offer.set_defaults(func=cmd_intro_offer)
    for status in ("made", "met"):
        p_step = intro_sub.add_parser(status)
        p_step.add_argument("id")
        p_step.add_argument("--date")
        p_step.set_defaults(func=cmd_intro_advance, status=status)
    p_close = intro_sub.add_parser("close")
    p_close.add_argument("id")
    p_close.add_argument("--result", required=True, choices=store.INTRO_RESULTS)
    p_close.add_argument("--opportunity")
    p_close.add_argument("--date")
    p_close.set_defaults(func=cmd_intro_close)
    p_list = intro_sub.add_parser("list")
    p_list.add_argument("--open", action="store_true")
    p_list.set_defaults(func=cmd_intro_list)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people.py tools/test_people.py
git commit -m "people: intro lifecycle (offer, made, met, close, list) and stalled intros in due"
```

---

### Task 8: merge

**Files:**
- Modify: `tools/people_store.py` (append `merge_fields`)
- Modify: `tools/people.py` (add `cmd_merge`; register `merge`)
- Test: `tools/test_people.py` (append)

**Interfaces:**
- Produces:
  - `store.merge_fields(keep: Person, drop: Person) -> None`. It unions roles and aliases, fills keep's blank org/title/email, keeps relationship `yes` if either has it, and keeps keep's cadence unless that is `none`. The earlier `next_touch` wins. Drop's body is appended under `## Merged from <name>`, with a bullet for every org/title/email value that differed. Task 11 reuses it.
  - The `merge <keep> <drop>` command.

- [ ] **Step 1: Write the failing tests** (append to `tools/test_people.py`)

```python
class MergeTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.people("add", "Dana Reyes", "--org", "Northwind Motors", "--role", f"recruiter@{NW}",
                    "--next-touch", "2026-11-01")
        self.people("add", "D. Reyes", "--org", "Bluefin Security", "--email", "dana@example.com",
                    "--title", "Talent Partner", "--role", f"connector@{BF}", "--relationship", "yes",
                    "--cadence", "30d", "--next-touch", "2026-10-20")
        path = self.root / "people" / "d_reyes.md"
        path.write_text(path.read_text() + "Knows the Bluefin CTO.\n")
        self.people("touch", "d_reyes", "--channel", "email", "--date", days_ago(3))

    def test_merge(self):
        self.people("merge", "dana_reyes", "d_reyes")
        page = self.page("dana_reyes")
        # d_reyes's touch 3 days ago moved its next_touch to today + 27; the earlier date wins.
        earlier = min("2026-11-01", (TODAY + datetime.timedelta(days=27)).isoformat())
        for fragment in ("email: dana@example.com", "title: Talent Partner", "relationship: yes",
                         "cadence: 30d", f"next_touch: {earlier}", f"recruiter @ {NW}", f"connector @ {BF}",
                         "aliases: D. Reyes", "## Merged from D. Reyes", "- org: Bluefin Security",
                         "Knows the Bluefin CTO."):
            self.assertIn(fragment, page)
        self.assertFalse((self.root / "people" / "d_reyes.md").exists())
        self.assertIn("| Dana Reyes | connector | [[people/dana_reyes]] |", self.contacts(BF))
        self.assertEqual(self.events()[-1]["detail"], {"from": "d_reyes"})

    def test_history_and_lookups_follow_the_merge(self):
        self.people("merge", "dana_reyes", "d_reyes")
        self.assertIn(f"{days_ago(3)}  email", self.people("show", "d_reyes"))

    def test_dropped_slug_is_never_reused(self):
        self.people("merge", "dana_reyes", "d_reyes")
        self.assertIn("d_reyes_2", self.people("add", "D. Reyes", "--org", "Elsewhere"))

    def test_merge_with_self_fails(self):
        self.assertIn("same person", self.people_error("merge", "dana_reyes", "Dana Reyes"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people.MergeTest -v`
Expected: FAIL, `invalid choice: 'merge'`.

- [ ] **Step 3: Implement**

Append to `tools/people_store.py`:

```python
# --- merging ------------------------------------------------------------------------

def merge_fields(keep: Person, drop: Person) -> None:
    """Folds drop into keep (keep's slug survives). Nothing of drop's is lost:
    a differing org/title/email is listed under the merged section."""
    for role in drop.roles:
        if role not in keep.roles:
            keep.roles.append(role)
    taken = {keep.name.casefold(), *(a.casefold() for a in keep.aliases)}
    for alias in [drop.name, *drop.aliases]:
        if alias.casefold() not in taken:
            keep.aliases.append(alias)
            taken.add(alias.casefold())
    differing = []
    for key in ("org", "title", "email"):
        mine, theirs = getattr(keep, key), getattr(drop, key)
        if theirs and not mine:
            setattr(keep, key, theirs)
        elif theirs and theirs.casefold() != mine.casefold():
            differing.append(f"- {key}: {theirs}")
    if drop.relationship == "yes":
        keep.relationship = "yes"
    if keep.cadence == "none":
        keep.cadence = drop.cadence
    if drop.next_touch and (not keep.next_touch or drop.next_touch < keep.next_touch):
        keep.next_touch = drop.next_touch
    section = f"\n## Merged from {drop.name}\n" + ("\n" + "\n".join(differing) + "\n" if differing else "")
    keep.body = keep.body + ("" if keep.body.endswith("\n") else "\n") + section + drop.body
```

In `tools/people.py`, after `cmd_intro_list`:

```python
def cmd_merge(args):
    with store.locked():
        st = load_state()
        keep = store.resolve(args.keep, st.people, st.merges)
        drop = store.resolve(args.drop, st.people, st.merges)
        if keep.slug == drop.slug:
            raise PeopleError(f"{args.keep!r} and {args.drop!r} are the same person ({keep.slug})")
        affected = store.opportunities_of(keep) | store.opportunities_of(drop)
        store.merge_fields(keep, drop)
        store.save_person(keep)
        store.append_event({"type": "person", "person": keep.slug, "action": "merge",
                            "detail": {"from": drop.slug}})
        store.delete_person(drop.slug)
        del st.people[drop.slug]
        store.sync_contacts(affected, st.known, st.people)
    print(f"merged {drop.slug} into {store.describe(keep)}")
```

Register before `return parser`:

```python
    p_merge = sub.add_parser("merge")
    p_merge.add_argument("keep")
    p_merge.add_argument("drop")
    p_merge.set_defaults(func=cmd_merge)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people_store.py tools/people.py tools/test_people.py
git commit -m "people: merge"
```

---

### Task 9: export, and people.py in the no-bytecode check

**Files:**
- Modify: `tools/people.py` (add `export_data`, `cmd_export`; register `export`)
- Modify: `tools/test_no_bytecode.py` (run `people.py`)
- Test: `tools/test_people.py` (append)

**Interfaces:**
- Produces: `people.export_data() -> dict` and the `export --json` command. The export holds:
  - `schema: 1`, `roles` and `people`, where each person is `{slug, name, org, title, email, relationship, cadence, next_touch, roles: [{role, opportunity}], aliases}`.
  - `touches`, each `{ts, person, channel, note, inferred}` with `person` resolved through merges.
  - `intros`, each intro's state from `intro_states`.
  - `merges` and `warnings`.

- [ ] **Step 1: Write the failing tests**

Append to `tools/test_people.py`:

```python
import json  # noqa: E402  (put with the other imports at the top)


class ExportTest(WorkspaceTestCase):
    def test_export(self):
        self.people("add", "Dana Reyes", "--role", f"recruiter@{NW}", "--relationship", "yes")
        self.people("add", "Old Dana", "--email", "old@example.com")
        self.people("touch", "old_dana", "--channel", "call", "--date", days_ago(1))
        self.people("merge", "dana_reyes", "old_dana")
        self.people("intro", "offer", "dana_reyes", "--to-org", "Bluefin Security")
        with (self.root / "people_events.jsonl").open("a") as f:
            f.write("garbage\n")
        data = json.loads(self.people("export", "--json"))
        self.assertEqual(data["schema"], 1)
        [person] = data["people"]
        self.assertEqual(person["roles"], [{"role": "recruiter", "opportunity": NW}])
        self.assertEqual([t["person"] for t in data["touches"]], ["dana_reyes"])
        self.assertEqual(data["intros"][0]["status"], "offered")
        self.assertEqual(data["merges"], {"old_dana": "dana_reyes"})
        self.assertEqual(len(data["warnings"]), 1)
```

In `tools/test_no_bytecode.py`, add to `test_entry_scripts_leave_no_pycache`, after the `tracker.py` line:

```python
        self.run_tool("people.py", "find", "x")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people.ExportTest tools.test_no_bytecode -v`
Expected: `ExportTest` FAILs with `invalid choice: 'export'`, and `test_no_bytecode` PASSes. That pass confirms the store modules set `dont_write_bytecode` before their sibling imports.

- [ ] **Step 3: Implement** (in `tools/people.py`, after `cmd_merge`)

```python
def export_data() -> dict:
    """Everything a phase-2 dashboard view needs, as plain JSON."""
    with store.locked():
        events, warnings = store.read_events()
        people = store.load_people()
    merges = store.merged_into(events)
    intros = store.intro_states(events, merges)
    return {
        "schema": 1,
        "roles": store.ROLES,
        "people": [{"slug": p.slug, "name": p.name, "org": p.org, "title": p.title, "email": p.email,
                    "relationship": p.relationship, "cadence": p.cadence, "next_touch": p.next_touch,
                    "roles": [{"role": r.role, "opportunity": r.opportunity} for r in p.roles],
                    "aliases": p.aliases}
                   for p in sorted(people.values(), key=lambda p: p.slug)],
        "touches": [{"ts": e["ts"], "person": merges.get(e.get("person"), e.get("person")),
                     "channel": e.get("channel", ""), "note": e.get("note", ""),
                     "inferred": e.get("inferred", False)}
                    for e in events if e["type"] == "touch"],
        "intros": sorted(intros.values(), key=lambda i: int(i["id"][2:])),
        "merges": merges,
        "warnings": warnings,
    }


def cmd_export(args):
    json.dump(export_data(), sys.stdout, indent=2, ensure_ascii=False)
    print()
```

Register before `return parser`:

```python
    p_export = sub.add_parser("export")
    p_export.add_argument("--json", action="store_true", required=True)
    p_export.set_defaults(func=cmd_export)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people tools.test_no_bytecode -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people.py tools/test_people.py tools/test_no_bytecode.py
git commit -m "people: export --json"
```

---
### Task 10: import — parse the old files and write a draft

**Files:**
- Create: `tools/people_import.py`
- Modify: `tools/people.py` (register `import`)
- Test: `tools/test_people_import.py` (fixture built in `setUp` from invented data)

**Interfaces:**
- Consumes: `people_store` (Tasks 2–4), `tracker.split_row`/`unescape_cell`/`escape_cell`/`known_opportunities`.
- Produces (Task 11 relies on these):
  - Constants `DRAFT_NAME = "people-import-draft.md"`, `PEOPLE_COLUMNS`, `INTRO_COLUMNS`, `NETWORKING = "networking.md"`, `NETWORKING_POINTER`.
  - `@dataclass Candidate(name, source, file, opportunity="", org="", title="", email="", role_text="", notes="")`, where `source` is `"<file>:<line>"`.
  - `@dataclass Row(num, name, org, title, email, roles: list[str], relationship, cadence, next_touch, sources: list[str])` and `@dataclass IntroRow(frm, to, for_, result)`.
  - Parsing: `parse_contacts(text, rel, opp="", org="") -> (list[Candidate], list[str])`, `guess_role(c) -> str` (one of `ROLES` or `"?"`) and `collect(root, known) -> (candidates, unparsed, opportunity_slugs_with_files)`.
  - Proposals: `make_rows(cands, today) -> list[Row]`, `same_person_suggestions(rows) -> list[tuple[int, int, str]]` and `proposed_intros(rows, known) -> list[IntroRow]`.
  - Draft file: `render_draft(draft_id, rows, suggestions, intros, unparsed) -> str`, `parse_draft(text) -> (draft_id, [(line, cells)], [(line, a, b)], [(line, cells)])` and `write_draft(today=None) -> str` (the summary line).
  - The `people.py import --draft` command.

The heading-section shape (`## Name`, a paragraph, an `Email:` line or `- **Field:** value` bullets) is how most real `contacts.md` files are written, so the parser treats it as first-class alongside tables and `- **Name** — …` bullets.

- [ ] **Step 1: Write the failing tests** (`tools/test_people_import.py`)

```python
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import people_import as imp  # noqa: E402
import tracker  # noqa: E402
from people_testkit import BF, NW, WorkspaceTestCase  # noqa: E402

COBALT = "cobalt_labs/cto"
TODAY = datetime.date(2026, 10, 14)

NW_CONTACTS = """# Contacts — Northwind Motors / VP of Engineering

| Name | Title | Role in Process | Email | Notes |
| --- | --- | --- | --- | --- |
| Dana Reyes | Senior Recruiter | Recruiter running the search | dana.reyes@example.com | Reached out 2026-09-02 on LinkedIn. |
| Sam Ortiz | CTO | Hiring manager | Not on file | Wants a builder who ships. |
| Ann Bo | Director, Platform | Panel interviewer | — | Asked about on-call load. |
"""

BF_CONTACTS = """# Contacts — Bluefin Security / Head of Platform

## Lee Park

Former colleague who made the referral (2026-09-20). Connected me with the CTO.

Email: lee.park@example.com; personal: lee@example.org

## Hiring team

Still waiting to hear who is on the panel.

## Kim Vo
- **Title:** VP Engineering
- **Email:** kim.vo@example.com
- **Role:** Hiring manager
- Prefers morning calls.
"""

COBALT_CONTACTS = """# Contacts

- **Dana Reyes** — recruiter, dana.reyes@example.com, also ran the Cobalt search
- **Pat Lin**: board member

| Mutual connection | Degree |
| --- | --- |
| Someone Else | 2nd |
"""

GHOST_CONTACTS = """## Rae Chu — Founder
Email: rae@example.com
"""

NETWORKING = """# Networking

Some intro text.

## Lee Park — Bluefin Security - Staff Engineer
Coffee every quarter. Last coffee 2026-08-15.

## Dana Reyes — Acme Corp - Recruiter
A different Dana, met at a meetup.
"""


class ImportFixture(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.tracker("add", "Cobalt Labs", "CTO", "--stage", "Applied", "--source", "Other")
        self.tracker("close", "Cobalt Labs", "CTO", "--outcome", "Rejected", "--reason", "x")
        for opp, text in ((NW, NW_CONTACTS), (BF, BF_CONTACTS), (COBALT, COBALT_CONTACTS),
                          ("ghost_co/cto", GHOST_CONTACTS)):
            folder = self.root / "opportunity" / opp
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "contacts.md").write_text(text)
        (self.root / "networking.md").write_text(NETWORKING)

    def draft(self):
        summary = imp.write_draft(today=TODAY)
        return summary, (self.root / imp.DRAFT_NAME).read_text()

    def rows(self, text):
        _, rows, _, _ = imp.parse_draft(text)
        return {cells["Name"] + "|" + cells["Org"]: cells for _, cells in rows}


class ParseTest(unittest.TestCase):
    def test_table_rows(self):
        cands, unparsed = imp.parse_contacts(NW_CONTACTS, "nw.md", NW, "Northwind Motors")
        self.assertEqual(unparsed, [])
        dana, sam, ann = cands
        self.assertEqual((dana.name, dana.title, dana.email, dana.org, dana.source),
                         ("Dana Reyes", "Senior Recruiter", "dana.reyes@example.com", "Northwind Motors", "nw.md:5"))
        self.assertIn("Role in Process: Recruiter running the search", dana.notes)
        self.assertIn("Reached out 2026-09-02 on LinkedIn.", dana.notes)
        self.assertEqual(sam.email, "")
        self.assertEqual([imp.guess_role(c) for c in cands], ["recruiter", "hiring", "panelist"])

    def test_heading_sections(self):
        cands, unparsed = imp.parse_contacts(BF_CONTACTS, "bf.md", BF, "Bluefin Security")
        lee, kim = cands
        self.assertEqual(lee.email, "lee.park@example.com")
        self.assertIn("personal: lee@example.org", lee.notes)
        self.assertIn("made the referral", lee.notes)
        self.assertEqual(imp.guess_role(lee), "connector")
        self.assertEqual((kim.title, kim.email, imp.guess_role(kim)), ("VP Engineering", "kim.vo@example.com", "hiring"))
        self.assertIn("Prefers morning calls.", kim.notes)
        self.assertEqual(unparsed, ["bf.md:11: Still waiting to hear who is on the panel."])

    def test_person_bullets_and_non_person_tables(self):
        cands, unparsed = imp.parse_contacts(COBALT_CONTACTS, "c.md", COBALT, "Cobalt Labs")
        self.assertEqual([(c.name, c.email) for c in cands],
                         [("Dana Reyes", "dana.reyes@example.com"), ("Pat Lin", "")])
        self.assertEqual(imp.guess_role(cands[1]), "?")
        self.assertEqual(unparsed, ["c.md:6: | Mutual connection | Degree |", "c.md:8: | Someone Else | 2nd |"])

    def test_role_words_match_whole_words_only(self):
        director = imp.Candidate(name="A", source="x:1", file="x", title="Director, Platform")
        self.assertEqual(imp.guess_role(director), "?")


class DraftTest(ImportFixture):
    def test_summary(self):
        summary, _ = self.draft()
        self.assertIn("8 people from 5 files", summary)
        self.assertIn("1 need a role", summary)
        self.assertIn("4 unparsed lines", summary)

    def test_rows(self):
        _, text = self.draft()
        rows = self.rows(text)
        # Files are read in path order (bluefin, cobalt, ghost, northwind), so Dana's first
        # source is Cobalt's; her org is the most common one, ties going to the first seen.
        dana = rows["Dana Reyes|Cobalt Labs"]
        self.assertEqual(dana["#"], "1")  # overdue first: 2026-09-02 + 21d
        self.assertEqual(dana["Roles"], f"recruiter @ {COBALT}, recruiter @ {NW}")
        self.assertEqual((dana["Relationship"], dana["Cadence"], dana["Next touch"]), ("yes", "21d", "2026-09-23"))
        lee = rows["Lee Park|Bluefin Security"]
        self.assertEqual((lee["Roles"], lee["Cadence"], lee["Next touch"]), (f"connector @ {BF}, peer", "30d", "2026-10-20"))
        self.assertEqual(lee["Email"], "lee.park@example.com")
        self.assertEqual(rows["Pat Lin|Cobalt Labs"]["Roles"], f"? @ {COBALT}")
        self.assertEqual(rows["Rae Chu|"]["Roles"], "hiring")
        self.assertEqual(rows["Sam Ortiz|Northwind Motors"]["Relationship"], "no")
        self.assertEqual(rows["Dana Reyes|Acme Corp"]["Roles"], "recruiter")

    def test_suggestions_intros_unparsed(self):
        _, text = self.draft()
        rows = self.rows(text)
        a, b = sorted(int(rows[k]["#"]) for k in ("Dana Reyes|Cobalt Labs", "Dana Reyes|Acme Corp"))
        self.assertIn(f"- [ ] {a} = {b} — same name", text)
        _, _, _, intros = imp.parse_draft(text)
        [(_, intro)] = intros
        self.assertEqual((intro["To"], intro["For"], intro["Result"]),
                         ("org:Bluefin Security", BF, "led_to_opportunity"))
        self.assertIn("- networking.md:3: Some intro text.", text)

    def test_draft_round_trips(self):
        rows = [imp.Row(num=1, name="A | B", roles=["peer"], sources=["x.md:1"])]
        text = imp.render_draft("d-20261014T090000", rows, [], [], [])
        draft_id, parsed, merges, intros = imp.parse_draft(text)
        self.assertEqual((draft_id, parsed[0][1]["Name"], merges, intros), ("d-20261014T090000", "A | B", [], []))

    def test_generated_contacts_are_skipped(self):
        self.people("add", "New Person", "--role", f"recruiter@{NW}")
        summary, text = self.draft()
        self.assertNotIn("Sam Ortiz", text)

    def test_cli(self):
        self.assertIn("people-import-draft.md", self.people("import", "--draft"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people_import -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'people_import'`.

- [ ] **Step 3: Implement** (`tools/people_import.py`)

```python
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
```

In `tools/people.py`, add `import people_import  # noqa: E402` next to the other sibling imports, then after `cmd_export`:

```python
def cmd_import(args):
    if args.draft:
        print(people_import.write_draft())
    else:
        print(people_import.apply(Path(args.apply)))
```

Register before `return parser`:

```python
    p_import = sub.add_parser("import", help="one-time import of contacts.md files and networking.md")
    mode = p_import.add_mutually_exclusive_group(required=True)
    mode.add_argument("--draft", action="store_true")
    mode.add_argument("--apply", metavar="DRAFT")
    p_import.set_defaults(func=cmd_import)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people_import -v`
Expected: all PASS. (`--apply` arrives in Task 11; `test_cli` uses only `--draft`.)

- [ ] **Step 5: Commit**

```bash
git add tools/people_import.py tools/people.py tools/test_people_import.py
git commit -m "people import: parse contacts.md and networking.md into a reviewable draft"
```

---

### Task 11: import — apply the draft

**Files:**
- Modify: `tools/people_import.py` (append `apply` and helpers)
- Test: `tools/test_people_import.py` (append)

**Interfaces:**
- Consumes: everything from Task 10; `store.merge_fields` (Task 8); `store.sync_contacts`, `store.next_intro_id`, `store.intro_states` and `store.used_slugs`/`allocate_slug`.
- Produces `people_import.apply(draft_path: Path) -> str` (a summary line). It validates the whole draft first, and nothing is written on any error. It's a no-op if that draft id was already applied.

- [ ] **Step 1: Write the failing tests** (append to `tools/test_people_import.py`, above the `__main__` guard)

```python
import json  # noqa: E402  (put with the other imports at the top)


class ApplyTest(ImportFixture):
    def edited_draft(self, merge_danas=False):
        _, text = self.draft()
        text = text.replace("| ? @ ", "| other @ ")
        if merge_danas:
            text = text.replace("- [ ] ", "- [x] ", 1)
        (self.root / imp.DRAFT_NAME).write_text(text)
        return text

    def apply(self):
        return self.people("import", "--apply", imp.DRAFT_NAME)

    def test_unresolved_roles_reject_everything(self):
        self.draft()
        err = self.people_error("import", "--apply", imp.DRAFT_NAME)
        self.assertIn("(Pat Lin): replace ?", err)
        self.assertFalse((self.root / "people").exists())
        self.assertEqual(self.events(), [])
        self.assertEqual(self.contacts(NW), NW_CONTACTS)

    def test_apply_creates_pages_with_notes_by_source(self):
        self.edited_draft()
        self.assertIn("8 people", self.apply())
        lee = self.page("lee_park")
        self.assertIn(f"roles: connector @ {BF}, peer", lee)
        self.assertIn(f"### From {BF}", lee)
        self.assertIn("### From networking.md", lee)
        self.assertIn("Coffee every quarter.", lee)
        self.assertIn("roles: hiring\n", self.page("rae_chu"))
        adds = [e for e in self.events() if e["type"] == "person"]
        self.assertEqual(len(adds), 8)
        self.assertTrue(all(e["inferred"] and e["detail"]["import"].startswith("d-") for e in adds))

    def test_contacts_regenerated_with_originals_kept(self):
        self.edited_draft()
        self.apply()
        self.assertIn("| Dana Reyes | recruiter | [[people/dana_reyes]] |", self.contacts(NW))
        self.assertEqual((self.root / "opportunity" / NW / "contacts.hand-written.md").read_text(), NW_CONTACTS)
        self.assertEqual(self.contacts("ghost_co/cto"), GHOST_CONTACTS)  # not in the tracker: left alone
        self.assertIn("people/", (self.root / "networking.md").read_text())
        self.assertEqual((self.root / "networking.hand-written.md").read_text(), NETWORKING)

    def test_everyone_named_before_is_named_after(self):
        self.edited_draft()
        self.apply()
        for name in ("Dana Reyes", "Sam Ortiz", "Ann Bo"):
            self.assertIn(f"| {name} |", self.contacts(NW))
        for name in ("Lee Park", "Kim Vo"):
            self.assertIn(f"| {name} |", self.contacts(BF))

    def test_notes_text_is_not_lost(self):
        self.edited_draft()
        self.apply()
        source = sum(len(line.split("|")[5].split()) for line in NW_CONTACTS.splitlines()[4:])
        imported = sum(len(p.read_text().split()) for p in (self.root / "people").glob("*.md"))
        self.assertGreaterEqual(imported, source)
        for line in NW_CONTACTS.splitlines()[4:]:
            note = line.split("|")[5].strip()
            self.assertTrue(any(note in p.read_text() for p in (self.root / "people").glob("*.md")), note)

    def test_inferred_intro_recorded(self):
        self.edited_draft()
        self.apply()
        [intro] = [e for e in self.events() if e["type"] == "intro"]
        self.assertEqual((intro["from"], intro["to"], intro["status"], intro["result"], intro["opportunity"],
                          intro["inferred"]),
                         ("lee_park", "org:Bluefin Security", "closed", "led_to_opportunity", BF, True))

    def test_ticked_merge(self):
        self.edited_draft(merge_danas=True)
        self.assertIn("7 people", self.apply())
        page = self.page("dana_reyes")
        self.assertIn("recruiter @ northwind_motors/vp_of_engineering", page)
        self.assertIn("A different Dana, met at a meetup.", page)
        self.assertFalse((self.root / "people" / "dana_reyes_2.md").exists())

    def test_reapply_is_a_no_op(self):
        self.edited_draft()
        self.apply()
        before = len(self.events())
        self.assertIn("already applied", self.apply())
        self.assertEqual(len(self.events()), before)

    def test_existing_page_duplicate_is_refused(self):
        self.edited_draft()
        self.people("add", "Sam Ortiz", "--org", "Northwind Motors")
        self.assertIn("(Sam Ortiz) duplicates existing page sam_ortiz", self.people_error("import", "--apply", imp.DRAFT_NAME))

    def test_stale_draft_is_refused(self):
        self.edited_draft()
        (self.root / "opportunity" / COBALT / "contacts.md").unlink()
        self.assertIn("run import --draft again", self.people_error("import", "--apply", imp.DRAFT_NAME))

    def test_export_after_import(self):
        self.edited_draft()
        self.apply()
        data = json.loads(self.people("export", "--json"))
        self.assertEqual(len(data["people"]), 8)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_people_import.ApplyTest -v`
Expected: ERROR, `AttributeError: module 'people_import' has no attribute 'apply'`.

- [ ] **Step 3: Implement** (append to `tools/people_import.py`)

```python
def _row_person(num, cells, known, by_source, errors):
    where = f"row {num} ({cells['Name'] or 'no name'})"
    p = Person(slug="", name=cells["Name"], org=cells["Org"], title=cells["Title"], email=cells["Email"],
               relationship=cells["Relationship"] or "no", cadence=cells["Cadence"] or "none",
               next_touch=cells["Next touch"])
    for item in store.split_list(cells["Roles"]):
        if item.partition("@")[0].strip() == "?":
            errors.append(f"{where}: replace ? in {item!r} with one of {', '.join(store.ROLES)}")
            continue
        try:
            role = store.parse_role(item)
        except PeopleError as e:
            errors.append(f"{where}: {e}")
            continue
        if role.opportunity and role.opportunity not in known:
            errors.append(f"{where}: {role.opportunity!r} is not an opportunity in the tracker")
        elif role not in p.roles:
            p.roles.append(role)
    sources = [s.strip() for s in cells["Sources"].split(";") if s.strip()]
    for source in sources:
        if source not in by_source:
            errors.append(f"{where}: source {source} doesn't match the files any more — run import --draft again")
    try:
        store.check_person(p)
    except PeopleError as e:
        errors.append(f"{where}: {e}")
    return p, sources


def _note_section(c: Candidate) -> str:
    label = c.opportunity or c.file
    notes = c.notes.strip()
    return f"\n### From {label}\n" + (f"\n{notes}\n" if notes else "")


def _retire_networking(root: Path) -> bool:
    net = root / NETWORKING
    if not net.exists():
        return False
    text = net.read_text(encoding="utf-8")
    if NETWORKING_POINTER in text:
        return False
    backup = root / NETWORKING_BACKUP
    prior = backup.read_text(encoding="utf-8") if backup.exists() else ""
    backup.write_text(prior + ("\n\n" if prior else "") + text, encoding="utf-8")
    net.write_text(f"# Networking\n\n{NETWORKING_POINTER}\n\nEveryone who was here now has a page in "
                   f"`people/` (`people.py due`, `people.py find`). The original text is in "
                   f"`{NETWORKING_BACKUP}`.\n", encoding="utf-8")
    return True


def apply(draft_path: Path) -> str:
    try:
        text = draft_path.read_text(encoding="utf-8")
    except OSError as e:
        raise PeopleError(f"can't read {draft_path}: {e}") from None
    draft_id, rows, merges, intro_rows = parse_draft(text)
    root = store.root()
    with store.locked():
        events, _ = store.read_events()
        if any(e["type"] == "person" and (e.get("detail") or {}).get("import") == draft_id for e in events):
            return f"draft {draft_id} was already applied; nothing to do"
        people = store.load_people()
        known = tracker.known_opportunities()
        cands, _, opps = collect(root, known)
        by_source = {c.source: c for c in cands}
        errors: list[str] = []

        planned, sources = {}, {}
        for n, cells in rows:
            num = int(cells["#"]) if cells["#"].isdigit() else None
            if num is None or num in planned:
                errors.append(f"{DRAFT_NAME}:{n}: '#' must be a unique row number")
                continue
            planned[num], sources[num] = _row_person(num, cells, known, by_source, errors)

        parent = {num: num for num in planned}

        def find(num):
            while parent[num] != num:
                num = parent[num]
            return num

        for n, a, b in merges:
            if a not in planned or b not in planned:
                errors.append(f"{DRAFT_NAME}:{n}: merge {a} = {b} names a row that isn't in People")
                continue
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        final = {}
        for num in sorted(planned):
            keep_num = find(num)
            if keep_num == num:
                final[num] = planned[num]
            else:
                store.merge_fields(final[keep_num], planned[num])
                sources[keep_num] += sources[num]

        intro_plan = []
        for n, cells in intro_rows:
            ref = cells["From"].lstrip("#")
            to = cells["To"].strip()
            for_, result = cells["For"].strip(), cells["Result"].strip()
            if not ref.isdigit() or int(ref) not in planned:
                errors.append(f"{DRAFT_NAME}:{n}: From must be a row number like #3")
                continue
            if to.startswith("#") and to[1:].isdigit() and int(to[1:]) in planned:
                to = ("row", find(int(to[1:])))
            elif not (to.startswith("org:") and to[4:].strip()):
                errors.append(f"{DRAFT_NAME}:{n}: To must be org:<Org> or a row number like #3")
                continue
            if for_ and for_ not in known:
                errors.append(f"{DRAFT_NAME}:{n}: {for_!r} is not an opportunity in the tracker")
            if result and result not in store.INTRO_RESULTS:
                errors.append(f"{DRAFT_NAME}:{n}: Result must be one of {', '.join(store.INTRO_RESULTS)} or empty")
            if result == "led_to_opportunity" and not for_:
                errors.append(f"{DRAFT_NAME}:{n}: led_to_opportunity needs For")
            intro_plan.append((find(int(ref)), to, for_, result))

        seen_email: dict[str, int] = {}
        for num, p in final.items():
            p.body = ""
            dup = next((q for q in people.values()
                        if (p.email and q.email.casefold() == p.email.casefold())
                        or (q.name.casefold() == p.name.casefold() and q.org.casefold() == p.org.casefold())), None)
            if dup:
                errors.append(f"row {num} ({p.name}) duplicates existing page {dup.slug}; delete the row "
                              "(and use people.py merge later if needed)")
            if p.email:
                other = seen_email.setdefault(p.email.casefold(), num)
                if other != num:
                    errors.append(f"rows {other} and {num} share {p.email}; tick their Same person? box or fix one")
        if errors:
            raise PeopleError("import rejected, nothing written:\n  " + "\n  ".join(errors))

        used = store.used_slugs(people, events)
        slug_of = {}
        for num in sorted(final):
            p = final[num]
            p.slug = store.allocate_slug(p.name, used)
            used.add(p.slug)
            p.body = "\n## Notes\n" + "".join(_note_section(by_source[s]) for s in sources[num])
            store.save_person(p)
            people[p.slug] = p
            slug_of[num] = p.slug
            store.append_event({"type": "person", "person": p.slug, "action": "add", "inferred": True,
                                "detail": {"import": draft_id, "sources": sources[num]}})
        intros = store.intro_states(events, store.merged_into(events))
        for frm, to, for_, result in intro_plan:
            intro_id = store.next_intro_id(intros)
            intros[intro_id] = {}
            store.append_event({"type": "intro", "intro": intro_id, "status": "closed" if result else "made",
                                "from": slug_of[frm], "to": to if isinstance(to, str) else slug_of[to[1]],
                                "for": for_, "result": result,
                                "opportunity": for_ if result == "led_to_opportunity" else "",
                                "note": "inferred by import", "inferred": True})
        changed = store.sync_contacts(set(opps) | store.linked_opportunities(people), known, people)
        retired = _retire_networking(root)
    return (f"applied {draft_id}: {len(final)} people, {len(intro_plan)} intros, "
            f"{len(changed)} contacts.md regenerated" + ("; networking.md moved to people/" if retired else ""))
```

Note on `p.body = ""` in the duplicate loop: `merge_fields` appended the merged rows' default bodies. The body is rebuilt from sources at write time, so clearing it there is safe.

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tools.test_people_import -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/people_import.py tools/test_people_import.py
git commit -m "people import: apply a reviewed draft (pages, intros, contacts.md, networking.md)"
```

---

### Task 12: skills, persona, README and version

**Files:**
- Modify: `guidance/persona.md` (Data Files; replace `## Contacts` with `## People`)
- Modify: `skills/morning-scan/SKILL.md` (Tier 1 sender list and touches, a Relationships step, the Tier 4 wording, Summary Format)
- Modify: `skills/interview-review/SKILL.md`, `commands/summarize-call.md` (touch attendees, add people, record intros)
- Modify: `skills/interview-prep/SKILL.md` (read people pages)
- Modify: `skills/company-research/SKILL.md` (add people found)
- Modify: `skills/score-opportunity/SKILL.md` (close the intro that led here)
- Create: `skills/relationships/SKILL.md`
- Modify: `tools/test_skills.py`, `README.md`, `.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: the CLI from Tasks 5–11, exactly as registered.

- [ ] **Step 1: Write the failing skill checks** (append to `tools/test_skills.py`, above the `__main__` guard)

```python
PEOPLE = '${CLAUDE_PLUGIN_ROOT}/tools/people.py"'
PLUGIN = SKILLS.parent


class PeopleGuidanceTest(unittest.TestCase):
    def text(self, rel):
        return (PLUGIN / rel).read_text()

    def test_persona_points_contacts_at_people_tool(self):
        text = self.text("guidance/persona.md")
        self.assertIn(f"{PEOPLE} add", text)
        self.assertIn("Never hand-edit an opportunity's `contacts.md`", text)
        self.assertNotIn("add them to its\n`contacts.md`", text)

    def test_no_skill_reads_emails_from_contacts_md(self):
        for path in list(SKILLS.rglob("*.md")) + list((PLUGIN / "commands").rglob("*.md")):
            self.assertNotIn("contacts.md` for known contact emails", path.read_text(), path)

    def test_morning_scan_uses_people(self):
        text = self.text("skills/morning-scan/SKILL.md")
        self.assertIn(f"{PEOPLE} emails --active", text)
        self.assertIn(f"{PEOPLE} due --within 3d", text)
        self.assertIn(f"{PEOPLE} touch", text)

    def test_call_skills_touch_attendees(self):
        for rel in ("skills/interview-review/SKILL.md", "commands/summarize-call.md"):
            self.assertIn(f"{PEOPLE} touch", self.text(rel), rel)

    def test_interview_prep_reads_people_pages(self):
        self.assertIn(f"{PEOPLE} show", self.text("skills/interview-prep/SKILL.md"))

    def test_relationships_skill(self):
        text = self.text("skills/relationships/SKILL.md")
        self.assertIn("name: relationships", text)
        self.assertIn(f"{PEOPLE} due", text)
        self.assertIn(f"{PEOPLE} import --draft", text)
        self.assertIn("Never send", text)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tools.test_skills.PeopleGuidanceTest -v`
Expected: FAIL on the persona, morning-scan, call skills, interview-prep and relationships checks.

- [ ] **Step 3: Update `guidance/persona.md`**

In `## Data Files`, add after the `tracker_events.jsonl` bullet:

```markdown
- `people/<slug>.md` — one page per person (recruiters, connectors,
  hiring managers, panelists, peers): a field block managed only by
  `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py"`, then free-form notes
  below it. Files starting with `_` are not person pages.
- `people_events.jsonl` — every touch, intro and people change, written by
  `people.py`. Never edit it by hand.
```

Replace the whole `## Contacts` section with:

```markdown
## People

Everyone in the search has one page in `people/`, and each opportunity's
`contacts.md` is generated from those pages. Never hand-edit an
opportunity's `contacts.md`, and never edit a page's field block (the
lines between the `---` markers) by hand. Use `people.py`. Notes go below
the field block, and you may edit them directly.

Whenever you learn of a contact for an opportunity, don't wait to be asked.
This applies during any skill session. Check `people.py find "<name or
email>"` first, then either add them or link the page they already have:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" add "<Name>" --org "<Org>" --title "<Title>" --email "<email>" --role "<role>@<opportunity slug>"
    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" role "<person>" --add "<role>@<opportunity slug>"

- **Roles:** recruiter, hiring, connector, peer, panelist, other.
- **Opportunity slug:** the last two parts of the folder path that
  `opportunity-path` prints (e.g. `northwind_motors/vp_of_engineering`).
- **Relationship:** `--relationship yes --cadence <N>d` marks someone to
  keep in touch with. Ask the user before setting it.

Log every conversation:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" touch "<person>" --channel call|email|meeting|message|other --date <YYYY-MM-DD> --note "<what>"

Record intros as they happen:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" intro offer "<who offered>" --to "<person>" | --to-org "<Org>" [--for <opportunity slug>]
    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" intro made|met <id>
    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" intro close <id> --result led_to_opportunity --opportunity <slug> | --result led_to_intros | --result dead_end

`people.py due` lists who to get back to and which intros have stalled.
Never send anything to these people. Draft only.
```

- [ ] **Step 4: Update `skills/morning-scan/SKILL.md`**

Replace the first paragraph of `## Tier 1 — Pipeline Emails` (from "Build the contact list dynamically…" through "…read that folder's `contacts.md` for known contact emails.") with:

```markdown
Build the sender list from the people tool rather than a fixed list:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" emails --active

It prints everyone linked to an active opportunity plus everyone with
`relationship: yes`, one email per line.
```

After the numbered three-tier method in Tier 1 (after the `--after YYYY-MM-DD` line), add:

```markdown
**Log each genuinely new message as a touch**, using the sender's email, the message date and its subject:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" touch "<sender email>" --channel email --date <YYYY-MM-DD> --note "<subject>"

Re-running is safe: an identical touch is logged once.
```

Before `## Summary Format`, add a section:

```markdown
## Tier 5 — Relationships

After Tiers 1–3 (it needs their touches logged), run:

    python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" due --within 3d

It lists relationships due for a touch (overdue first), stalled intros and
other open intros. Don't draft outreach unless the user asks. Never send.
```

In step 4 of the numbered list at the top, change "Run Tiers 1-3 in parallel, **then** Tier 4" to "Run Tiers 1-3 in parallel, **then** Tier 4, **then** Tier 5".

In Tier 4's "Report, do not act", change "**Do not create tracker rows, write `contacts.md`, or change any status" to "**Do not create tracker rows, add people, or change any status". Then change "including the standing job-search-os instruction to record contacts" to "including the standing job-search-os instruction to record people (`people.py add`)".

In `## Summary Format`, add after **Calendar**:

```markdown
**Relationships** — the `due` output: who to get back to (with the last touch), stalled intros, open intros. One line each. If nothing is due, say so in one line.
```

- [ ] **Step 5: Update the call skills, interview-prep, company-research and score-opportunity**

`skills/interview-review/SKILL.md`, under `## Output`, add step 4:

```markdown
4. Record the people on the call:
   - For each attendee, check `people.py find "<name>"`. Add anyone new with their role on this opportunity:
     `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" add "<Name>" --org "<Org>" --title "<Title>" --role "<role>@<opportunity slug>"`
   - Log the call for every attendee:
     `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" touch "<person>" --channel call --date <call date> --note "<stage>"` (`--channel meeting` if in person).
   - If someone offered an intro, record it with `people.py intro offer` (see the persona's People section).
```

`commands/summarize-call.md`: insert the same block as a new step between step 4 (**Update the tracker**) and step 5 (**Ask the user**), and renumber "Ask the user" to 6.

`skills/interview-prep/SKILL.md`: in `## Session Start`, after the sentence listing what to read, add:

```markdown
Then, for each person in `contacts.md`, run
`python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" show "<slug>"` and read their
page `people/<slug>.md`. The page holds their notes from every opportunity
they've been part of, not just this one.
```

In `## Briefing Contents`, change item 1's "from `contacts.md`, plus what's known about that person's role and priorities from `notes.md`" to "from `contacts.md` and each person's page, plus what's known about their role and priorities from `notes.md`".

`skills/company-research/SKILL.md`, at the end of `## Output`:

```markdown
People you identify (likely hiring manager, leaders the role works with) get a page and a role on this opportunity, if they don't have one already (`people.py find` first):
`python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" add "<Name>" --org "<Company>" --title "<Title>" --role "other@<opportunity slug>"`
(`hiring@…` for the hiring manager). Leave `relationship` at its default (`no`).
```

`skills/score-opportunity/SKILL.md`, after step 6 of "New Opportunity":

```markdown
6a. If the opportunity came through a person (a referral or warm intro),
    close the intro that led here. Run
    `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" intro list --open`.
    If it shows the matching intro, run
    `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" intro close <id> --result led_to_opportunity --opportunity <opportunity slug>`.
    Otherwise record the intro first with
    `python3 "${CLAUDE_PLUGIN_ROOT}/tools/people.py" intro offer "<person>" --to-org "<Company>" --for <opportunity slug>`,
    then close the id it prints the same way.
```

- [ ] **Step 6: Create `skills/relationships/SKILL.md`**

```markdown
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
```

- [ ] **Step 7: Update `README.md` and the manifest**

- `README.md`:
  - Change "Fifteen skills" to "Sixteen skills" (two places: the intro to the table, and "the fifteen skills above" in Layout).
  - Add a table row after `backfill-history`: `| relationships | Who to get back to, intros in flight, and everything known about a person — one page per person, follow-up cadences, intros tracked from offer to result |`.
  - In Layout, under `tools/`, add:
    ```
      people.py                    people, follow-ups and intros (sole writer of people/)
      people_store.py              person pages, event log, generated contacts.md
      people_import.py             one-time import of old contacts.md / networking.md
    ```
- `.claude-plugin/plugin.json`: set `"version": "0.3.0"`. In `description`, change "a pipeline tracker, and a local read-only dashboard" to "a pipeline tracker, a relationships tracker (people, follow-ups, intros), and a local read-only dashboard".

- [ ] **Step 8: Run everything**

Run: `tools/run_tests.sh && claude plugin validate .`
Expected: all Python and Node tests PASS, every static check passes (no exit 1), and the manifest validates.

- [ ] **Step 9: Commit**

```bash
git add guidance/persona.md skills commands tools/test_skills.py README.md .claude-plugin/plugin.json
git commit -m "Skills and persona use people.py; new relationships skill; v0.3.0"
```

---

## After the plan (not tasks)

- **Before the PR:** run the import on a copy of the author's workspace (spec, Rollout step 2). That's a dry run; do it on the real workspace only with the user, as one revertible commit there.
- **Review:** open the PR and run an independent review before merging, then tag v0.3.0.
