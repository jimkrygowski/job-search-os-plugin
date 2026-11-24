import unittest
from pathlib import Path

SKILLS = Path(__file__).parent.parent / "skills"
PERSONA_REF = "${CLAUDE_PLUGIN_ROOT}/guidance/persona.md"


class PersonaLoadedWhenWorkspaceCreatedMidSessionTest(unittest.TestCase):
    """The SessionStart hook can't inject the persona into the session that
    creates the workspace, so the skills that create one must load it."""

    def test_bootstrap_loads_persona_after_init(self):
        text = (SKILLS / "bootstrap" / "SKILL.md").read_text()
        self.assertIn(PERSONA_REF, text)
        self.assertLess(text.index("workspace.py\" init"), text.index(PERSONA_REF))

    def test_migrate_loads_persona_for_same_directory_destination(self):
        text = (SKILLS / "migrate" / "SKILL.md").read_text()
        self.assertIn(PERSONA_REF, text)


TRACKER = '${CLAUDE_PLUGIN_ROOT}/tools/tracker.py"'


def _invocations(command):
    """Every tracker.py <command> invocation across skills and guidance,
    joined across backslash line continuations."""
    found = []
    for path in list(SKILLS.rglob("*.md")) + list((SKILLS.parent / "guidance").rglob("*.md")):
        text = path.read_text().replace("\\\n", " ")
        for line in text.splitlines():
            if f'{TRACKER} {command} ' in line:
                found.append((path.parent.name, line))
    return found


class TrackerInvocationsTest(unittest.TestCase):
    def test_every_add_passes_source(self):
        calls = _invocations("add")
        self.assertTrue(calls)
        for skill, line in calls:
            self.assertIn("--source", line, skill)

    def test_every_close_passes_outcome(self):
        calls = _invocations("close")
        self.assertTrue(calls)
        for skill, line in calls:
            self.assertIn("--outcome", line, skill)

    def test_backfill_history_skill_uses_backfill(self):
        text = (SKILLS / "backfill-history" / "SKILL.md").read_text()
        self.assertIn(f"{TRACKER} backfill --events-file", text)

    def test_interview_review_lists_canonical_stages(self):
        text = (SKILLS / "interview-review" / "SKILL.md").read_text()
        self.assertIn("Identified, Applied, Recruiter Screen, Hiring Manager, Interview Loop, Offer", text)


class DashboardSkillTest(unittest.TestCase):
    def setUp(self):
        self.text = (SKILLS / "dashboard" / "SKILL.md").read_text()

    def test_launches_server_from_plugin_root(self):
        self.assertIn('node "${CLAUDE_PLUGIN_ROOT}/dashboard/server/main.ts" --workspace', self.text)

    def test_checks_workspace_and_node_version_first(self):
        self.assertIn('${CLAUDE_PLUGIN_ROOT}/tools/workspace.py" root', self.text)
        self.assertIn("22.18", self.text)
        self.assertLess(self.text.index("22.18"), self.text.index("dashboard/server/main.ts"))


class StalledRuleTest(unittest.TestCase):
    def test_morning_scan_uses_the_configured_stall_threshold(self):
        text = (SKILLS / "morning-scan" / "SKILL.md").read_text()
        self.assertIn("stallDays", text)
        self.assertNotIn("21 or more days", text)


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


class InterviewFileSkillsTest(unittest.TestCase):
    def text(self, name):
        """Whitespace collapsed, so phrase checks don't depend on line wraps."""
        return " ".join((SKILLS / name / "SKILL.md").read_text().split())

    def test_both_skills_call_interview_file(self):
        callers = {skill for skill, _ in _invocations("interview-file")}
        self.assertTrue({"interview-prep", "interview-review"} <= callers, callers)

    def test_both_read_talking_points(self):
        for name in ("interview-prep", "interview-review"):
            self.assertIn("career/talking_points.md", self.text(name), name)

    def test_prep_defines_terms_and_saves_rehearsals(self):
        text = self.text("interview-prep")
        for phrase in ("Glossary", "best guess", "Rehearsed answers"):
            self.assertIn(phrase, text)

    def test_review_writes_to_interview_file_not_notes(self):
        text = self.text("interview-review")
        self.assertNotIn("Append the review under", text)
        self.assertNotIn("appends it to the opportunity's notes.md", text)
        self.assertIn("## Review (<date>)", text)
        self.assertIn("question actually asked", text)

    def test_both_skills_match_existing_session_files(self):
        """Prep and review must find the same file: unreviewed files for the
        same interviewer(s) or a label for this stage, at any date."""
        for name in ("interview-prep", "interview-review"):
            text = self.text(name)
            self.assertIn("no `## Review` section yet", text, name)
            self.assertIn("any date", text, name)
            self.assertIn("label", text, name)
            self.assertIn("already reviewed", text, name)

    def test_talking_points_needs_ok(self):
        for name in ("interview-prep", "interview-review"):
            self.assertIn("only with the user's OK", self.text(name), name)


class InterviewLinksFollowedTest(unittest.TestCase):
    """Interview prep and reviews live in prep/ files linked from notes.md;
    anything reading an opportunity's history must follow those links."""

    def text(self, rel):
        return (PLUGIN / rel).read_text()

    def test_notes_readers_follow_interview_links(self):
        for rel in ("skills/career-coach/SKILL.md", "skills/offer-negotiator/SKILL.md",
                    "skills/score-opportunity/SKILL.md", "skills/backfill-history/SKILL.md",
                    "skills/interview-prep/SKILL.md", "guidance/persona.md"):
            self.assertIn("prep/", self.text(rel), rel)

    def test_backfill_reads_both_review_headings(self):
        text = self.text("skills/backfill-history/SKILL.md")
        self.assertIn("## Review (<date>)", text)
        self.assertIn("## Interview Review (<date>)", text)

    def test_persona_lists_talking_points(self):
        self.assertIn("career/talking_points.md", self.text("guidance/persona.md"))


if __name__ == "__main__":
    unittest.main()
