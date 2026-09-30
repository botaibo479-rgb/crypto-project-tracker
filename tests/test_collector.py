import json
import tempfile
import unittest
from unittest.mock import patch

from crypto_tracker import config
from crypto_tracker.collector.loops import Collector
from crypto_tracker.net.http import Requester
from crypto_tracker.sources import binance, opennews, rss
from crypto_tracker.store import jsonstore, spool

CLOCK = 2_000_000_000_000


def fake_api(path, params, request):
    if "ticker" in path:
        return {
            "lastPrice": "14",
            "priceChangePercent": "2",
            "quoteVolume": "100",
            "closeTime": CLOCK,
        }
    if "klines" in path:
        candles = [
            [
                CLOCK - (400 - i) * 14400000,
                0,
                0,
                0,
                str(10 + i / 100),
                0,
                CLOCK - (399 - i) * 14400000 - 1,
            ]
            for i in range(400)
        ]
        candles.append([CLOCK, 0, 0, 0, "999999", 0, CLOCK + 14400000])
        return candles
    return [
        {"timestamp": CLOCK - 3600000, "sumOpenInterest": "100"},
        {"timestamp": CLOCK, "sumOpenInterest": "110"},
    ]


PROJECT = {"id": "soon", "symbol": "SOON", "account": "soon_svm", "name": "SOON"}


class MarketTests(unittest.TestCase):
    def test_ema_seed_and_recurrence(self):
        self.assertEqual(binance.ema([1, 2], 3), [])
        self.assertEqual(binance.ema([1, 2, 3, 4], 3), [None, None, 2, 3])

    def test_closed_candles_and_oi_window(self):
        with (
            patch.object(binance, "api", side_effect=fake_api),
            patch.object(binance, "now", return_value=CLOCK),
        ):
            _, m = binance.market(PROJECT, None)
        self.assertEqual(m["klineCount"], 400)
        self.assertLess(m["ema200"], 14)
        self.assertAlmostEqual(m["oiChange1h"], 10)
        self.assertEqual(m["close4h"], 13.99)

    def test_short_oi_window_is_not_one_hour(self):
        def api(path, params, request):
            if "ticker" in path:
                raise TimeoutError()
            if "klines" in path:
                return []
            return [
                {"timestamp": CLOCK - 300000, "sumOpenInterest": "100"},
                {"timestamp": CLOCK, "sumOpenInterest": "110"},
            ]

        with patch.object(binance, "api", side_effect=api):
            _, m = binance.market(PROJECT, None)
        self.assertNotIn("oiChange1h", m)
        self.assertIn("oiWindow", m["errors"])
        self.assertNotIn("price", m)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.paths = config.Paths(self.dir.name)
        self.paths.spool.mkdir(parents=True)
        self.collector = Collector(self.paths, Requester(""))

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_token_is_explicit(self):
        store = rss.Store(self.paths.file("s.json"))
        events, status = opennews.provider_news(PROJECT, None, False, store)
        self.assertEqual(events, [])
        self.assertEqual(status["OpenTwitter"]["status"], "missing_credential")

    def test_public_source_success_status(self):
        row = {"id": "real", "p": "near", "title": "Official title"}
        near = self.collector.project("near")
        with patch(
            "crypto_tracker.sources.official_sites.public_news", return_value=[row]
        ):
            pid, items, status = self.collector.refresh_news(near)
        self.assertEqual(pid, "near")
        self.assertEqual(items, [row])
        self.assertEqual(status["官网资讯"]["status"], "ok")
        self.assertEqual(status["团队 X"]["status"], "missing_credential")

    def test_run_once_offline_persists_state_without_token(self):
        def offline(*args, **kwargs):
            raise TimeoutError()

        with (
            patch.object(binance, "api", side_effect=offline),
            patch("crypto_tracker.net.safe_fetch.fetch", side_effect=offline),
            patch("crypto_tracker.net.http.direct", side_effect=offline) as direct,
        ):
            self.collector.run_once()
        direct.assert_not_called()
        live = jsonstore.read(self.paths.file("live-cache.json"), {})
        self.assertEqual(live["credential"], {"opennews": "missing"})
        self.assertEqual(
            {p["id"] for p in live["projects"]}, {"soon", "near", "pha", "nil"}
        )
        self.assertIn("errors", live["markets"]["near"])

    def test_token_is_never_written_to_store(self):
        token = "tok-" + "9" * 40
        collector = Collector(self.paths, Requester(token))

        def provider(url, payload=None, **kwargs):
            self.assertEqual(kwargs["token"], token)
            return json.dumps({"success": True, "data": []})

        with (
            patch.object(binance, "api", side_effect=TimeoutError()),
            patch("crypto_tracker.net.safe_fetch.fetch", side_effect=TimeoutError()),
            patch("crypto_tracker.net.http.direct", side_effect=provider),
        ):
            collector.run_once()
        written = [p for p in self.paths.root.rglob("*") if p.is_file()]
        self.assertTrue(written)
        for path in written:
            self.assertNotIn(token, path.read_text(errors="ignore"), path)
        live = jsonstore.read(self.paths.file("live-cache.json"), {})
        self.assertEqual(live["credential"], {"opennews": "set"})

    def run_command(self, kind, payload):
        ident = spool.submit(self.paths.spool, kind, payload)
        self.collector.process_spool()
        return spool.results(self.paths.store)[ident]

    def test_spool_rule_lifecycle_uses_existing_validation(self):
        bad = self.run_command(
            "upsert_rule", {"p": "near", "type": "shell", "name": "x"}
        )
        self.assertEqual(bad["status"], "error")
        good = self.run_command(
            "upsert_rule",
            {
                "p": "near",
                "type": "price",
                "name": "NEAR 5%",
                "period": "24h",
                "threshold": 5,
            },
        )
        self.assertEqual(good["status"], "ok")
        rid = good["result"]["rule"]["id"]
        rules = jsonstore.read(self.paths.file("alerts.json"), {})["rules"]
        self.assertEqual([r["id"] for r in rules], [rid])
        self.assertEqual(
            self.run_command("rule_action", {"id": rid, "action": "delete"})["status"],
            "ok",
        )
        self.assertEqual(
            jsonstore.read(self.paths.file("alerts.json"), {})["rules"], []
        )

    def test_spool_add_and_remove_project(self):
        with patch.object(self.collector, "_background"):
            added = self.run_command(
                "add_project",
                {
                    "name": "Arbitrum",
                    "symbol": "ARB",
                    "account": "arbitrum",
                    "website": "https://arbitrum.io",
                },
            )
        self.assertEqual(added["status"], "ok", added)
        saved = jsonstore.read(self.paths.file("projects.json"), [])
        self.assertIn("custom-arb", [p["id"] for p in saved])
        dup = self.run_command("add_project", {"name": "Arb", "symbol": "ARB"})
        self.assertEqual(dup["status"], "error")
        self.assertEqual(
            self.run_command("remove_project", {"projectId": "near"})["status"], "ok"
        )
        self.assertIsNone(self.collector.project("near"))
        reloaded = Collector(self.paths, Requester(""))
        self.assertIsNone(reloaded.project("near"))
        self.assertIsNotNone(reloaded.project("custom-arb"))

    def test_spool_rejects_unknown_symlinks_and_oversize(self):
        with self.assertRaises(ValueError):
            spool.submit(self.paths.spool, "exec", {})
        with self.assertRaises(ValueError):
            spool.submit(self.paths.spool, "refresh", {"x": "y" * spool.MAX_BYTES})
        target = self.paths.root / "outside.json"
        target.write_text(json.dumps({"kind": "refresh", "payload": {}}))
        (self.paths.spool / ("1" * 13 + "-" + "a" * 32 + ".json")).symlink_to(target)
        (self.paths.spool / "note.txt").write_text("ignored")
        self.collector.process_spool()
        result = spool.results(self.paths.store)["1" * 13 + "-" + "a" * 32]
        self.assertEqual(result["status"], "error")
        self.assertTrue(target.exists())
        self.assertTrue((self.paths.spool / "note.txt").exists())

    def test_refresh_is_rate_limited(self):
        with patch.object(self.collector, "_background") as background:
            first = self.run_command("refresh", {"projectId": "near"})
            second = self.run_command("refresh", {"projectId": "near"})
        self.assertEqual(first["result"]["started"], ["near"])
        self.assertEqual(second["result"]["started"], [])
        self.assertEqual(background.call_count, 1)


if __name__ == "__main__":
    unittest.main()
