import unittest, json, time
import features


class FeaturesTests(unittest.TestCase):
    def test_follower_threshold(self):
        for count in [None, 0, 19999, "unknown"]:
            self.assertFalse(features.eligible_discussant({"followers": count}))
        for count in [20000, 25000, "30000"]:
            self.assertTrue(features.eligible_discussant({"followers": count}))

    def test_manual_validation(self):
        p = features.prepare_project(
            {
                "name": "Arbitrum",
                "symbol": "arb",
                "account": "@arbitrum",
                "website": "https://arbitrum.io",
            },
            None,
        )
        self.assertEqual(p["symbol"], "ARB")
        self.assertEqual(p["account"], "arbitrum")
        for payload in [
            {"name": "<script>", "symbol": "X"},
            {"name": "Test", "symbol": "X", "website": "javascript:alert(1)"},
            {"name": "Test", "symbol": "X", "account": "bad/name"},
        ]:
            with self.assertRaises(ValueError):
                features.prepare_project(payload, None)

    def test_confirmation_keeps_selected_identity_and_user_corrections(self):
        prepared = features.prepare_project(
            {"coinId": "sample-token"},
            lambda url: json.dumps(
                {
                    "name": "Old name",
                    "symbol": "old",
                    "links": {
                        "homepage": ["https://old.example"],
                        "twitter_screen_name": "old",
                    },
                }
            ),
        )
        self.assertEqual(prepared["coinId"], "sample-token")
        confirmed = features.confirm_project(
            {
                **prepared,
                "name": "Corrected name",
                "symbol": "NEW",
                "website": "https://new.example",
                "account": "@new",
            }
        )
        self.assertEqual(confirmed["id"], "sample-token")
        self.assertEqual(confirmed["name"], "Corrected name")
        self.assertEqual(confirmed["symbol"], "NEW")
        self.assertEqual(confirmed["website"], "https://new.example")
        self.assertEqual(confirmed["account"], "new")
        self.assertIn("尚未独立核实", confirmed["identity"])

    def test_confirmation_validates_manual_and_source_id(self):
        self.assertEqual(
            features.confirm_project({"name": "Manual", "symbol": "MAN"})["id"],
            "custom-man",
        )
        for coin in ["../../bad", "https://example.com", "<script>"]:
            with self.assertRaises(ValueError):
                features.confirm_project(
                    {"coinId": coin, "name": "Test", "symbol": "T"}
                )

    def test_discovery_rejects_stale_and_unrelated(self):
        now = int(time.time() * 1000)
        rows = [
            {
                "userScreenName": "alice",
                "userFollowers": 25000,
                "id": "123",
                "createdAt": now,
                "text": "Hello @arbitrum",
            },
            {
                "userScreenName": "bob",
                "id": "124",
                "createdAt": now - 9 * 86400000,
                "text": "@arbitrum",
            },
            {
                "userScreenName": "eve",
                "id": "125",
                "createdAt": now,
                "text": "unrelated",
            },
        ]
        r = features.discover(
            {"name": "Arbitrum", "symbol": "ARB", "account": "arbitrum"},
            lambda *a: json.dumps({"data": rows}),
            lambda s: s,
        )
        self.assertEqual([a["account"] for a in r["discussants"]], ["alice"])


if __name__ == "__main__":
    unittest.main()
