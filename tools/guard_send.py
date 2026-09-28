#!/usr/bin/env python3
"""PreToolUse hook: inside a job-search-os workspace, deny Gmail send /
reply / forward. Outside a workspace, stay silent (normal permissions apply).

Fails closed: the hook's matcher only invokes it for send-like tools, so if
the input can't be understood, denying is the safe answer.
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import session_start  # noqa: E402
import workspace  # noqa: E402

SEND_TOOL = re.compile(r"^mcp__.*Gmail.*__(send_message|reply|forward)$")
REASON = ("job-search-os: sending correspondence is disabled in job-search "
          "workspaces. Draft the message instead and let the user send it.")


def decide(hook_input):
    if not SEND_TOOL.search(hook_input["tool_name"]):
        return False
    # Deny if either the session's project dir or the directory Claude is
    # working in is inside a workspace (e.g. a session started elsewhere
    # that has since moved into one).
    starts = [session_start.resolve_start(hook_input), hook_input.get("cwd")]
    return any(workspace.find_root(s) is not None for s in starts if s)


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
        deny = decide(hook_input)
    except Exception as e:
        print(f"job-search-os guard_send: {e}; failing closed", file=sys.stderr)
        deny = True
    if deny:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }}))


if __name__ == "__main__":
    main()
