import unittest
from unittest.mock import patch
import server


class MarketTests(unittest.TestCase):
    def test_ema_seed_and_recurrence(self):
        self.assertEqual(server.ema([1, 2], 3), [])
        self.assertEqual(server.ema([1, 2, 3, 4], 3), [None, None, 2, 3])

    def test_closed_candles_and_oi_window(self):
        clock = 2_000_000_000_000
        candles = [
            [
                clock - (400 - i) * 14400000,
                0,
                0,
                0,
                str(10 + i / 100),
                0,
                clock - (399 - i) * 14400000 - 1,
            ]
            for i in range(400)
        ]
        candles.append([clock, 0, 0, 0, "999999", 0, clock + 14400000])

        def api(path, params):
            if "ticker" in path:
                return {
                    "lastPrice": "14",
                    "priceChangePercent": "2",
                    "quoteVolume": "100",
                    "closeTime": clock,
                }
            if "klines" in path:
                return candles
            return [
                {"timestamp": clock - 3600000, "sumOpenInterest": "100"},
                {"timestamp": clock, "sumOpenInterest": "110"},
            ]

        with (
            patch("server.api", side_effect=api),
            patch("server.now", return_value=clock),
        ):
            _, m = server.market(server.PROJECTS[0])
        self.assertEqual(m["klineCount"], 400)
        self.assertLess(m["ema200"], 14)
        self.assertAlmostEqual(m["oiChange1h"], 10)
        self.assertEqual(m["close4h"], 13.99)

    def test_short_oi_window_is_not_one_hour(self):
        clock = 2_000_000_000_000

        def api(path, params):
            if "ticker" in path:
                raise TimeoutError()
            if "klines" in path:
                return []
            return [
                {"timestamp": clock - 300000, "sumOpenInterest": "100"},
                {"timestamp": clock, "sumOpenInterest": "110"},
            ]

        with patch("server.api", side_effect=api):
            _, m = server.market(server.PROJECTS[0])
        self.assertNotIn("oiChange1h", m)
        self.assertIn("oiWindow", m["errors"])
        self.assertNotIn("price", m)

    def test_missing_token_is_explicit(self):
        with patch("server.TOKEN", ""):
            events, status = server.provider_news(server.PROJECTS[0])
        self.assertEqual(events, [])
        self.assertEqual(status["OpenTwitter"]["status"], "missing_credential")

    def test_public_source_success_status(self):
        row = {"id": "real", "p": "near", "title": "Official title"}
        with patch("server.TOKEN", ""), patch("server.public_news", return_value=[row]):
            pid, items, status = server.refresh_news(server.PROJECTS[1])
        self.assertEqual(pid, "near")
        self.assertEqual(items, [row])
        self.assertEqual(status["官网资讯"]["status"], "ok")
        self.assertEqual(status["官网资讯"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
