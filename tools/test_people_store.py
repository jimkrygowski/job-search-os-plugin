import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import people_store as store  # noqa: E402
from people_store import Person, PeopleError, Role  # noqa: E402
from people_testkit import BF, NW, WorkspaceTestCase  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
