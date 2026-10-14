import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import people_store as store  # noqa: E402
from people_testkit import BF, NW, WorkspaceTestCase  # noqa: E402
import concurrent.futures  # noqa: E402
import datetime  # noqa: E402
import subprocess  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
