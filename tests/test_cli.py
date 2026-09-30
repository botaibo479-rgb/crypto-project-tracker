import json
import tempfile
import unittest
from pathlib import Path

from crypto_tracker import cli, config


class MigrateTests(unittest.TestCase):
    def test_copies_known_files_only_and_never_touches_source(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            old = Path(old)
            (old / "alerts.json").write_text(json.dumps({"rules": [], "alerts": []}))
            (old / "translations.json").write_text("{}")
            (old / ".env.local").write_text("OPENNEWS_TOKEN=x")
            before = {p.name: p.read_text() for p in old.iterdir()}
            paths = config.Paths(new)
            result = cli.migrate(old, paths)
            self.assertEqual(result["copied"], ["alerts.json"])
            self.assertFalse(paths.file("translations.json").exists())
            self.assertFalse(paths.file(".env.local").exists())
            self.assertEqual({p.name: p.read_text() for p in old.iterdir()}, before)
            paths.file("alerts.json").write_text(json.dumps({"rules": [1]}))
            self.assertEqual(cli.migrate(old, paths)["skipped"], ["alerts.json"])
            self.assertEqual(
                json.loads(paths.file("alerts.json").read_text()), {"rules": [1]}
            )
            cli.migrate(old, paths, force=True)
            self.assertEqual(
                json.loads(paths.file("alerts.json").read_text())["rules"], []
            )

    def test_status_without_store(self):
        with tempfile.TemporaryDirectory() as home:
            result = cli.status(config.Paths(home))
            self.assertEqual(result["projects"], [])
            self.assertEqual(result["pendingCommands"], 0)


if __name__ == "__main__":
    unittest.main()
