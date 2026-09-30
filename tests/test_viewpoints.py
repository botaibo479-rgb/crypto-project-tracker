import unittest, tempfile, time
from pathlib import Path
from crypto_tracker.core.viewpoints import Store, classify, DAY

P = {"id": "near", "symbol": "NEAR", "account": "NEARProtocol"}


class ViewpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / "v.json")
        self.now = int(time.time() * 1000) + 10000

    def row(self, ident, text, at):
        return dict(
            id=ident,
            account="alice",
            text=text,
            url="https://x.com/alice/status/" + ident,
            publishedAt=at,
        )

    def ingest(self, rows, at=None):
        self.s.ingest(P, dict(status="ok", posts=rows, limited=False), at or self.now)

    def test_conservative_classification(self):
        self.assertEqual(classify("I am bullish on $NEAR", P), "positive")
        self.assertEqual(classify("我看空$NEAR", P), "concern")
        for text in [
            "If it breaks I am bullish on $NEAR",
            "I am not bullish on $NEAR",
            "I am bullish on $BTC; $NEAR news",
            "I am short puts on $NEAR",
            '"I am bullish on $NEAR"',
            "NEAR will moon",
            "I am bullish on $NEAR but I am bearish on $NEAR",
        ]:
            self.assertEqual(classify(text, P), "unclear", text)

    def test_backfill_and_repeat_never_alert(self):
        self.s.configure(
            {"action": "alerts", "projectId": "near", "enabled": True}, ["near"]
        )
        rows = [
            self.row("1", "I am bullish on $NEAR", self.now - 1000),
            self.row("2", "I am bearish on $NEAR", self.now - 500),
        ]
        self.ingest(rows)
        self.ingest(rows, self.now + 500)
        self.assertEqual(self.s.snapshot("near", self.now)["changes"], [])

    def test_new_change_retains_both_sources(self):
        self.ingest([self.row("1", "I am bullish on $NEAR", self.now - 1000)])
        self.s.configure(
            {"action": "alerts", "projectId": "near", "enabled": True}, ["near"]
        )
        self.ingest(
            [self.row("2", "I am bearish on $NEAR", self.now + 500)], self.now + 1000
        )
        c = self.s.snapshot("near", self.now + 1000)["changes"]
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["before"]["id"], "1")

    def test_quote_and_unclear_interrupt_change(self):
        self.ingest([self.row("1", "I am bullish on $NEAR", self.now - 1000)])
        self.s.configure(
            {"action": "alerts", "projectId": "near", "enabled": True}, ["near"]
        )
        self.ingest(
            [
                {
                    **self.row("2", "I am bearish on $NEAR", self.now + 500),
                    "quoted": True,
                }
            ],
            self.now + 1000,
        )
        self.assertEqual(self.s.snapshot("near", self.now + 1000)["changes"], [])

    def test_failure_preserves_history_and_status(self):
        self.ingest([self.row("1", "news", self.now - 1000)])
        self.s.ingest(P, {"status": "error"}, self.now + 1000)
        x = self.s.snapshot("near", self.now + 1000)
        self.assertEqual(len(x["posts"]), 1)
        self.assertEqual(x["coverage"]["status"], "error")
        self.assertIsNone(x["attention"]["newInSample"])

    def test_watches_validate_and_persist(self):
        self.s.configure(
            {
                "action": "watch",
                "account": "@Alice",
                "projectIds": ["near"],
                "note": "research",
            },
            ["near"],
        )
        self.assertEqual(Store(self.s.path).watches("near")[0]["account"], "alice")
        with self.assertRaises(ValueError):
            self.s.configure(
                {"action": "watch", "account": "bob", "projectIds": ["invalid"]},
                ["near"],
            )
        self.s.configure({"action": "remove", "account": "Alice"}, ["near"])
        self.assertEqual(self.s.watches("near"), [])

    def test_sampling_does_not_fill_missed_window(self):
        self.s.track(
            {"id": "x", "title": "news"},
            "near",
            {"price": 10, "priceAt": self.now},
            self.now,
        )
        self.s.sample(
            {"near": {"price": 12, "priceAt": self.now + 3600000}}, self.now + 3600000
        )
        self.s.sample(
            {"near": {"price": 13, "priceAt": self.now + DAY + 600000}},
            self.now + DAY + 600000,
        )
        t = self.s.snapshot("near", self.now)["tracking"][0]
        self.assertAlmostEqual(t["samples"]["1h"]["change"], 20)
        self.assertNotIn("24h", t["samples"])

    def test_stale_start_rejected(self):
        with self.assertRaises(ValueError):
            self.s.track(
                {"id": "x", "title": "news"},
                "near",
                {"price": 10, "priceAt": 1},
                self.now,
            )


if __name__ == "__main__":
    unittest.main()


class CollectionTests(unittest.TestCase):
    def test_explicit_watch_bypasses_floor_and_wrong_author_rejected(self):
        import json, time
        from crypto_tracker.sources import social as features
        from unittest.mock import patch

        at = int(time.time() * 1000)
        rows = [
            {
                "id": "123",
                "userScreenName": "alice",
                "userFollowers": 10,
                "createdAt": at,
                "text": "I am bullish on $NEAR @NEARProtocol",
            },
            {
                "id": "124",
                "userScreenName": "intruder",
                "userFollowers": 50000,
                "createdAt": at,
                "text": "News @NEARProtocol",
            },
        ]

        def request(url, payload):
            return json.dumps(
                {"success": True, "data": rows if payload.get("fromUser") else []}
            )

        with patch.object(features, "enrich_avatars"):
            x = features.discover(P, request, lambda x: x, [{"account": "alice"}])
        self.assertEqual([r["account"] for r in x["posts"]], ["alice"])
        self.assertEqual(x["discussants"], [])

    def test_watch_failure_is_reported(self):
        import json
        from crypto_tracker.sources import social as features
        from unittest.mock import patch

        def request(url, payload):
            if payload.get("fromUser"):
                raise ValueError("failed")
            return json.dumps({"data": []})

        with patch.object(features, "enrich_avatars"):
            x = features.discover(P, request, lambda x: x, [{"account": "alice"}])
        self.assertEqual(x["watchErrors"], ["alice"])
