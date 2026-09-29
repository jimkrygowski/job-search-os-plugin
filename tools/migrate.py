#!/usr/bin/env python3
"""Copy an original job-search-os checkout's state/ into a workspace.

Read-only on the source. All-or-nothing: if any destination file already
exists, nothing is copied. Writes the workspace marker on success.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never write into the plugin directory
sys.path.insert(0, str(Path(__file__).parent))
import tracker  # noqa: E402
import workspace  # noqa: E402

SKIP_NAMES = {".tracker.lock", ".DS_Store"}
SKIP_DIRS = {"__pycache__"}
STATE_SIGNS = ("career", "opportunity", "tracker.md")


def _looks_like_state(path):
    return any((path / s).exists() for s in STATE_SIGNS)


def resolve_source(from_path):
    p = Path(from_path).expanduser().resolve()
    if (p / "state").is_dir() and _looks_like_state(p / "state"):
        return p / "state"
    if _looks_like_state(p):
        return p
    raise ValueError(
        f"{p} doesn't look like a job-search-os checkout or its state/ folder "
        "(expected career/, opportunity/, or tracker.md)")


def plan(src, dst):
    pairs = []
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if not f.is_file() or f.name in SKIP_NAMES or SKIP_DIRS & set(rel.parts):
            continue
        pairs.append((f, dst / rel))
    return pairs


def plan_dirs(src, dst):
    """Every directory in the source tree, so empty ones (e.g. a
    transcripts/ folder with nothing in it yet) survive the migration."""
    return [dst / d.relative_to(src) for d in sorted(src.rglob("*"))
            if d.is_dir() and not SKIP_DIRS & set(d.relative_to(src).parts)]


def conflicts(pairs):
    return [d for _, d in pairs if d.exists()]


def stage_report(src):
    """Stage names in the old trackers that aren't canonical. Reported only:
    the copied files are left exactly as they were."""
    lines = []
    for name, columns in (("tracker.md", tracker.ACTIVE_COLUMNS),
                          ("tracker_closed.md", tracker.CLOSED_COLUMNS)):
        path = src / name
        if not path.exists():
            continue
        try:
            rows = tracker.read_table(path, columns)
        except ValueError as e:
            lines.append(f"  {name}: couldn't read ({e})")
            continue
        for row in rows:
            stage = row["Stage"]
            if stage in tracker.STAGES:
                continue
            mapped = tracker.canonical_stage(stage)
            where = f"{name}: {row['Company']} / {row['Role']}"
            if mapped:
                lines.append(f"  {where}: {stage!r} -> {mapped!r} (mapped automatically)")
            else:
                lines.append(f"  {where}: {stage!r} is not a known stage — "
                             "fix it with tracker.py update-status")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="src", required=True,
                        help="original job-search-os checkout (or its state/ folder)")
    parser.add_argument("--to", dest="dst", default=".", help="workspace (default: cwd)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        src = resolve_source(args.src)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    dst = Path(args.dst).expanduser().resolve()
    # The old checkout (the repo around state/, or the folder itself) is
    # read-only: never let the workspace land anywhere inside it.
    checkout = src.parent if src.name == "state" else src
    if dst == checkout or checkout in dst.parents:
        print(f"error: {dst} is inside the old checkout {checkout}. Pick a "
              "workspace folder outside it (e.g. ~/job-search).", file=sys.stderr)
        sys.exit(2)
    pairs = plan(src, dst)
    dirs = plan_dirs(src, dst)

    clash = conflicts(pairs)
    if clash:
        print("Refusing to migrate — these files already exist in the workspace:")
        for d in clash:
            print(f"  {d.relative_to(dst)}")
        print("Nothing was copied.")
        sys.exit(1)

    verb = "Would copy" if args.dry_run else "Copied"
    if not args.dry_run:
        workspace.init_root(dst)
        for s, d in pairs:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    for _, d in pairs:
        print(f"  {d.relative_to(dst)}")
    print(f"{verb} {len(pairs)} files from {src} to {dst}")
    report = stage_report(src)
    if report:
        print("Stage names that differ from the canonical list "
              f"({', '.join(tracker.STAGES)}):")
        print("\n".join(report))


if __name__ == "__main__":
    main()
