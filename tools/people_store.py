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
