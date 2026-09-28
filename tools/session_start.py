#!/usr/bin/env python3
"""SessionStart hook: inside a job-search-os workspace, inject the persona/
guardrails (guidance/persona.md) plus any bootstrap-completeness note.
Outside a workspace, do nothing. Never fails the session."""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import check_bootstrap_state  # noqa: E402
import workspace  # noqa: E402

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).parent.parent).resolve()
PERSONA_PATH = PLUGIN_ROOT / "guidance" / "persona.md"


def resolve_start(hook_input):
    return (os.environ.get("CLAUDE_PROJECT_DIR")
            or hook_input.get("cwd")
            or os.getcwd())


def build_context(root):
    persona = PERSONA_PATH.read_text().replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))
    parts = [persona, f"Workspace root: {root}"]
    note = check_bootstrap_state.bootstrap_note(root)
    if note:
        parts.append("Setup status: " + note)
    return "\n\n".join(parts)


def main():
    try:
        try:
            hook_input = json.loads(sys.stdin.read() or "{}")
            if not isinstance(hook_input, dict):
                hook_input = {}
        except ValueError:
            hook_input = {}
        root = workspace.find_root(resolve_start(hook_input))
        if root is None:
            return
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_context(root),
        }}))
    except Exception as e:  # never break a session over this hook
        print(f"job-search-os session_start: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
