#!/usr/bin/env python3
"""Locate (or create) the job-search-os workspace.

A workspace is any directory containing a MARKER file. All personal state
lives there; the plugin's own code never does. Tools find the workspace by
walking up from the current directory, the way git finds .git, so they keep
working if Claude has cd'd into a subfolder such as an opportunity folder.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

MARKER = ".job-search-os.json"
SCHEMA = 1


def find_root(start=None):
    here = Path(start if start is not None else Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / MARKER).is_file():
            return d
    return None


def require_root():
    root = find_root()
    if root is None:
        print(
            f"error: not inside a job-search-os workspace (no {MARKER} found "
            f"from {Path.cwd()} upward). Run the bootstrap skill to create "
            "one, or cd into your workspace.",
            file=sys.stderr,
        )
        sys.exit(2)
    return root


def init_root(path):
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if not marker.exists():
        marker.write_text(json.dumps(
            {"schema": SCHEMA, "created": datetime.date.today().isoformat()},
            indent=2,
        ) + "\n")
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="make PATH (default: cwd) a workspace")
    p_init.add_argument("path", nargs="?", default=".")
    sub.add_parser("root", help="print the current workspace root")
    args = parser.parse_args()
    if args.command == "init":
        print(init_root(args.path))
    else:
        print(require_root())


if __name__ == "__main__":
    main()
