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
        result = self._run("people.py", "emails")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--active", result.stderr)

    def test_sync_contacts_rebuilds_every_linked_opportunity(self):
        (self.root / "opportunity" / NW / "contacts.md").unlink()
        self.assertIn(NW, self.people("sync-contacts"))
        self.assertIn("| Kim Vo | panelist |", self.contacts(NW))

    def test_malformed_page_fails_every_command_naming_the_line(self):
        (self.root / "people" / "dana_reyes.md").write_text("---\nname: Dana\nbogus\n---\n")
        self.assertIn("people/dana_reyes.md:3", self.people_error("show", "lee_park"))


if __name__ == "__main__":
    unittest.main()
