import tempfile, unittest
from pathlib import Path
from alerts import Store, evaluate, validate

NOW = 1800000000000


class AlertTests(unittest.TestCase):
    def rule(self, kind="price"):
        return dict(
            id="r",
            p="near",
            type=kind,
            name="Test",
            period="24h",
            threshold=5,
            cooldownMinutes=60,
            on=True,
            createdAt=NOW - 1000,
        )

    def test_baseline_then_reset_then_cross_and_dedupe(self):
        r = self.rule()
        rt = {}

        def tick(value, offset):
            return evaluate(
                r, rt, {"change24h": value, "priceAt": NOW + offset}, [], NOW + offset
            )

        self.assertEqual(tick(8, 0), [])
        self.assertEqual(tick(2, 60000), [])
        self.assertEqual(len(tick(6, 120000)), 1)
        self.assertEqual(tick(6, 120000), [])
        tick(1, 180000)
        self.assertEqual(tick(8, 240000), [])
        tick(1, 4000000)
        self.assertEqual(len(tick(8, 4060000)), 1)

    def test_stale_missing_and_future_data_do_not_trigger(self):
        for m in [
            {},
            {"change24h": 10, "priceAt": NOW - 700000},
            {"change24h": 10, "priceAt": NOW + 1},
        ]:
            rt = {"condition": False}
            self.assertEqual(evaluate(self.rule(), rt, m, [], NOW), [])
            self.assertEqual(rt["status"], "missing_data")

    def test_level_requires_new_closed_candle_and_persists(self):
        r = self.rule("level")
        r["threshold"] = 10
        rt = {}
        m = {
            "candleAt": NOW - 2000,
            "close4h": 11,
            "candles": [{"close": 9}, {"close": 11}],
        }
        self.assertEqual(evaluate(r, rt, m, [], NOW), [])
        m["candleAt"] = NOW
        self.assertEqual(len(evaluate(r, rt, m, [], NOW + 1)), 1)
        self.assertEqual(evaluate(r, rt, m, [], NOW + 3600001), [])

    def test_news_requires_new_publication_and_one_event_once(self):
        r = self.rule("news")
        rt = {}
        e = {"id": "n", "p": "near", "publishedAt": NOW, "high": True, "title": "Title"}
        self.assertEqual(len(evaluate(r, rt, {}, [e], NOW + 1)), 1)
        self.assertEqual(
            evaluate(r, rt, {}, [{**e, "revision": "updated"}], NOW + 3600001), []
        )
        self.assertEqual(
            evaluate(
                r, rt, {}, [{**e, "id": "old", "publishedAt": NOW - 2000}], NOW + 1
            ),
            [],
        )

    def test_later_progress_can_trigger_after_old_initial_story(self):
        r = self.rule("news")
        rt = {}
        e = {
            "id": "n",
            "p": "near",
            "publishedAt": NOW - 2000,
            "high": True,
            "title": "Old story",
            "progressCandidates": [
                {
                    "key": "v2",
                    "publishedAt": NOW,
                    "url": "https://example.org/update",
                    "reason": "New amount",
                    "signals": ["$200 million"],
                }
            ],
        }
        self.assertEqual(len(evaluate(r, rt, {}, [e], NOW + 1)), 1)
        self.assertEqual(evaluate(r, rt, {}, [e], NOW + 3600001), [])

    def test_record_and_dedupe_survive_store_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "alerts.json"
            store = Store(path)
            r = self.rule()
            r.pop("id")
            saved = store.upsert(r, ["near"])
            t = saved["createdAt"] + 1000
            store.tick({"near": {"change24h": 1, "priceAt": t}}, [], t)
            store.tick({"near": {"change24h": 6, "priceAt": t + 60000}}, [], t + 60000)
            self.assertEqual(len(store.snapshot()["alerts"]), 1)
            reloaded = Store(path)
            reloaded.tick(
                {"near": {"change24h": 6, "priceAt": t + 60000}}, [], t + 60000
            )
            self.assertEqual(len(reloaded.snapshot()["alerts"]), 1)

    def test_reject_unsupported_rule_and_persist_reload(self):
        with self.assertRaises(ValueError):
            validate({**self.rule(), "period": "15m"}, ["near"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "alerts.json"
            store = Store(path)
            r = self.rule()
            r.pop("id")
            saved = store.upsert(r, ["near"])
            store.action(saved["id"], "toggle")
            reloaded = Store(path)
            self.assertFalse(reloaded.snapshot()["rules"][0]["on"])
            reloaded.action(saved["id"], "delete")
            self.assertEqual(Store(path).snapshot()["rules"], [])


if __name__ == "__main__":
    unittest.main()
