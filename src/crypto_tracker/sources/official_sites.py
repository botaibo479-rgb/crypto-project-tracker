"""Per-project official site adapters for the seed projects (SOON, NEAR, NIL, PHA).

Fetched through the SSRF-safe public client with same-site redirects only.
"""

import datetime as dt
import json
import re
from html.parser import HTMLParser

from crypto_tracker.core.events import news_event, timestamp
from crypto_tracker.sources.rss import parse_feed


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, text):
        if self.href:
            self.text.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(" ".join(self.text).split())))
            self.href = None


def public_news(p, request):
    pid = p["id"]
    out = []
    if pid == "soon":
        response = json.loads(
            request("https://api.official-admin.soo.network/social/medium/list")
        )
        result = response.get("data", {}).get("result")
        if not result:
            raise ValueError("official_article_feed_unavailable")
        rows = result.get("data", {})
        for row in (rows.get("last", []) + rows.get("pin", []))[:8]:
            out.append(
                news_event(
                    pid,
                    row.get("title", ""),
                    row.get("articleLink", ""),
                    timestamp(row.get("publishedDate", "")),
                    "SOON 官网文章索引",
                )
            )
        return out
    if pid == "near":
        parser = Anchors()
        parser.feed(request("https://www.near.org/blog/category/Infrastructure"))
        seen = set()
        for path, label in parser.links:
            if (
                not path.startswith("/blog/")
                or "/category/" in path
                or path in seen
                or not label
            ):
                continue
            seen.add(path)
            out.append(
                news_event(
                    pid,
                    label,
                    "https://www.near.org" + path,
                    None,
                    "NEAR 官网 · Infrastructure 分类",
                    "官网分类页中的真实文章标题，发布时间未取得；此来源仅覆盖基础设施分类，不代表最新全量资讯。",
                )
            )
        return out[:5]
    if pid == "nil":
        parser = Anchors()
        parser.feed(request("https://nillion.com/news/"))
        for path, label in parser.links:
            if not path.startswith("/news/") or path == "/news/":
                continue
            match = re.match(r"(\d{1,2} [A-Za-z]+ \d{4})\s+(.*)", label)
            if match:
                date = int(
                    dt.datetime.strptime(match[1], "%d %B %Y")
                    .replace(tzinfo=dt.timezone.utc)
                    .timestamp()
                    * 1000
                )
                e = news_event(
                    pid, match[2], "https://nillion.com" + path, date, "Nillion 官网"
                )
                e["datePrecision"] = "day"
                out.append(e)
        return out[:8]
    if pid == "pha":
        url = "https://phala.com/atom.xml"
        for item in parse_feed(request(url), url)[:8]:
            out.append(
                news_event(
                    pid, item["title"], item["url"], item["at"], "Phala 官方 RSS"
                )
            )
        return out
    return []
