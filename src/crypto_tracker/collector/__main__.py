"""Run the collector: ``python -m crypto_tracker.collector [--once]``."""

import argparse
import logging
import os
import sys

from crypto_tracker import config, credentials, logging_setup
from crypto_tracker.collector.loops import Collector
from crypto_tracker.net.http import Requester

log = logging.getLogger("crypto_tracker.collector")


def acquire_lock(path):
    """Single instance per TRACKER_HOME; the lock is released when the process exits."""
    import fcntl

    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crypto-tracker-collector")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument(
        "--home", help="TRACKER_HOME (default: env or ~/.local/share/crypto-tracker)"
    )
    parser.add_argument(
        "--log-level", default=os.environ.get("TRACKER_LOG_LEVEL", "INFO")
    )
    args = parser.parse_args(argv)

    token = credentials.load("OPENNEWS_TOKEN", "opennews_token")
    defillama_key = credentials.load("DEFILLAMA_API_KEY", "defillama_key")
    logging_setup.configure(args.log_level, secrets=[token, defillama_key])

    paths = config.Paths(args.home)
    # store: group-readable for Hermes; spool: group-writable for MCP commands.
    for directory, mode in (
        (paths.root, 0o750),
        (paths.store, 0o750),
        (paths.spool, 0o2770),
    ):
        directory.mkdir(parents=True, exist_ok=True, mode=mode)
    lock = acquire_lock(paths.lock)
    if lock is None:
        log.error("another collector is already running for %s", paths.root)
        return 1

    log.info(
        "starting collector home=%s opennews_token=%s defillama_key=%s",
        paths.root,
        credentials.fingerprint(token) or "missing",
        "set" if defillama_key else "missing",
    )
    collector = Collector(
        paths,
        Requester(token),
        defillama_key=defillama_key,
        rsshub=credentials.setting("SIGNAL_RSSHUB_URL"),
    )
    if args.once:
        collector.run_once()
        return 0
    try:
        collector.run_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
