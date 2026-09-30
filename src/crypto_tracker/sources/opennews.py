"""Project news (OpenNews) and official-account posts (OpenTwitter) via ai.6551.io."""

import json

from crypto_tracker.core.events import news_event, now, timestamp
from crypto_tracker.core.news_quality import QUERIES, relevant
from crypto_tracker.net.http import error_label
from crypto_tracker.sources.intelligence import kind


def provider_news(p, request, has_token, rss_store):
    out = []
    statuses = {}
    if not has_token:
        return [], {
            "OpenNews": {
                "status": "missing_credential",
                "message": "未配置 OPENNEWS_TOKEN",
            },
            "OpenTwitter": {
                "status": "missing_credential",
                "message": "未连接；团队和 KOL 尚未采集",
            },
        }
    extra = [
        str(v).replace(chr(34), "").replace(chr(92), "")
        for v in p.get("aliases", [])[:4] + p.get("contracts", [])[:2]
    ]
    query = QUERIES[p["id"]] + "".join(" OR " + chr(34) + v + chr(34) for v in extra)
    tasks = {
        "OpenNews": ("news_search", {"coins": [p["symbol"]], "limit": 30, "page": 1}),
        "OpenNews关键词": ("news_search", {"q": query, "limit": 30, "page": 1}),
        "OpenTwitter": (
            "twitter_user_tweets",
            {
                "username": p["account"],
                "maxResults": 20,
                "includeReplies": True,
                "includeRetweets": False,
                "product": "Latest",
            },
        ),
    }
    if rss_store.snapshot(p["id"]).get("economy") and rss_store.healthy(p["id"]):
        tasks.pop("OpenNews关键词", None)
        statuses["OpenNews关键词"] = {
            "status": "limited",
            "message": "免费源优先模式：健康 RSS 已更新，跳过关键词补充检索；保留币种、X 与市场事件",
        }
    for name, (path, payload) in tasks.items():
        try:
            response = json.loads(request("https://ai.6551.io/open/" + path, payload))
            rows = response.get("data", [])
            if response.get("success") is False:
                raise ValueError("provider_error")
            if isinstance(rows, dict):
                rows = rows.get("tweets", rows.get("list", []))
            if not isinstance(rows, list):
                raise ValueError("unexpected_data")
            before_count = len(out)
            for row in rows:
                if name == "OpenTwitter":
                    author = row.get("userScreenName", p["account"])
                    tid = str(row.get("id", ""))
                    if not tid.isdigit() or author.lower() != p["account"].lower():
                        continue
                    e = news_event(
                        p["id"],
                        row.get("text", "")[:140],
                        "https://x.com/" + author + "/status/" + tid,
                        timestamp(row.get("createdAt", "")),
                        "X · @" + author,
                        row.get("text", ""),
                    )
                else:
                    if kind(row):
                        continue
                    url = row.get("link", "")
                    text = row.get("text", "")
                    # The provider's coin mapping is necessary, but ambiguous English words alone are insufficient.
                    if not url.startswith("https://") or not relevant(p["id"], text, p):
                        continue
                    e = news_event(
                        p["id"],
                        text[:140],
                        url,
                        timestamp(row.get("ts")),
                        str(row.get("newsType", "OpenNews")),
                        text,
                    )
                e["channel"] = "x" if name == "OpenTwitter" else "opennews"
                if name == "OpenTwitter":
                    e.update(
                        isReply=bool(
                            row.get("isReply") or row.get("inReplyToStatusId")
                        ),
                        isRetweet=bool(row.get("isRetweet")),
                    )
                if name != "OpenTwitter":
                    rating = row.get("aiRating") or {}
                    e["providerRating"] = {
                        "score": rating.get("score"),
                        "summary": rating.get("summary"),
                        "status": rating.get("status"),
                    }
                    e["matchReason"] = "官方名称 / 标识匹配；" + (
                        "币种检索" if name == "OpenNews" else "关键词补充检索"
                    )
                out.append(e)
            statuses[name] = {
                "status": "ok",
                "count": len(out) - before_count,
                "returnedCount": len(rows),
                "lastSuccessAt": now(),
                "message": "分页首批检索，非完整历史；结果经项目标识过滤",
            }
        except Exception as e:
            statuses[name] = {"status": "error", "message": error_label(e)}
    return out, statuses
