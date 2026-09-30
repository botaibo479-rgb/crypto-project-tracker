import unittest, tempfile, datetime as dt, os
from unittest.mock import patch
from pathlib import Path
from delivery import Store, make_digest, ntfy_config


class DeliveryTests(unittest.TestCase):
    def test_digest_uses_yesterday_quality_and_three_per_project(self):
        current = dt.datetime(2026, 9, 30, 9).astimezone()
        date = dt.datetime(2026, 9, 29, 12).astimezone().timestamp() * 1000
        rows = [
            dict(
                id=str(i),
                p="near",
                title="Event " + str(i),
                publishedAt=date,
                qualityScore=60,
            )
            for i in range(6)
        ]
        rows += [
            dict(
                id="noise",
                p="near",
                title="💙",
                publishedAt=date,
                qualityScore=90,
                lowInformation=True,
            ),
            dict(
                id="today",
                p="near",
                title="Today",
                publishedAt=current.timestamp() * 1000,
                qualityScore=90,
            ),
        ]
        result = make_digest(rows, [{"id": "near", "name": "NEAR"}], current)
        self.assertEqual(result["date"], "2026-09-29")
        self.assertEqual(len(result["items"]), 3)
        self.assertFalse(any(i["id"] in ["noise", "today"] for i in result["items"]))

    def test_config_is_opt_in_and_no_arbitrary_webhook(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(ntfy_config())
        with patch.dict(
            os.environ,
            {
                "SIGNAL_PUSH_ENABLED": "1",
                "SIGNAL_NTFY_URL": "https://localhost/private",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                ntfy_config()

    def test_no_historical_push_and_no_duplicate_on_restart(self):
        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(
                os.environ,
                {
                    "SIGNAL_PUSH_ENABLED": "1",
                    "SIGNAL_NTFY_URL": "https://ntfy.sh/private-topic-example",
                },
                clear=True,
            ),
        ):
            store = Store(Path(d) / "state.json")
            current = dt.datetime(2026, 9, 30, 7).astimezone()
            now = int(current.timestamp() * 1000)
            sent = []
            sender = lambda *a: sent.append(a)
            alert = {
                "id": "a",
                "at": now - 10,
                "ruleName": "OI",
                "title": "test",
                "evidence": {},
            }
            store.tick([], [], [alert], current, sender)
            self.assertEqual(sent, [])
            alert["at"] = now + 1000
            store.tick([], [], [alert], current + dt.timedelta(seconds=2), sender)
            self.assertEqual(len(sent), 1)
            Store(Path(d) / "state.json").tick(
                [], [], [alert], current + dt.timedelta(seconds=3), sender
            )
            self.assertEqual(len(sent), 1)

    def test_daily_digest_persists_once_after_hour_without_push(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            store = Store(Path(d) / "state.json")
            before = dt.datetime(2026, 9, 30, 7).astimezone()
            store.tick([], [], [], before)
            self.assertFalse(store.data["digests"])
            store.tick([], [], [], before + dt.timedelta(hours=1))
            self.assertEqual(len(store.data["digests"]), 1)
            self.assertFalse(store.data["outbox"])
