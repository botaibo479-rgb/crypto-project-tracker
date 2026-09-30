"""X account profiles and recent discussants (KOL discovery) via OpenTwitter."""

import datetime as dt
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from crypto_tracker.core import account_profiles, discussion_quality
from crypto_tracker.core.news_quality import relevant
from crypto_tracker.store import jsonstore

TLOCK = threading.Lock()
APATH = None
AVATARS = {}


def configure(path):
    """Persist the profile cache at ``path`` (the collector's store)."""
    global APATH, AVATARS
    APATH = Path(path)
    AVATARS = jsonstore.read(APATH, {})


def enrich_avatars(accounts, request):
    def apply(a, cached):
        if "followers" in cached:
            a["followers"] = cached["followers"]
        if cached.get("url"):
            a["avatar"] = cached["url"]
        if cached.get("profile"):
            a["profile"] = cached["profile"]

    def enrich(a):
        handle = a["account"]
        cached = AVATARS.get(handle, {})
        if cached.get("expires", 0) > time.time() and cached.get("profile"):
            apply(a, cached)
            return
        stamp = int(time.time() * 1000)
        try:
            response = json.loads(
                request(
                    "https://ai.6551.io/open/twitter_user_info", {"username": handle}
                )
            )
            if response.get("success") is False:
                raise ValueError("profile_query_failed")
            returned = (response.get("data") or {}).get("screenName")
            if returned and returned.lower() != handle.lower():
                raise ValueError("profile_identity_mismatch")
            profile = account_profiles.observed(
                cached.get("profile", {}), response.get("data"), stamp
            )
            cached = {
                "url": profile["avatar"],
                "followers": profile["followers"],
                "profile": profile,
                "expires": time.time() + 86400,
            }
        except Exception:
            cached = {
                **cached,
                "profile": account_profiles.failed(cached.get("profile", {}), stamp),
                "expires": time.time() + 300,
            }
        with TLOCK:
            AVATARS[handle] = cached
        apply(a, cached)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(enrich, accounts))
    with TLOCK:
        if APATH is not None:
            jsonstore.write(APATH, AVATARS)


def eligible_discussant(a):
    try:
        return int(a.get("followers") or 0) >= 20000
    except (ValueError, TypeError):
        return False


def discover(p, request, stamp, watches=None):
    if not p.get("account"):
        return {
            "status": "unavailable",
            "message": "尚未配置官方 X 账号",
            "discussants": [],
            "team": [],
        }
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    r = json.loads(
        request(
            "https://ai.6551.io/open/twitter_search",
            {
                "mentionUser": p["account"],
                "maxResults": 40,
                "product": "Latest",
                "excludeRetweets": True,
                "sinceDate": since.strftime("%Y-%m-%d"),
            },
        )
    )
    rows = r.get("data", [])
    if isinstance(rows, dict):
        rows = rows.get("tweets", rows.get("list", []))
    if not isinstance(rows, list) or r.get("success") is False:
        raise ValueError("discussion_search_failed")
    limited = len(rows) >= 40
    watch_errors = []
    watched = {w["account"] for w in watches or []}
    for handle in watched:
        try:
            response = json.loads(
                request(
                    "https://ai.6551.io/open/twitter_search",
                    {
                        "fromUser": handle,
                        "mentionUser": p["account"],
                        "maxResults": 40,
                        "product": "Latest",
                        "excludeRetweets": True,
                        "excludeReplies": True,
                        "sinceDate": since.strftime("%Y-%m-%d"),
                    },
                )
            )
            extra = response.get("data", [])
            if isinstance(extra, dict):
                extra = extra.get("tweets", extra.get("list", []))
            if response.get("success") is False or not isinstance(extra, list):
                raise ValueError("watch_search_failed")
            limited = limited or len(extra) >= 40
            rows += [
                r
                for r in extra
                if isinstance(r, dict)
                and str(
                    r.get("userScreenName")
                    or (r.get("user") or {}).get("screenName")
                    or (r.get("user") or {}).get("username")
                    or ""
                ).lower()
                == handle
            ]
        except Exception:
            watch_errors.append(handle)
    authors = {}
    observations = {}
    seen = set()
    posts = []
    for row in rows:
        if not isinstance(row, dict) or discussion_quality.is_retweet(row):
            continue
        user = row.get("user") or {}
        handle = (
            row.get("userScreenName") or user.get("screenName") or user.get("username")
        )
        tid = str(row.get("id", ""))
        date = stamp(row.get("createdAt", ""))
        if (
            not handle
            or not re.fullmatch("[A-Za-z0-9_]{1,15}", handle)
            or not tid.isdigit()
            or handle.lower() == p["account"].lower()
        ):
            continue
        if (
            not date
            or date < int(since.timestamp() * 1000)
            or date > int(time.time() * 1000) + 300000
        ):
            continue
        if tid in seen:
            continue
        seen.add(tid)
        handle = handle.lower()
        text = str(row.get("text", ""))
        if text.lstrip().startswith("@"):
            continue
        if any(w.casefold() in text.casefold() for w in p.get("excludeTerms", [])):
            continue
        if not (
            re.search(r"@" + re.escape(p["account"]) + r"\b", text, re.I)
            or relevant(p.get("id", ""), text, p)
        ):
            continue
        posts.append(
            dict(
                id=tid,
                account=handle,
                text=text,
                url="https://x.com/" + handle + "/status/" + tid,
                publishedAt=date,
                quoted=bool(
                    row.get("isQuote")
                    or row.get("quotedStatus")
                    or row.get("quotedTweet")
                ),
                watched=handle in watched,
            )
        )
        a = authors.setdefault(
            handle,
            {
                "account": handle,
                "avatar": row.get("userProfileImageUrl")
                or user.get("profileImageUrl")
                or user.get("profile_image_url_https"),
                "name": row.get("userName") or user.get("name") or handle,
                "text": text,
                "url": "https://x.com/" + handle + "/status/" + tid,
                "publishedAt": date,
                "count": 0,
                "followers": row.get("userFollowers") or user.get("followersCount"),
                "identity": "近期讨论者，KOL 身份未核实",
            },
        )
        observations.setdefault(handle, []).append(
            discussion_quality.observation(row, date)
        )
        a["count"] += 1
        if date > a["publishedAt"]:
            a.update(
                text=text,
                url="https://x.com/" + handle + "/status/" + tid,
                publishedAt=date,
            )
    candidates = sorted(authors.values(), key=lambda a: a["publishedAt"], reverse=True)
    enrich_avatars(candidates + p.get("team", []), request)
    discussion_quality.mark_shared_text(observations)
    for a in candidates:
        a["quality"] = discussion_quality.quality(observations[a["account"]])
    selected = discussion_quality.rank(
        [a for a in candidates if eligible_discussant(a)]
    )[:12]
    allowed = {a["account"] for a in candidates if eligible_discussant(a)} | watched
    posts = [r for r in posts if r["account"] in allowed]
    return {
        "status": "ok",
        "posts": posts,
        "limited": limited,
        "watchErrors": watch_errors,
        "discussants": selected,
        "team": [],
        "updatedAt": int(time.time() * 1000),
        "message": "近 7 天提及官方账号，粉丝数至少 20,000；按样本持续性和内容形式排序；最多检索 40 条，非全量名单",
    }
