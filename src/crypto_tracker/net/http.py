"""Outbound HTTP policy. Every request leaves through one of these paths.

* ``direct``: JSON APIs on a fixed host allowlist. Redirects are refused, so an
  ``Authorization`` header can never follow a 3xx to another host or to http.
  The bearer token is attached only for ``ai.6551.io``.
* ``public_text``: public web pages (RootData, official sites) through the
  SSRF-safe ``safe_fetch.fetch`` (public IPs only, pinned, every hop
  validated), restricted to redirects within the same site.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from crypto_tracker.net import safe_fetch

USER_AGENT = "SignalReader/0.4"
AUTH_HOST = "ai.6551.io"
DIRECT_HOSTS = frozenset({AUTH_HOST, "fapi.binance.com", "api.coingecko.com"})
MAX_BYTES = 6_000_000
RETRY_CODES = (502, 503, 504)


class RedirectRefused(ValueError):
    """A direct API answered with a redirect; it is never followed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectRefused("redirect_refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


def direct_url(url):
    u = urllib.parse.urlsplit(url)
    if (
        u.scheme != "https"
        or u.hostname not in DIRECT_HOSTS
        or u.port not in (None, 443)
        or u.username
        or u.password
    ):
        raise ValueError("host_not_allowed")
    return u


def direct(url, payload=None, *, token="", timeout=18, attempts=2):
    """GET (or POST JSON) an allowlisted API and return the decoded body."""
    u = direct_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if u.hostname == AUTH_HOST:
        if not token:
            raise ValueError("missing_credential")
        headers["Authorization"] = "Bearer " + token
    raw = json.dumps(payload).encode() if payload is not None else None
    if raw:
        headers["Content-Type"] = "application/json"
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=raw, headers=headers)
            with _OPENER.open(request, timeout=timeout) as response:
                return response.read(MAX_BYTES).decode("utf-8")
        except urllib.error.HTTPError as e:
            # Authorization failures are final; only retry temporary failures.
            if attempt + 1 >= attempts or e.code not in RETRY_CODES:
                raise
            time.sleep(1)
        except (TimeoutError, urllib.error.URLError):
            if attempt + 1 >= attempts:
                raise
            time.sleep(1)


def error_label(e):
    """Map an exception to a fixed label; never expose raw provider bodies."""
    if isinstance(e, urllib.error.HTTPError):
        return "HTTP " + str(e.code)
    return {
        "TimeoutError": "连接超时",
        "URLError": "网络连接失败",
        "ValueError": "数据不可用",
        "RedirectRefused": "数据不可用",
    }.get(type(e).__name__, "数据读取失败")


CALENDAR_URL = "https://ai.6551.io/open/finance-enhance/key-market-events"


class Requester:
    """``request(url, payload=None) -> str``: the single outbound chokepoint.

    The token lives only on this object inside the collector process.
    """

    def __init__(self, token=""):
        self._token = token

    @property
    def has_token(self):
        return bool(self._token)

    def __repr__(self):
        return "Requester(token=%s)" % ("set" if self._token else "unset")

    def __call__(self, url, payload=None):
        if urllib.parse.urlsplit(url).hostname in DIRECT_HOSTS:
            calendar_query = url == CALENDAR_URL
            return direct(
                url,
                payload,
                token=self._token,
                timeout=35 if calendar_query else 18,
                attempts=1 if calendar_query else 2,
            )
        if payload is not None:
            raise ValueError("post_not_allowed")
        return public_text(url)


def public_text(url):
    """Fetch a public page; redirects may only stay on the same site."""
    text, _, _, _ = safe_fetch.fetch(url, same_site=True, max_bytes=MAX_BYTES)
    return text
