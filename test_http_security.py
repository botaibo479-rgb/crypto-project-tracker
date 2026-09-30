import io
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import http_clients
import public_sources
import server


def serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class RedirectTests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        seen = self.seen

        class Sink(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.sink = serve(Sink)
        target = "http://127.0.0.1:%d/collect" % self.sink.server_port

        class Bounce(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.bounce = serve(Bounce)
        self.url = "http://127.0.0.1:%d/" % self.bounce.server_port

    def tearDown(self):
        for httpd in (self.sink, self.bounce):
            httpd.shutdown()
            httpd.server_close()

    def open(self, *handlers):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), *handlers)
        request = urllib.request.Request(
            self.url, headers={"Authorization": "Bearer t"}
        )
        with opener.open(request, timeout=5) as response:
            return response.read()

    def test_stdlib_default_forwards_authorization_on_redirect(self):
        # Documents finding S1: the reason authenticated calls must not follow redirects.
        self.open()
        self.assertEqual(self.seen, ["Bearer t"])

    def test_authenticated_opener_refuses_redirect(self):
        with self.assertRaises(http_clients.RedirectRefused):
            self.open(http_clients._NoRedirect)
        self.assertEqual(self.seen, [])


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class DirectClientTests(unittest.TestCase):
    def capture(self):
        sent = []

        def open_(request, timeout):
            sent.append(request)
            return FakeResponse(b'{"ok": true}')

        return sent, patch.object(http_clients._OPENER, "open", side_effect=open_)

    def test_rejects_hosts_schemes_ports_and_userinfo(self):
        for url in [
            "http://ai.6551.io/open/news_search",
            "https://evil.example/open/news_search",
            "https://ai.6551.io.evil.example/x",
            "https://user:pass@ai.6551.io/x",
            "https://ai.6551.io:8443/x",
            "https://translate.googleapis.com/translate_a/single",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                http_clients.direct(url, token="t")

    def test_token_only_sent_to_provider_host(self):
        sent, patcher = self.capture()
        with patcher:
            http_clients.direct(
                "https://fapi.binance.com/fapi/v1/ticker/24hr", token="t"
            )
            http_clients.direct(
                "https://ai.6551.io/open/news_search", {"q": 1}, token="t"
            )
        self.assertIsNone(sent[0].get_header("Authorization"))
        self.assertEqual(sent[1].get_header("Authorization"), "Bearer t")

    def test_missing_token_never_calls_provider(self):
        sent, patcher = self.capture()
        with patcher, self.assertRaises(ValueError):
            http_clients.direct("https://ai.6551.io/open/news_search", {}, token="")
        self.assertEqual(sent, [])

    def test_authorization_errors_are_not_retried(self):
        calls = []

        def unauthorized(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)

        with patch.object(http_clients._OPENER, "open", side_effect=unauthorized):
            with self.assertRaises(urllib.error.HTTPError):
                http_clients.direct("https://ai.6551.io/open/x", {}, token="t")
        self.assertEqual(len(calls), 1)


class DispatcherTests(unittest.TestCase):
    def test_routes_by_host_and_refuses_public_post(self):
        with (
            patch.object(server, "TOKEN", "t"),
            patch("http_clients.direct", return_value="{}") as direct,
            patch("http_clients.public_text", return_value="<html>") as public,
        ):
            server.request("https://ai.6551.io/open/news_search", {"q": 1})
            self.assertEqual(direct.call_args.kwargs["token"], "t")
            server.request("https://www.rootdata.com/projects/detail/X?k=1")
            public.assert_called_once()
            with self.assertRaises(ValueError):
                server.request("https://www.rootdata.com/x", {"q": 1})

    def test_official_feed_rejects_entity_declarations(self):
        feed = (
            '<!DOCTYPE x [<!ENTITY a "b">]><feed xmlns="http://www.w3.org/2005/Atom"/>'
        )
        with patch.object(server, "request", return_value=feed):
            with self.assertRaises(ValueError):
                server.public_news({"id": "pha"})


class FakeConnection:
    routes = {}

    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, headers=None):
        self.response = self.routes[self.host]

    def getresponse(self):
        return self.response

    def close(self):
        pass


class FakeHTTPResponse:
    def __init__(self, status, location="", body=b"ok"):
        self.status = status
        self.location = location
        self.body = body
        self.headers = self

    def getheader(self, name, default=None):
        return self.location if name == "Location" and self.location else default

    def get_content_charset(self):
        return "utf-8"

    def read(self, size):
        return self.body[:size]


class PublicFetchTests(unittest.TestCase):
    def test_same_site_blocks_cross_site_redirect(self):
        FakeConnection.routes = {
            "www.rootdata.com": FakeHTTPResponse(302, "https://attacker.example/x"),
            "attacker.example": FakeHTTPResponse(200),
        }
        with patch.object(public_sources, "PublicHTTPS", FakeConnection):
            with self.assertRaises(ValueError):
                public_sources.fetch("https://www.rootdata.com/a", same_site=True)
            self.assertEqual(
                public_sources.fetch("https://www.rootdata.com/a")[0], "ok"
            )

    def test_same_site_allows_subdomain_redirect(self):
        FakeConnection.routes = {
            "near.org": FakeHTTPResponse(301, "https://www.near.org/blog"),
            "www.near.org": FakeHTTPResponse(200, body=b"blog"),
        }
        with patch.object(public_sources, "PublicHTTPS", FakeConnection):
            self.assertEqual(
                public_sources.fetch("https://near.org/", same_site=True)[0], "blog"
            )

    def test_size_limit(self):
        FakeConnection.routes = {"a.example": FakeHTTPResponse(200, body=b"x" * 11)}
        with patch.object(public_sources, "PublicHTTPS", FakeConnection):
            with self.assertRaises(ValueError):
                public_sources.fetch("https://a.example/", max_bytes=10)

    def test_private_literals_rejected(self):
        for url in [
            "https://127.0.0.1/",
            "https://[::1]/",
            "https://[fc00::1]/",
            "https://[fe80::1]/",
            "https://169.254.169.254/",
            "https://localhost/",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_sources.public_url(url)

    def test_doh_fallback_is_opt_in(self):
        synthetic = [(2, 1, 6, "", ("198.18.0.7", 443))]
        connection = public_sources.PublicHTTPS("example.org", timeout=1)
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("socket.getaddrinfo", return_value=synthetic),
            patch("urllib.request.urlopen") as urlopen,
        ):
            with self.assertRaises(ValueError):
                connection.connect()
            urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
