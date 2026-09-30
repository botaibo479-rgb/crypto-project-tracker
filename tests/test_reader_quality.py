import unittest
from crypto_tracker.core.news_quality import annotate, relevant
from crypto_tracker.core.reader_quality import presentation
from crypto_tracker.store.projects import match_fields
from crypto_tracker.core.alerts import evaluate, validate


class ReaderQualityTests(unittest.TestCase):
    def event(self, **values):
        return {
            "id": "news-000000000001",
            "p": "soon",
            "title": "",
            "summary": "SOON Network is building infrastructure for autonomous agents",
            "url": "https://x.com/soon/status/1",
            "channel": "x",
            "source": "X · @soon",
            "publishedAt": 1000,
            **values,
        }

    def test_social_noise_is_preserved_but_not_high(self):
        for text in [
            "@Kaiz_294 💙",
            "@SuccinctLabs🥳🥳",
            "较高",
            "RT @someone: new thing",
        ]:
            e = annotate(self.event(summary=text), 2000)
            self.assertTrue(e["lowInformation"])
            self.assertFalse(e["high"])
            self.assertEqual(e["summary"], text)

    def test_keyword_teaser_does_not_become_important(self):
        vague = annotate(
            self.event(summary="Buyback coming soon. Something big is coming!"), 2000
        )
        concrete = annotate(
            self.event(summary="SOON has completed buyback of $200 million tokens"),
            2000,
        )
        self.assertFalse(vague["high"])
        self.assertTrue(concrete["high"])
        self.assertGreater(concrete["qualityScore"], vague["qualityScore"])

    def test_cross_project_original_has_one_card_two_tags_and_evidence(self):
        a = annotate(self.event(), 2000)
        b = annotate(self.event(p="pha", id="news-000000000002"), 2000)
        result = presentation([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["projectIds"]), {"soon", "pha"})
        self.assertEqual(len(result[0]["crossProjectItems"]), 2)

    def test_distinct_originals_stay_separate_across_projects(self):
        a = self.event()
        b = self.event(p="pha", id="2", url="https://x.com/pha/status/2")
        self.assertEqual(len(presentation([a, b])), 2)

    def test_custom_matching_exclusions_take_precedence(self):
        p = {
            "name": "Example",
            "symbol": "EX",
            **match_fields(
                {
                    "aliases": "Unique Tool",
                    "contracts": "0x12345678",
                    "excludeTerms": "giveaway",
                }
            ),
        }
        self.assertTrue(relevant("custom-ex", "Unique Tool launches", p))
        self.assertTrue(relevant("custom-ex", "token 0x12345678", p))
        self.assertFalse(relevant("custom-ex", "Unique Tool giveaway", p))

    def test_ema200_is_separate_from_dual_average_rule(self):
        now = 100000000
        rule = {
            "id": "r",
            "p": "soon",
            "type": "ema200",
            "name": "EMA200",
            "period": "4h",
            "threshold": 5,
            "cooldownMinutes": 1,
            "on": True,
            "createdAt": now - 1000,
        }
        self.assertEqual(validate(rule, ["soon"])["type"], "ema200")
        market = {
            "period": "4h",
            "candles": [{"close": 99}, {"close": 102}],
            "previousEma200": 100,
            "ema200": 101,
            "ema360": 110,
            "close4h": 102,
            "candleAt": now,
            "cross": None,
        }
        self.assertEqual(len(evaluate(rule, {}, market, [], now)), 1)
        market.pop("previousEma200")
        self.assertEqual(evaluate(rule, {}, market, [], now), [])

    def test_listing_template_filters_deposit_changes(self):
        base = dict(
            id="r",
            p="soon",
            type="listing",
            name="listing",
            period="event",
            threshold=0,
            cooldownMinutes=1,
            on=True,
            createdAt=100001000,
            listingScope="listing",
        )
        event = dict(
            id="a",
            p="soon",
            providerKind="listing",
            listingType="充提调整",
            publishedAt=100002000,
            title="Deposit suspended",
        )
        self.assertEqual(evaluate(base, {}, {}, [event], 100003000), [])
        self.assertEqual(
            len(evaluate(base, {}, {}, [{**event, "listingType": "下架"}], 100003000)),
            1,
        )

    def test_batch_templates_validate_all_before_mutation(self):
        import tempfile
        from pathlib import Path
        from crypto_tracker.core.alerts import Store

        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "alerts.json")
            payload = dict(
                projectIds=["soon", "unknown"],
                type="listing",
                name="公告",
                period="event",
                threshold=0,
            )
            with self.assertRaises(ValueError):
                store.batch(payload, ["soon", "near"])
            self.assertEqual(store.snapshot()["rules"], [])
            result = store.batch(
                {**payload, "projectIds": ["soon", "near"]}, ["soon", "near"]
            )
            self.assertEqual(len(result), 2)

    def test_short_concrete_launch_is_not_folded_as_chatter(self):
        event = annotate(self.event(summary="Mainnet is live"), 2000)
        self.assertFalse(event["lowInformation"])
        self.assertGreaterEqual(event["qualityScore"], 40)
