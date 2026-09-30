"""stdio MCP server: ``python -m crypto_tracker.mcp_server``.

stdout carries JSON-RPC only; logs go to stderr. No credentials are loaded here.
"""

import argparse
import os
import sys

from crypto_tracker import config, logging_setup


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crypto-tracker-mcp")
    parser.add_argument(
        "--home", help="TRACKER_HOME (default: env or ~/.local/share/crypto-tracker)"
    )
    parser.add_argument(
        "--log-level", default=os.environ.get("TRACKER_LOG_LEVEL", "WARNING")
    )
    args = parser.parse_args(argv)
    logging_setup.configure(args.log_level)

    from crypto_tracker.mcp_server.tools import build

    build(config.Paths(args.home)).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
