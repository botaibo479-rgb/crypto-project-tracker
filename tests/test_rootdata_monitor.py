import unittest
from crypto_tracker.sources.rootdata import (
    members,
    refresh,
    member_account,
    resolve_candidates,
    validate_source,
)

URL = "https://www.rootdata.com/projects/detail/Test?k=abc"
HTML = '<h2>Team</h2><a href="/member/Alice?k=1">Alice CEO</a><div role="tabpanel" data-state="inactive"><a href="/member/Former?k=2">Former</a></div><h2>Related People</h2><a href="/member/Investor?k=3">Investor</a>'


class RootDataTests(unittest.TestCase):
    def test_project_source_requires_matching_official_handle(self):
        p = {"account": "NEARProtocol"}
        self.assertEqual(
            validate_source(
                p, URL, lambda url: '<a href="https://x.com/NEARProtocol">X</a>'
            ),
            URL,
        )
        for html in [
            '<a href="https://x.com/other">X</a>',
            '<a href="https://x.com/NEARProtocol/status/1">X</a>',
        ]:
            with self.assertRaises(ValueError):
                validate_source(p, URL, lambda url: html)

    def test_source_rejects_other_hosts_before_fetch(self):
        def unexpected(url):
            self.fail("Invalid source must not be fetched")

        for url in [
            "https://example.com/projects/detail/foo",
            "https://www.rootdata.com.evil.example/projects/detail/foo",
            "http://www.rootdata.com/projects/detail/foo",
            "https://user:pass@www.rootdata.com/projects/detail/foo",
        ]:
            with self.assertRaises(ValueError):
                validate_source({"account": "near"}, url, unexpected)

    def test_member_requires_matching_name_and_single_profile_link(self):
        person = {"name": "Alice", "url": "https://www.rootdata.com/member/Alice?k=1"}
        self.assertEqual(
            member_account(person, '<h1>Alice</h1><a href="https://x.com/alice">X</a>'),
            "alice",
        )
        for html in [
            '<h1>Bob</h1><a href="https://x.com/alice">X</a>',
            '<h1>Alice</h1><a href="https://x.com/alice/status/123">X</a>',
            '<h1>Alice</h1><a href="https://x.com/alice">X</a><a href="https://x.com/bob">X</a>',
        ]:
            with self.assertRaises(ValueError):
                member_account(person, html)

    def test_resolution_keeps_unresolved_people_and_source_evidence(self):
        observation = {
            "status": "ok",
            "source": URL,
            "candidates": [
                {"name": "Alice", "url": "https://www.rootdata.com/member/Alice?k=1"},
                {"name": "Bob", "url": "https://www.rootdata.com/member/Bob?k=2"},
            ],
        }

        def request(url):
            return (
                '<h1>Alice</h1><a href="https://x.com/alice">X</a>'
                if "Alice" in url
                else "<h1>Bob</h1>"
            )

        result, added = resolve_candidates({"team": []}, observation, request, 200)
        self.assertEqual([p["name"] for p in result["candidates"]], ["Bob"])
        self.assertEqual(added[0]["account"], "alice")
        self.assertEqual(added[0]["projectEvidence"], URL)
        self.assertEqual(len(observation["candidates"]), 2)

    def test_only_public_team_section_and_active_panel(self):
        self.assertEqual([x["name"] for x in members(HTML, URL)], ["Alice"])

    def test_missing_section_does_not_clear_previous_observation(self):
        p = {
            "teamSourceUrl": URL,
            "rootdataObservation": {"checkedAt": 100, "members": [{"key": "1"}]},
        }
        result = refresh(p, lambda url: "<h2>Fundraising</h2>", 200)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["checkedAt"], 100)
        self.assertEqual(result["members"], [{"key": "1"}])

    def test_candidates_do_not_mutate_team_or_infer_departures(self):
        p = {
            "teamSourceUrl": URL,
            "team": [
                {
                    "account": "old",
                    "evidence": "https://www.rootdata.com/member/Old?k=9",
                }
            ],
        }
        result = refresh(p, lambda url: HTML, 200)
        self.assertEqual(result["candidates"][0]["name"], "Alice")
        self.assertEqual(p["team"][0]["account"], "old")
        self.assertEqual(result["notVisibleCount"], 1)

    def test_empty_team_is_not_proof_everyone_left(self):
        with self.assertRaises(ValueError):
            members("<h2>Team</h2><h2>News</h2>", URL)


if __name__ == "__main__":
    unittest.main()
