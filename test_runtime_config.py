import unittest
from unittest.mock import patch
import runtime_config as config

class HostingBoundaryTests(unittest.TestCase):
    def test_local_origin_is_exact(self):
        with patch.object(config, 'PUBLIC_HOST', None), patch.object(config, 'PORT', 4317):
            self.assertTrue(config.allowed_write('127.0.0.1:4317', 'http://127.0.0.1:4317', 'application/json'))
            self.assertFalse(config.allowed_write('127.0.0.1:4317', 'https://evil.example', 'application/json'))
            self.assertFalse(config.allowed_read('127.0.0.1.evil.example:4317'))
            self.assertFalse(config.allowed_read('127.0.0.1:80'))

    def test_https_proxy_origin_and_content_type(self):
        with patch.object(config, 'PUBLIC_HOST', 'signal.example.com'), patch.object(config, 'PUBLIC_ORIGIN', 'https://signal.example.com'):
            self.assertTrue(config.allowed_write('signal.example.com', 'https://signal.example.com', 'application/json; charset=utf-8'))
            self.assertFalse(config.allowed_write('signal.example.com', 'http://signal.example.com', 'application/json'))
            self.assertFalse(config.allowed_write('signal.example.com', 'https://signal.example.com', 'text/plain'))
            self.assertFalse(config.allowed_write('signal.example.com', '', 'application/json'))

    def test_public_origin_rejects_unsafe_or_ambiguous_values(self):
        for origin in ['http://signal.example.com', 'https://user:pass@example.com', 'https://example.com/path', 'https://example.com?q=1', 'https://example.com#hash']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                config.validate_origin(origin)
        self.assertEqual(config.validate_origin('https://signal.example.com'), 'signal.example.com')

if __name__ == '__main__':
    unittest.main()
