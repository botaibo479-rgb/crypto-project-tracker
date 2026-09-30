"""Portable local launcher. Configuration never searches another project."""

import os
import runpy
from pathlib import Path

root = Path(__file__).resolve().parent
local = root / ".env.local"
if (
    not os.environ.get("OPENNEWS_TOKEN")
    and not os.environ.get("SIGNAL_ENV_FILE")
    and local.exists()
):
    os.environ["SIGNAL_ENV_FILE"] = str(local)
runpy.run_path(str(root / "server.py"), run_name="__main__")
