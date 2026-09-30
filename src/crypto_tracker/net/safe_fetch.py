"""SSRF-safe public HTTPS fetching: public IPs only, pinned per connection, every
redirect re-validated, bounded size, no credentials ever forwarded."""

import http.client
import ipaddress
import json
import os
import re
import socket
import urllib.parse
import urllib.request


def public_url(url):
    u = urllib.parse.urlsplit(str(url))
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.port not in (None, 443)
    ):
        raise ValueError("仅支持公开 HTTPS 地址，不接受账号密码或非标准端口")
    if u.hostname.lower() in {
        "localhost",
        "metadata.google.internal",
    } or u.hostname.lower().endswith((".local", ".localhost")):
        raise ValueError("不能访问本地网络")
    try:
        literal = ipaddress.ip_address(u.hostname)
    except ValueError:
        literal = None
        if re.fullmatch(r"[0-9.:]+", u.hostname):
            raise ValueError("不能访问本地网络")
    if literal is not None and not literal.is_global:
        raise ValueError("不能访问本地网络")
    return urllib.parse.urlunsplit(("https", u.netloc, u.path or "/", u.query, ""))


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        # Some desktop proxies return RFC 2544 synthetic addresses. Only when explicitly
        # enabled, resolve that range through dns.google (which then sees the hostname),
        # and still connect only to a public IP.
        synthetic = ipaddress.ip_network("198.18.0.0/15")
        if addresses and all(
            ipaddress.ip_address(a[4][0]) in synthetic for a in addresses
        ):
            if os.environ.get("TRACKER_ALLOW_DOH") != "1":
                raise ValueError(
                    "合成 DNS 地址；如需经 dns.google 解析请设置 TRACKER_ALLOW_DOH=1"
                )
            q = urllib.parse.urlencode(
                {"name": self.host, "type": "A", "edns_client_subnet": "0.0.0.0/0"}
            )
            with urllib.request.urlopen(
                "https://dns.google/resolve?" + q, timeout=8
            ) as r:
                answer = json.loads(r.read(65536))
            ips = [a["data"] for a in answer.get("Answer", []) if a.get("type") == 1]
            addresses = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443)) for ip in ips
            ]
        if not addresses or any(
            not ipaddress.ip_address(a[4][0]).is_global for a in addresses
        ):
            raise ValueError("不能访问私有地址")
        self.sock = socket.create_connection((addresses[0][4][0], 443), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def site(host):
    return ".".join(host.lower().rstrip(".").split(".")[-2:])


def fetch(url, headers=None, *, same_site=False, max_bytes=2_000_000):
    # Pin the validated destination address; validate every redirect. Never forward credentials.
    origin = site(urllib.parse.urlsplit(public_url(url)).hostname)
    for _ in range(4):
        url = public_url(url)
        u = urllib.parse.urlsplit(url)
        if same_site and site(u.hostname) != origin:
            raise ValueError("来源重定向到其他站点")
        c = PublicHTTPS(u.hostname, timeout=12)
        try:
            c.request(
                "GET",
                urllib.parse.urlunsplit(("", "", u.path or "/", u.query, "")),
                headers={
                    "User-Agent": "SignalReader/0.3",
                    "Accept": "application/rss+xml, application/atom+xml, text/html, application/json",
                    **{
                        k: v
                        for k, v in (headers or {}).items()
                        if k in ("If-None-Match", "If-Modified-Since")
                    },
                },
            )
            r = c.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, r.getheader("Location", ""))
                continue
            if r.status == 304:
                return "", {}, url, 304
            if r.status != 200:
                raise ValueError("来源 HTTP " + str(r.status))
            body = r.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("来源内容过大")
            encoding = r.headers.get_content_charset() or "utf-8"
            return (
                body.decode(encoding, errors="replace"),
                {
                    k: r.getheader(k)
                    for k in ("ETag", "Last-Modified")
                    if r.getheader(k)
                },
                url,
                200,
            )
        finally:
            c.close()
    raise ValueError("来源重定向过多")
