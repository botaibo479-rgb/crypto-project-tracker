import unittest, json, time
from team_news import collect, project_related
from server import news_event, timestamp


class TeamTests(unittest.TestCase):
    def test_relevance_does_not_accept_ambiguous_names(self):
        p = {"id": "soon", "name": "SOON", "symbol": "SOON", "account": "soon_svm"}
        self.assertFalse(project_related(p, "coming soon"))
        self.assertTrue(project_related(p, "We shipped at @soon_svm"))

    def test_filters_author_date_relevance_and_retweets(self):
        p = {
            "id": "near",
            "name": "NEAR Protocol",
            "symbol": "NEAR",
            "account": "NEARProtocol",
            "team": [
                {
                    "account": "alice",
                    "identity": "RootData 收录",
                    "role": "工程师",
                    "evidence": "https://example.org",
                }
            ],
        }
        now = int(time.time() * 1000)
        base = {
            "userScreenName": "alice",
            "id": "1",
            "text": "NEAR Protocol upgrade",
            "createdAt": now,
        }
        rows = [
            base,
            {**base, "id": "2", "text": "my breakfast"},
            {**base, "id": "3", "userScreenName": "bob"},
            {**base, "id": "4", "createdAt": now - 31 * 86400000},
            {**base, "id": "5", "text": "RT @NEARProtocol upgrade"},
        ]
        events, status = collect(
            p, lambda *args: json.dumps({"data": rows}), timestamp, news_event
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["channel"], "team")
        self.assertEqual(status["accounts"][0]["count"], 1)

    def test_unverified_accounts_not_collected_and_failures_exposed(self):
        p = {
            "id": "near",
            "name": "NEAR Protocol",
            "symbol": "NEAR",
            "account": "NEARProtocol",
            "team": [
                {"account": "alice", "identity": "待核实"},
                {"account": "bob", "identity": "RootData 收录"},
            ],
        }
        calls = []

        def request(url, payload):
            calls.append(payload["username"])
            raise ValueError("failure")

        events, status = collect(p, request, timestamp, news_event)
        self.assertEqual(calls, ["bob"])
        self.assertEqual(events, [])
        self.assertEqual(status["status"], "error")


if __name__ == "__main__":
    unittest.main()
