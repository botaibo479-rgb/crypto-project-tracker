"""Event record helpers shared by all collectors."""

import datetime as dt
import email.utils
import hashlib
import time


def now():
    return int(time.time() * 1000)


def timestamp(s):
    try:
        if isinstance(s, (int, float)):
            return int(s if s > 10**11 else s * 1000)
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            d = email.utils.parsedate_to_datetime(s)
        return int(d.replace(tzinfo=d.tzinfo or dt.timezone.utc).timestamp() * 1000)
    except Exception:
        return None


def news_event(pid, title, url, published, source, body=""):
    return dict(
        id="news-" + hashlib.sha256((pid + url + source).encode()).hexdigest()[:20],
        p=pid,
        type="news",
        title=title,
        summary=body
        or "保留来源原文标题。点击查看原始内容，项目方表述不等于独立核实。",
        url=url,
        publishedAt=published,
        discoveredAt=now(),
        source=source,
        high=False,
        topic="项目资讯",
        evidence="来源声明",
        datePrecision="unknown" if not published else "source",
    )
