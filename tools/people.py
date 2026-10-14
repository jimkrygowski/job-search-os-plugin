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

    p_touch = sub.add_parser("touch")
    p_touch.add_argument("person")
    p_touch.add_argument("--channel", required=True, choices=store.CHANNELS)
    p_touch.add_argument("--date")
    p_touch.add_argument("--note", default="")
    p_touch.set_defaults(func=cmd_touch)

    p_due = sub.add_parser("due")
    p_due.add_argument("--within", default="0d")
    p_due.set_defaults(func=cmd_due)

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

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("keep")
    p_merge.add_argument("drop")
    p_merge.set_defaults(func=cmd_merge)

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
