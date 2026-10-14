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
