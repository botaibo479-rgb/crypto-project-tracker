"""Bounded, credential-free RSS/Atom discovery and collection."""

import datetime as dt, email.utils, hashlib, html, json, re, threading, time, urllib.parse, xml.etree.ElementTree as ET

from crypto_tracker.net.safe_fetch import fetch, public_url
from crypto_tracker.store import jsonstore
from html.parser import HTMLParser
from pathlib import Path


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.feeds = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href", "")
        if tag == "a" and href:
            self.links.append(href)
        if (
            tag == "link"
            and "alternate" in a.get("rel", "")
            and any(t in a.get("type", "") for t in ("rss", "atom"))
        ):
            self.feeds.append(href)


def route(url, rsshub=""):
    u = urllib.parse.urlsplit(public_url(url))
    host = u.hostname.lower()
    parts = u.path.strip("/").split("/")
    if (
        host == "github.com"
        and len(parts) >= 2
        and all(re.fullmatch(r"[\w.-]+", x) for x in parts[:2])
    ):
        return f"https://github.com/{parts[0]}/{parts[1]}/releases.atom"
    if host == "medium.com" and parts[0]:
        return "https://medium.com/feed/" + parts[0]
    if host.endswith(".medium.com"):
        return "https://" + host + "/feed"
    if host.endswith(".mirror.xyz") or host == "mirror.xyz":
        return url.rstrip("/") + "/feed/atom"
    if host in ("t.me", "telegram.me"):
        name = parts[1] if parts[0] == "s" and len(parts) > 1 else parts[0]
        if not rsshub:
            raise ValueError("Telegram 需要配置 SIGNAL_RSSHUB_URL，或填写已有 RSS 地址")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,64}", name):
            raise ValueError("频道地址无效")
        return public_url(rsshub.rstrip("/") + "/telegram/channel/" + name)
    return url


def parse_feed(text, base):
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        raise ValueError("不接受含实体声明的 XML")
    root = ET.fromstring(text)
    if root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("不是 RSS / Atom")
    out = []
    for item in [e for e in root.iter() if e.tag.split("}")[-1] in ("item", "entry")][
        :100
    ]:
        values = {}
        link = ""
        for child in item:
            tag = child.tag.split("}")[-1]
            value = "".join(child.itertext())
            if tag == "link" and child.attrib.get("rel", "alternate") == "alternate":
                link = child.attrib.get("href") or value
            values.setdefault(tag, value)
        title = html.unescape(re.sub("<[^>]+>", "", values.get("title", ""))).strip()[
            :300
        ]
        body = html.unescape(
            re.sub(
                "<[^>]+>",
                "",
                values.get("encoded")
                or values.get("content")
                or values.get("description")
                or values.get("summary")
                or title,
            )
        ).strip()[:6000]
        if not title or not link:
            continue
        try:
            link = public_url(urllib.parse.urljoin(base, link))
        except ValueError:
            continue
        raw = (
            values.get("published")
            or values.get("pubDate")
            or values.get("date")
            or values.get("updated")
        )
        stamp = None
        if raw:
            try:
                try:
                    date = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    date = email.utils.parsedate_to_datetime(raw)
                if date.tzinfo is not None:
                    stamp = int(date.timestamp() * 1000)
            except (ValueError, TypeError, OverflowError):
                pass
        out.append({"title": title, "body": body, "url": link, "at": stamp})
    return out


class Store:
    def __init__(self, path, rsshub=""):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.rsshub = rsshub
        self.data = {"projects": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))
        for project in self.data["projects"].values():
            project["discovering"] = False

    def save(self):
        jsonstore.write(self.path, self.data)

    def snapshot(self, pid):
        with self.lock:
            return json.loads(
                json.dumps(
                    self.data["projects"].get(
                        pid, {"sources": [], "candidates": [], "economy": False}
                    )
                )
            )

    def patch(self, pid, **values):
        with self.lock:
            self.data["projects"].setdefault(
                pid, {"sources": [], "candidates": [], "economy": False}
            ).update(values)
            self.save()

    def discover(self, p):
        pid = p["id"]
        old = self.snapshot(pid)
        if old.get("discovering"):
            return
        self.patch(pid, discovering=True)
        try:
            text, _, base, _ = fetch(p["website"])
            parser = Links()
            parser.feed(text)
            candidates = []
            for href in parser.feeds:
                try:
                    candidates.append(
                        {
                            "url": public_url(urllib.parse.urljoin(base, href)),
                            "kind": "原生 RSS / Atom",
                            "evidence": base,
                        }
                    )
                except ValueError:
                    pass
            pages = []
            for href in parser.links:
                try:
                    url = public_url(urllib.parse.urljoin(base, href))
                    host = urllib.parse.urlsplit(url).hostname
                except ValueError:
                    continue
                if host in (
                    "github.com",
                    "medium.com",
                    "t.me",
                    "telegram.me",
                    "mirror.xyz",
                ) or host.endswith((".medium.com", ".mirror.xyz")):
                    try:
                        feed = route(url, self.rsshub)
                    except ValueError:
                        continue
                    if feed != url:
                        candidates.append(
                            {
                                "url": feed,
                                "kind": "官网链接推导 · 待核对",
                                "evidence": url,
                            }
                        )
                elif (
                    any(x in url.lower() for x in ("blog", "forum", "governance"))
                    and host == urllib.parse.urlsplit(base).hostname
                ):
                    pages.append(url)
            for url in list(dict.fromkeys(pages))[:2]:
                try:
                    text, _, b, _ = fetch(url)
                    other = Links()
                    other.feed(text)
                    for href in other.feeds:
                        candidates.append(
                            {
                                "url": public_url(urllib.parse.urljoin(b, href)),
                                "kind": "博客 / 论坛 RSS",
                                "evidence": b,
                            }
                        )
                except Exception:
                    pass
            unique = {x["url"]: x for x in candidates}
            self.patch(
                pid,
                candidates=list(unique.values())[:20],
                discoveryStatus="ok",
                discoveredAt=int(time.time() * 1000),
            )
        except Exception:
            self.patch(
                pid, discoveryStatus="error", discoveredAt=int(time.time() * 1000)
            )
        finally:
            self.patch(pid, discovering=False)

    def add(self, pid, url, label):
        url = route(url, self.rsshub)
        text, _, base, _ = fetch(url)
        parse_feed(text, base)
        label = str(label).strip()[:80] or "项目订阅"
        with self.lock:
            d = self.data["projects"].setdefault(
                pid, {"sources": [], "candidates": [], "economy": False}
            )
            if len(d["sources"]) >= 8:
                raise ValueError("每项目最多 8 个订阅源")
            if any(x["url"] == url for x in d["sources"]):
                raise ValueError("来源已存在")
            d["sources"].append(
                {
                    "id": hashlib.sha256(url.encode()).hexdigest()[:16],
                    "url": url,
                    "label": label,
                    "enabled": True,
                    "status": "pending",
                }
            )
            self.save()

    def action(self, pid, payload):
        with self.lock:
            d = self.data["projects"].setdefault(
                pid, {"sources": [], "candidates": [], "economy": False}
            )
            if payload.get("action") == "economy":
                d["economy"] = bool(payload.get("enabled"))
            else:
                item = next(
                    (s for s in d["sources"] if s["id"] == payload.get("id")), None
                )
                if not item:
                    raise ValueError("来源不存在")
                item["enabled"] = not item["enabled"]
            self.save()

    def healthy(self, pid):
        return any(
            s["enabled"]
            and s.get("status") == "ok"
            and time.time() * 1000 - s.get("lastSuccessAt", 0) < 3600000
            for s in self.snapshot(pid)["sources"]
        )

    def collect(self, p, news_event):
        results = []
        for source in self.snapshot(p["id"])["sources"]:
            if not source["enabled"]:
                continue
            now = int(time.time() * 1000)
            if now < source.get("retryAt", 0):
                continue
            try:
                text, headers, base, code = fetch(
                    source["url"], source.get("conditional")
                )
                rows = source.get("rows", []) if code == 304 else parse_feed(text, base)
                update = {
                    "status": "ok",
                    "lastSuccessAt": now,
                    "rows": rows,
                    "failures": 0,
                    "conditional": {"If-None-Match": headers["ETag"]}
                    if headers.get("ETag")
                    else source.get("conditional", {}),
                }
                for r in rows:
                    if r["at"] and not 0 <= now - r["at"] <= 7 * 86400000:
                        continue
                    e = news_event(
                        p["id"],
                        r["title"],
                        r["url"],
                        r["at"],
                        "RSS · " + source["label"],
                        r["body"],
                    )
                    e.update(
                        channel="subscription",
                        subscriptionId=source["id"],
                        sourceUrl=source["url"],
                        matchReason="用户确认的项目订阅；来源身份未独立核验",
                    )
                    results.append(e)
            except Exception:
                failures = source.get("failures", 0) + 1
                update = {
                    "status": "error",
                    "failures": failures,
                    "retryAt": now + min(86400000, 1800000 * 2 ** min(failures - 1, 5)),
                }
            with self.lock:
                current = next(
                    (
                        s
                        for s in self.data["projects"][p["id"]]["sources"]
                        if s["id"] == source["id"]
                    ),
                    None,
                )
                if current:
                    current.update(update, lastAttemptAt=now)
                    self.save()
        return results
