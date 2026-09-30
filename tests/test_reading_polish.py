import unittest
from crypto_tracker.core import reading_text, alerts


class ReadingPolishTests(unittest.TestCase):
    def test_terms_and_original_are_separate(self):
        text = "Open interest rises as funding rate increases"
        self.assertEqual(
            reading_text.standard_terms(text),
            "持仓量（OI） rises as 资金费率 increases",
        )
        self.assertTrue(text.startswith("Open interest"))

    def test_alert_preserves_source_and_rule_snapshot(self):
        now = 1800000000000
        rule = dict(
            id="r",
            p="near",
            type="price",
            name="test",
            period="24h",
            threshold=5,
            cooldownMinutes=60,
            on=True,
            createdAt=now - 1000,
        )
        result = alerts.evaluate(
            rule,
            {"condition": False},
            {"change24h": 6, "priceAt": now, "source": "Binance", "symbol": "NEARUSDT"},
            [],
            now,
        )[0]
        self.assertEqual(result["evidence"]["source"], "Binance")
        self.assertEqual(result["evidence"]["threshold"], 5)
        rule["threshold"] = 10
        self.assertEqual(result["ruleSnapshot"]["threshold"], 5)
