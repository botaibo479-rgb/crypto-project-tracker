"""Logging to stderr with secret redaction.

stdout is reserved: the MCP server speaks JSON-RPC on it, and Hermes delivers
cron script stdout verbatim. Nothing in this package prints to stdout.
"""

import logging
import sys

from crypto_tracker.credentials import redact


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt, secrets=()):
        super().__init__(fmt)
        self.secrets = [s for s in secrets if s]

    def format(self, record):
        return redact(super().format(record), self.secrets)


def configure(level="INFO", secrets=()):
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", secrets)
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    return root
