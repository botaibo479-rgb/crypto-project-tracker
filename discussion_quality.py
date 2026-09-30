"""Explainable ordering inside the retrieved sample, never a credibility score."""

import re
import hashlib
import unicodedata

PROMOTION = re.compile(
    r"\b(?:giveaway|airdrop|referral|sponsored|paid partnership|promo code)\b|抽奖|返佣|推广码|邀请码|付费合作",
    re.I,
)


def is_retweet(row):
    return bool(
        row.get("isRetweet")
        or row.get("retweetedStatus")
        or re.match(r"^RT\s+@", row.get("text", ""), re.I)
    )


def observation(row, timestamp):
    reply = bool(
        row.get("isReply") or row.get("inReplyToStatusId") or row.get("inReplyToId")
    )
    quote = bool(
        row.get("isQuote")
        or row.get("quotedStatusId")
        or row.get("quotedStatus")
        or re.match(r"^(?:Quote|引用)\s*:", row.get("text", ""), re.I)
    )
    text = unicodedata.normalize("NFKC", row.get("text", "")).casefold()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    fingerprint = hashlib.sha256(text.encode()).hexdigest() if len(text) >= 80 else None
    return {
        "id": str(row["id"]),
        "day": timestamp // 86400000,
        "fingerprint": fingerprint,
        "standalone": not reply
        and not quote
        and not row.get("text", "").lstrip().startswith("@"),
        "promotional": bool(PROMOTION.search(row.get("text", ""))),
    }


def mark_shared_text(observations):
    """Mark text shared across authors; retrieval order cannot prove who wrote it."""
    owners = {}
    for account, rows in observations.items():
        for row in rows:
            if row.get("fingerprint"):
                owners.setdefault(row["fingerprint"], set()).add(account)
    for rows in observations.values():
        for row in rows:
            row["sharedText"] = len(owners.get(row.get("fingerprint"), set())) > 1


def quality(observations):
    rows = list({r["id"]: r for r in observations}.values())
    distinct = {}
    repeated = 0
    for row in sorted(rows, key=lambda r: (r["day"], r["id"])):
        key = row.get("fingerprint") or row["id"]
        if key in distinct:
            repeated += 1
        else:
            distinct[key] = row
    unique = list(distinct.values())
    days = len({r["day"] for r in unique})
    shared = sum(bool(r.get("sharedText")) for r in unique)
    standalone = sum(r["standalone"] and not r.get("sharedText") for r in unique)
    promotional = sum(r["promotional"] for r in rows)
    # Caps prevent posting frequency from overwhelming other signals.
    score = (
        min(days, 4) * 3
        + min(standalone, 3) * 2
        - min(promotional, 4) * 4
        - min(repeated + shared, 4) * 2
    )
    return {
        "score": score,
        "samplePosts": len(rows),
        "activeDays": days,
        "standalonePosts": standalone,
        "repeatedPosts": repeated,
        "sharedTextPosts": shared,
        "promotionalPosts": promotional,
        "basis": f"检索样本中 {days} 天讨论 · {standalone} 条非回复/引用且未命中重复文本 · {repeated} 条账号内重复 · {shared} 条跨账号同文 · {promotional} 条含推广关键词",
        "limit": "按样本持续性与内容形式排序；短于 80 字符不做同文判断；去除链接并统一空白后匹配长文本，不判断原作者或抄袭；非回复/引用不等于原创，推广关键词不证明商业合作。",
    }


def rank(accounts):
    return sorted(
        accounts, key=lambda a: (a["quality"]["score"], a["publishedAt"]), reverse=True
    )
