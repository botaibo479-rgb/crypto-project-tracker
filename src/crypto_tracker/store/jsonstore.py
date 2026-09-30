"""Atomic JSON persistence.

Writers replace files with os.replace, so a reader in another process (the MCP
server) always sees either the previous or the new complete document.
"""

import copy
import json
import os
import tempfile
from pathlib import Path

FILE_MODE = 0o640


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (ValueError, OSError):
        return copy.deepcopy(default)


def write(path, value, mode=FILE_MODE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix="." + path.name + ".", suffix=".tmp"
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
