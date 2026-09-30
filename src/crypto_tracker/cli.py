"""Operator CLI: ``crypto-tracker status | migrate --from DIR``."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from crypto_tracker import config
from crypto_tracker.store import jsonstore

# Files of the original web reader's data/ directory that carry over unchanged.
LEGACY_FILES = [
    "live-cache.json",
    "projects.json",
    "alerts.json",
    "intelligence.json",
    "delivery.json",
    "public-sources.json",
    "project-calendar.json",
    "viewpoints.json",
    "avatars.json",
]


def migrate(source, paths, force=False):
    """Copy legacy data into the store. The source directory is never modified."""
    source = Path(source)
    if not source.is_dir():
        raise SystemExit(f"{source} 不是目录")
    paths.store.mkdir(parents=True, exist_ok=True)
    copied, skipped = [], []
    for name in LEGACY_FILES:
        origin, target = source / name, paths.file(name)
        if not origin.is_file():
            continue
        if target.exists() and not force:
            skipped.append(name)
            continue
        # Round-trip through JSON so only well-formed documents are carried over.
        jsonstore.write(target, json.loads(origin.read_text()))
        copied.append(name)
    return {"copied": copied, "skipped": skipped}


def status(paths):
    live = jsonstore.read(paths.file("live-cache.json"), {}) or {}
    return {
        "home": str(paths.root),
        "credential": live.get("credential", {}),
        "persistedAt": live.get("persistedAt"),
        "projects": [p["id"] for p in live.get("projects", [])],
        "collectors": live.get("collectors", {}),
        "pendingCommands": len(list(paths.spool.glob("*.json")))
        if paths.spool.exists()
        else 0,
    }


def backup(paths, destination):
    """Archive the store before an upgrade or migration."""
    return shutil.make_archive(
        str(destination), "gztar", root_dir=paths.root, base_dir="store"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crypto-tracker")
    parser.add_argument("--home", help="TRACKER_HOME")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="collector health from the store")
    m = sub.add_parser("migrate", help="copy the old reader's data/ into the store")
    m.add_argument("--from", dest="source", required=True)
    m.add_argument(
        "--force", action="store_true", help="overwrite existing store files"
    )
    b = sub.add_parser("backup", help="tar.gz archive of the store")
    b.add_argument("destination", help="archive path without extension")
    args = parser.parse_args(argv)
    paths = config.Paths(args.home)
    if args.command == "status":
        result = status(paths)
    elif args.command == "migrate":
        result = migrate(args.source, paths, args.force)
    else:
        result = {"archive": backup(paths, args.destination)}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
