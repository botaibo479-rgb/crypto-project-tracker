import importlib.util
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent.parent / "hermes/scripts/tracker-alerts.py"


class AlertScriptTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.store = root / "home/store"
        self.store.mkdir(parents=True)
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copy(SCRIPT, scripts / "tracker-alerts.py")
        spec = importlib.util.spec_from_file_location(
            "tracker_alerts", scripts / "tracker-alerts.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.env = patch.dict(os.environ, {"TRACKER_HOME": str(root / "home")})
        self.env.start()
        self.now = int(time.time() * 1000)
        self.write_live(self.now)

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def write_live(self, persisted):
        (self.store / "live-cache.json").write_text(
            json.dumps(
                {
                    "projects": [{"id": "near", "name": "NEAR Protocol"}],
                    "persistedAt": persisted,
                }
            )
        )

    def write_alerts(self, alerts):
        (self.store / "alerts.json").write_text(
            json.dumps({"rules": [], "alerts": alerts})
        )

    def run_script(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.module.main(), 0)
        return out.getvalue()

    def alert(self, ident, at, **extra):
        return {
            "id": ident,
            "p": "near",
            "ruleName": "NEAR 5%",
            "type": "price",
            "title": "24h 价格变化达到阈值\u202e",
            "at": at,
            "evidence": {
                "change24h": 6.2,
                "threshold": 5,
                "source": "Binance",
                "url": "javascript:x",
            },
            **extra,
        }

    def test_first_run_is_silent_then_delivers_each_alert_once(self):
        self.write_alerts([self.alert("old", self.now - 60000)])
        self.assertEqual(self.run_script(), "")
        self.assertEqual(self.run_script(), "")  # history is never replayed
        self.write_alerts(
            [
                self.alert("old", self.now - 60000),
                self.alert("new", int(time.time() * 1000) + 5),
            ]
        )
        text = self.run_script()
        self.assertIn("NEAR Protocol · NEAR 5%", text)
        self.assertIn("24h 变化 % 6.2", text)
        self.assertNotIn("\u202e", text)
        self.assertNotIn("javascript:", text)
        self.assertEqual(text.count("【Signal 提醒】"), 1)
        self.assertEqual(self.run_script(), "")

    def test_stale_collector_warning_is_rate_limited(self):
        self.assertEqual(self.run_script(), "")
        self.write_live(self.now - 30 * 60000)
        self.write_alerts([])
        self.assertIn("采集器告警", self.run_script())
        self.assertEqual(self.run_script(), "")

    def test_state_file_is_private(self):
        self.run_script()
        state = SCRIPT.name
        path = Path(self.module.__file__).with_name(".crypto-tracker-alerts.state.json")
        self.assertTrue(path.exists(), state)
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
