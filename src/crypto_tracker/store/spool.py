"""Command spool between the MCP server (writer) and the collector (reader).

The MCP server never modifies collector state. It drops one JSON command per
file into spool/; the collector validates each command with the same
validators the web reader used and records the outcome in store/commands.json.

File contract: name ``<13-digit ms>-<32 hex>.json``, regular file (no symlinks),
at most MAX_BYTES, body ``{"kind": <KINDS>, "payload": {...}}``.
"""

import json
import os
import re
import stat
import time
import uuid
from pathlib import Path

from crypto_tracker.store import jsonstore

NAME = re.compile(r"^(\d{13}-[0-9a-f]{32})\.json$")
MAX_BYTES = 65536
FILE_MODE = 0o660
KINDS = frozenset(
    {
        "prepare_project",
        "add_project",
        "remove_project",
        "add_team_member",
        "set_rootdata_source",
        "add_rss_source",
        "rss_action",
        "discover_rss",
        "upsert_rule",
        "rules_template",
        "rule_action",
        "watch_account",
        "unwatch_account",
        "viewpoint_alerts",
        "track_event",
        "untrack_event",
        "refresh",
        "set_calendar_mapping",
    }
)
RESULTS = "commands.json"


def submit(spool_dir, kind, payload):
    """Queue a command; returns its id. Used by the MCP server."""
    if kind not in KINDS:
        raise ValueError("unknown command")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    ident = "%013d-%s" % (int(time.time() * 1000), uuid.uuid4().hex)
    body = json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False).encode()
    if len(body) > MAX_BYTES:
        raise ValueError("command too large")
    spool_dir = Path(spool_dir)
    tmp = spool_dir / (".tmp-" + ident)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        os.replace(tmp, spool_dir / (ident + ".json"))
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return ident


def _read(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    if info.st_size > MAX_BYTES:
        raise ValueError("command too large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        command = json.loads(handle.read(MAX_BYTES + 1))
    if (
        not isinstance(command, dict)
        or command.get("kind") not in KINDS
        or not isinstance(command.get("payload"), dict)
    ):
        raise ValueError("invalid command")
    return command


def pending(spool_dir, limit=20):
    """Yield ``(id, command_or_None, error_or_None)`` oldest first, then remove the file."""
    spool_dir = Path(spool_dir)
    try:
        names = sorted(os.listdir(spool_dir))
    except FileNotFoundError:
        return
    count = 0
    for name in names:
        match = NAME.match(name)
        if not match:
            continue
        if count >= limit:
            break
        count += 1
        path = spool_dir / name
        try:
            command, error = _read(path), None
        except (OSError, ValueError) as e:
            command, error = None, type(e).__name__
        try:
            os.unlink(path)
        except OSError:
            pass
        yield match.group(1), command, error


def results(store_dir):
    return jsonstore.read(Path(store_dir) / RESULTS, {}) or {}


def record(store_dir, ident, kind, status, value, keep=200):
    path = Path(store_dir) / RESULTS
    data = jsonstore.read(path, {}) or {}
    data[ident] = {
        "kind": kind,
        "status": status,
        "result" if status == "ok" else "error": value,
        "finishedAt": int(time.time() * 1000),
    }
    data = dict(sorted(data.items())[-keep:])
    jsonstore.write(path, data)
