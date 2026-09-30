import unittest
import features
from reading_text import readable, chunks, translation_version


class ReadingTextTests(unittest.TestCase):
    def test_hidden_characters_cannot_disguise_placeholders(self):
        self.assertEqual(readable("near.\u200bcom"), "near.com")
        # Untranslated English text is shown as the original, never as a placeholder.
        self.assertIsNone(features.translated("A different public test text"))

    def test_markup_is_removed_without_losing_comparisons(self):
        self.assertEqual(
            readable("中文<br/><br/>更新 &amp; 公告"), "中文\n\n更新 & 公告"
        )
        self.assertEqual(readable("OI < 5 and price > 10"), "OI < 5 and price > 10")
        self.assertEqual(readable("<p>News<script>secret()</script></p>"), "News")

    def test_only_affected_cache_entries_change_version(self):
        self.assertEqual(translation_version("SOON partners with NEAR"), "v2:")
        self.assertEqual(translation_version("visit near.com"), "v3:")

    def test_long_text_does_not_split_protected_identifier(self):
        source = "x" * 2197 + "ZXQKEEP0QXZ" + " tail"
        parts = list(chunks(source))
        self.assertEqual("".join(parts), source)
        self.assertTrue(any("ZXQKEEP0QXZ" in p for p in parts))


if __name__ == "__main__":
    unittest.main()
