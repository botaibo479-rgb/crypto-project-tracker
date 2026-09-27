import json
import unittest
import urllib.parse
import urllib.error
import hashlib
from unittest.mock import patch
import features
from reading_text import readable, chunks, translation_version

class ReadingTextTests(unittest.TestCase):
    def test_legacy_cache_requires_all_current_protected_identifiers(self):
        source='Visit near.com with NEAR Intents.<br/>Today'
        key=hashlib.sha256(('v2:'+source).encode()).hexdigest()
        with patch.object(features,'TRANSLATIONS',{key:'访问 near.com 和 NEAR Intents。<br/>今天'}):
            self.assertEqual(features.translated(source),'访问 near.com 和 NEAR Intents。\n今天')
            features.translate_one(source,lambda url:self.fail('Valid legacy cache must avoid network'))
        for bad in ['访问 近.com 和 NEAR 意图。','访问 near.com 和 NEAR 意图。','ZXQKEEP0QXZ']:
            with patch.object(features,'TRANSLATIONS',{key:bad}):self.assertIsNone(features.translated(source))

    def test_rate_limit_pauses_other_translation_requests(self):
        def limited(url):
            raise urllib.error.HTTPError(url,429,'Too Many Requests',{'Retry-After':'600'},None)
        with patch.object(features,'TRANSLATION_PAUSE_UNTIL',0), patch.object(features,'TRANSLATIONS',{}), patch.object(features,'RETRY',{}):
            features.translate_one('Fresh example one',limited)
            self.assertEqual(features.translation_status()['status'],'rate_limited')
            def unexpected(url):self.fail('Global cooldown must suppress later calls')
            features.translate_one('Fresh example two',unexpected)

    def test_hidden_characters_cannot_disguise_placeholders(self):
        self.assertEqual(readable('near.\u200bcom'), 'near.com')
        original='A different public test text'
        with patch.object(features,'TRANSLATIONS',{features.digest(original):'ZX\u200b\u200bQKEEP0QXZ'}):
            self.assertIsNone(features.translated(original))

    def test_markup_is_removed_without_losing_comparisons(self):
        self.assertEqual(readable('中文<br/><br/>更新 &amp; 公告'), '中文\n\n更新 & 公告')
        self.assertEqual(readable('OI < 5 and price > 10'), 'OI < 5 and price > 10')
        self.assertEqual(readable('<p>News<script>secret()</script></p>'), 'News')

    def test_protection_keeps_bare_domains_and_product_names(self):
        original = 'Brave Leo uses NEAR Intents.<br/>Visit near.com and trade $ARB.'
        def translate(url):
            source = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['q'][0]
            self.assertNotIn('<br', source)
            self.assertNotIn('Brave', source)
            self.assertNotIn('near.com', source)
            return json.dumps([[[source.replace('uses','使用').replace('Visit','访问'), '']]])
        features.TRANSLATIONS.pop(features.digest(original), None)
        features.RETRY.pop(features.digest(original), None)
        features.translate_one(original, translate)
        result = features.translated(original)
        self.assertIn('Brave Leo 使用 NEAR Intents', result)
        self.assertIn('near.com', result)
        self.assertIn('$ARB', result)
        self.assertNotIn('<br', result)
        localized = features.localize({'summary':original, 'title':'中文标题'})
        self.assertEqual(localized['summary'], original)

    def test_only_affected_cache_entries_change_version(self):
        self.assertEqual(translation_version('SOON partners with NEAR'), 'v2:')
        self.assertEqual(translation_version('visit near.com'), 'v3:')

    def test_long_text_does_not_split_protected_identifier(self):
        source = 'x'*2197 + 'ZXQKEEP0QXZ' + ' tail'
        parts = list(chunks(source))
        self.assertEqual(''.join(parts), source)
        self.assertTrue(any('ZXQKEEP0QXZ' in p for p in parts))

if __name__ == '__main__': unittest.main()
