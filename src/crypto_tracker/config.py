"""Runtime locations and limits.

TRACKER_HOME (default ~/.local/share/crypto-tracker) contains:
  store/  JSON state written only by the collector (readable by the Hermes group)
  spool/  commands submitted by the MCP server, validated and applied by the collector
  collector.lock  single-instance lock
"""

import os
from pathlib import Path

MAX_PROJECTS = 20


def home():
    value = os.environ.get("TRACKER_HOME")
    return Path(value) if value else Path.home() / ".local/share/crypto-tracker"


class Paths:
    def __init__(self, root=None):
        self.root = Path(root) if root else home()
        self.store = self.root / "store"
        self.spool = self.root / "spool"
        self.lock = self.root / "collector.lock"

    def file(self, name):
        return self.store / name
