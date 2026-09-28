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


if __name__ == "__main__":
    unittest.main()
