"""Repository hygiene: no hidden or bidirectional control characters in sources
(Trojan Source, CVE-2021-42574) and no obvious credentials committed."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".sh", ".json", ".service", ".txt"}
SKIP = {".git", ".venv", "__pycache__"}
HIDDEN = re.compile(
    "[\\u200b-\\u200f\\u2028-\\u202e\\u2060-\\u2069\\ufeff\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]"
)
SECRET = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._-]{24,}|sk-[a-z0-9]{20,}|ghp_[a-z0-9]{30,}"
    r"|OPENNEWS_TOKEN\s*=\s*['\"]?[a-z0-9._-]{16,})"
)


def files():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in SUFFIXES and not SKIP & set(path.parts):
            yield path


class HygieneTests(unittest.TestCase):
    def test_no_hidden_or_bidi_characters(self):
        found = []
        for path in files():
            for number, line in enumerate(
                path.read_text(errors="ignore").splitlines(), 1
            ):
                if HIDDEN.search(line):
                    found.append("%s:%d" % (path.relative_to(ROOT), number))
        self.assertEqual(found, [])

    def test_no_committed_credentials(self):
        found = [
            str(path.relative_to(ROOT))
            for path in files()
            if path.name != "uv.lock" and SECRET.search(path.read_text(errors="ignore"))
        ]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
