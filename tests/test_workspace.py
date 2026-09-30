import unittest, tempfile, time
from pathlib import Path
from unittest.mock import patch
from crypto_tracker.core import alerts, charts
from crypto_tracker.net import safe_fetch
from crypto_tracker.sources import defillama as pc, rss as ps


class WorkspaceTests(unittest.TestCase):
    def test_rss_atom_keep_time_and_never_execute_html(self):
        rows = ps.parse_feed(
            "<rss><channel><item><title>&lt;script&gt;x&lt;/script&gt;</title><link>https://example.com/a</link><pubDate>Wed, 30 Sep 2026 10:00:00 GMT</pubDate><description>&lt;b&gt;hello&lt;/b&gt;</description></item></channel></rss>",
            "https://example.com",
        )
        self.assertEqual(rows[0]["body"], "hello")
        self.assertGreater(rows[0]["at"], 0)
        rows = ps.parse_feed(
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link href="/post"/><updated>2026-09-30T10:00:00</updated></entry></feed>',
            "https://example.com",
        )
        self.assertIsNone(rows[0]["at"])
        self.assertEqual(rows[0]["url"], "https://example.com/post")

    def test_entities_and_local_urls_rejected(self):
        for url in [
            "http://example.com",
            "https://127.0.0.1/a",
            "https://localhost/a",
            "https://user:pass@example.com",
        ]:
            with self.assertRaises(ValueError):
                safe_fetch.public_url(url)
        with self.assertRaises(ValueError):
            ps.parse_feed("<!DOCTYPE x><rss/>", "https://example.com")
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 443))],
        ):
            with self.assertRaises(ValueError):
                safe_fetch.PublicHTTPS("example.com").connect()

    def test_routes_and_telegram_needs_config(self):
        self.assertEqual(
            ps.route("https://github.com/org/repo"),
            "https://github.com/org/repo/releases.atom",
        )
        self.assertEqual(
            ps.route("https://medium.com/@near"), "https://medium.com/feed/@near"
        )
        with self.assertRaises(ValueError):
            ps.route("https://t.me/example")

    def test_oi_sort_dedupe_and_invalid_data(self):
        self.assertEqual(
            charts.oi_snapshot(
                [
                    {"timestamp": 100, "sumOpenInterest": "3"},
                    {"timestamp": 100, "sumOpenInterest": "4"},
                    {"timestamp": 200, "sumOpenInterest": "nan"},
                    {"timestamp": 999, "sumOpenInterest": "5"},
                ],
                500,
            ),
            [{"time": 100, "value": 4.0}],
        )

    def test_funding_only_exact_id_and_past(self):
        now = int(time.time() * 1000)
        data = {
            "raises": [
                {
                    "name": "Same",
                    "defillamaId": "1",
                    "date": int(now / 1000) - 100,
                    "round": "Seed",
                },
                {"name": "Same", "defillamaId": "1", "date": int(now / 1000) + 100},
            ]
        }
        self.assertEqual(pc.normalize_raises(data, {"id": "x"}, now), [])
        self.assertEqual(
            len(pc.normalize_raises(data, {"id": "x", "calendarProtocolId": "1"}, now)),
            1,
        )

    def test_retired_unlocks_cannot_create_or_fire(self):
        with self.assertRaises(ValueError):
            alerts.validate(
                {
                    "p": "x",
                    "name": "unlock",
                    "type": "unlock",
                    "period": "event",
                    "threshold": 3,
                },
                ["x"],
            )
        runtime = {}
        self.assertEqual(
            alerts.evaluate(
                {"on": True, "type": "unlock"},
                runtime,
                None,
                [],
                int(time.time() * 1000),
            ),
            [],
        )
        self.assertEqual(runtime["status"], "paused")
        with tempfile.TemporaryDirectory() as t:
            store = pc.Store(Path(t) / "calendar.json")
            store.data.update(
                items=[{"kind": "unlock"}, {"kind": "funding"}],
                unlockLeads=[{"p": "x"}],
            )
            store.save()
            self.assertEqual(store.snapshot()["items"], [{"kind": "funding"}])
            self.assertNotIn("unlockLeads", store.snapshot())

    def test_manual_calendar_requires_timezone_and_source(self):
        with self.assertRaises(ValueError):
            pc.manual(
                {
                    "kind": "unlock",
                    "title": "T",
                    "date": "2026-10-01T10:00:00",
                    "url": "https://example.com",
                },
                "x",
            )
        with self.assertRaises(ValueError):
            pc.manual(
                {
                    "kind": "funding",
                    "title": "T",
                    "date": "2030-01-01T00:00:00Z",
                    "url": "https://example.com",
                },
                "x",
            )

    def test_feed_failure_preserves_cached_rows_and_backs_off(self):
        with tempfile.TemporaryDirectory() as t:
            store = ps.Store(Path(t) / "s.json")
            store.patch(
                "x",
                sources=[
                    {
                        "id": "s",
                        "url": "https://example.com/feed",
                        "enabled": True,
                        "label": "test",
                        "status": "ok",
                        "rows": [{"title": "old"}],
                    }
                ],
            )
            with patch.object(ps, "fetch", side_effect=TimeoutError()):
                self.assertEqual(store.collect({"id": "x"}, None), [])
            s = store.snapshot("x")["sources"][0]
            self.assertEqual(s["rows"][0]["title"], "old")
            self.assertEqual(s["status"], "error")
            self.assertGreater(s["retryAt"], time.time() * 1000)


if __name__ == "__main__":
    unittest.main()
