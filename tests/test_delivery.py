import unittest, tempfile, datetime as dt, os
from unittest.mock import patch
from pathlib import Path
from crypto_tracker.core.digest import Store, make_digest


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

    def test_daily_digest_persists_once_after_hour_without_push(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            store = Store(Path(d) / "state.json")
            before = dt.datetime(2026, 9, 30, 7).astimezone()
            store.tick([], [], [], before)
            self.assertFalse(store.data["digests"])
            store.tick([], [], [], before + dt.timedelta(hours=1))
            self.assertEqual(len(store.data["digests"]), 1)
            self.assertFalse(store.data["outbox"])
