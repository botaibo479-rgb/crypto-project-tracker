"""Portable local launcher. Credentials are read by credentials.py (never another project)."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "server.py"), run_name="__main__")
