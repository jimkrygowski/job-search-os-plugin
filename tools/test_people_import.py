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
