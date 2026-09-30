"""Outbound HTTP policy. Every request leaves through one of these paths.

* ``direct``: JSON APIs on a fixed host allowlist. Redirects are refused, so an
  ``Authorization`` header can never follow a 3xx to another host or to http.
  The bearer token is attached only for ``ai.6551.io``.
* ``public_text``: public web pages (RootData, official sites) through the
  SSRF-safe ``public_sources.fetch`` (public IPs only, pinned, every hop
  validated), restricted to redirects within the same site.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import public_sources

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


def public_text(url):
    """Fetch a public page; redirects may only stay on the same site."""
    text, _, _, _ = public_sources.fetch(url, same_site=True, max_bytes=MAX_BYTES)
    return text
