import unittest
from crypto_tracker.core.discussion_quality import (
    observation,
    quality,
    rank,
    is_retweet,
    mark_shared_text,
)


class DiscussionQualityTests(unittest.TestCase):
    def test_duplicate_posts_do_not_inflate_continuity(self):
        a = observation({"id": "1", "text": "Protocol analysis"}, 86400000)
        q = quality([a, a])
        self.assertEqual(q["samplePosts"], 1)
        self.assertEqual(q["activeDays"], 1)

    def test_reply_quote_and_promotion_are_distinct(self):
        rows = [
            observation({"id": "1", "text": "@near reply"}, 0),
            observation({"id": "2", "text": "Analysis", "isQuote": True}, 0),
            observation({"id": "3", "text": "Airdrop referral"}, 0),
        ]
        q = quality(rows)
        self.assertEqual(q["standalonePosts"], 1)
        self.assertEqual(q["promotionalPosts"], 1)
        self.assertTrue(is_retweet({"text": "RT @near news"}))

    def test_reposted_long_text_does_not_inflate_days(self):
        text = (
            "A detailed protocol discussion with specific implementation observations. "
            * 3
        )
        rows = [
            observation(
                {"id": str(i), "text": text + " https://example.com/" + str(i)},
                i * 86400000,
            )
            for i in range(3)
        ]
        q = quality(rows)
        self.assertEqual(q["activeDays"], 1)
        self.assertEqual(q["repeatedPosts"], 2)
        self.assertEqual(q["standalonePosts"], 1)

    def test_cross_author_same_text_is_not_attributed_to_an_original_author(self):
        text = (
            "A detailed protocol discussion with specific implementation observations. "
            * 3
        )
        corpus = {
            name: [observation({"id": name, "text": text}, 0)]
            for name in ["alice", "bob"]
        }
        mark_shared_text(corpus)
        for rows in corpus.values():
            self.assertEqual(quality(rows)["sharedTextPosts"], 1)
            self.assertEqual(quality(rows)["standalonePosts"], 0)
        short = {
            name: [observation({"id": name, "text": "NEAR update"}, 0)]
            for name in ["alice", "bob"]
        }
        mark_shared_text(short)
        self.assertEqual(quality(short["alice"])["sharedTextPosts"], 0)

    def test_continuing_discussion_ranks_before_new_promotion(self):
        sustained = quality(
            [
                observation({"id": str(i), "text": "Technical analysis"}, i * 86400000)
                for i in range(3)
            ]
        )
        promotion = quality(
            [observation({"id": "9", "text": "Giveaway promo code"}, 4 * 86400000)]
        )
        accounts = [
            {"account": "promo", "quality": promotion, "publishedAt": 4 * 86400000},
            {"account": "analysis", "quality": sustained, "publishedAt": 2 * 86400000},
        ]
        self.assertEqual(rank(accounts)[0]["account"], "analysis")


if __name__ == "__main__":
    unittest.main()
