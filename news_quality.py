"""Conservative project relevance and evidence-preserving news curation."""

import re, hashlib, time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ALIASES = {
    "soon": r"\$SOON\b|soon_svm|SOON\s+(?:Network|SVM)|\bSOON\b.{0,24}(?:token|SVM|代币|网络|投资|价格|上市)",
    "near": r"NEAR\s+(?:Protocol|Foundation|AI|Intents)|NEARProtocol|\$NEAR\b|\bNEAR\b.{0,24}(?:token|代币|协议|网络|链|价格|基金会)",
    "pha": r"\bPhala\b|PhalaNetwork|\$PHA\b|\bPHA\b.{0,24}(?:token|代币|网络|价格|上市)",
    "nil": r"\bNillion\b|\$NIL\b|\bNIL\b.{0,24}(?:token|代币|网络|价格|上市)",
}
QUERIES = {
    "soon": '"SOON Network" OR "soon_svm" OR "$SOON"',
    "near": '"NEAR Protocol" OR "NEAR Intents" OR "NEAR Foundation"',
    "pha": '"Phala" OR "$PHA"',
    "nil": '"Nillion" OR "$NIL"',
}
CATEGORIES = [
    (
        "安全风险",
        r"\bhack(?:ed|ing)?\b|\bexploit(?:ed)?\b|\bvulnerability\b|漏洞|被盗|攻击|暂停提款",
        True,
    ),
    ("ETF / 机构产品", r"\bETF\b|交易所交易基金", True),
    ("交易所动态", r"delist|listing|will list|下架|上线.*(?:现货|合约)|上市", True),
    (
        "代币机制",
        r"tokenomics|buyback|unlock|inflation|回购|解锁|增发|通胀|代币经济",
        True,
    ),
    (
        "项目合作",
        r"partnership|partners with|strategic investment|合作|战略投资",
        False,
    ),
    (
        "产品进展",
        r"mainnet|upgrade|migration|launch|release|主网|升级|迁移|发布|上线",
        False,
    ),
]


def relevant(pid, text, project=None):
    if project:
        if any(
            w.casefold() in text.casefold() for w in project.get("excludeTerms", [])
        ):
            return False
        if any(
            re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text, re.I)
            for w in project.get("aliases", []) + project.get("contracts", [])
        ):
            return True
    if pid in ALIASES:
        return bool(re.search(ALIASES[pid], text))
    if not project:
        return False
    # Common-word project names need identifying context, not a bare word match.
    if project["name"].lower() in {"spark", "base", "layer", "pump", "flow", "core"}:
        if re.search(r"\$" + re.escape(project["symbol"]) + r"\b", text):
            return True
        account = project.get("account", "").lstrip("@")
        if account and re.search(r"@" + re.escape(account) + r"\b", text, re.I):
            return True
        domain = urlsplit(project.get("website", "")).hostname
        if domain and re.search(
            r"(?<![\w.-])" + re.escape(domain) + r"(?![\w.-])", text, re.I
        ):
            return True
        name = re.escape(project["name"])
        context = r"(?:DeFi|USDS|sUSDS|SparkLend|stablecoin|lending|vault|protocol|blockchain|代币|借贷|金库|稳定币|协议)"
        return bool(
            re.search(
                r"\b"
                + name
                + r"\b.{0,60}"
                + context
                + "|"
                + context
                + r".{0,60}\b"
                + name
                + r"\b",
                text,
                re.I | re.S,
            )
        )
    return bool(
        re.search(r"(?<!\w)" + re.escape(project["name"]) + r"(?!\w)", text, re.I)
        or re.search(r"\$" + re.escape(project["symbol"]) + r"\b", text)
    )


def canonical_url(url):
    try:
        u = urlsplit(url)
        host = u.netloc.lower().removeprefix("www.")
        if host == "twitter.com":
            host = "x.com"
        if host == "x.com":
            match = re.search(r"/status/(\d+)", u.path)
            if match:
                return "https://x.com/i/status/" + match[1]
        return urlunsplit(
            (
                "https",
                host,
                u.path.rstrip("/"),
                urlencode(
                    [
                        (k, v)
                        for k, v in parse_qsl(u.query)
                        if not k.lower().startswith("utm_")
                        and k not in ["s", "t", "ref"]
                    ]
                ),
                "",
            )
        )
    except Exception:
        return url


def annotate(e, current):
    e = dict(e)
    text = e.get("summary", "") + " " + e.get("title", "")
    date = e.get("publishedAt")
    age = (current - date) / 86400000 if date else None
    e["freshness"] = (
        "unknown"
        if age is None
        else "future"
        if age < -0.1
        else "recent"
        if age <= 7
        else "archive"
    )
    e["topic"] = "项目资讯"
    e["priorityReason"] = "未命中重点事件规则"
    e["high"] = False
    for topic, pattern, high in CATEGORIES:
        if re.search(pattern, text, re.I):
            e["topic"] = topic
            e["high"] = high and e["freshness"] == "recent"
            e["priorityReason"] = "文本命中「" + topic + "」规则，待阅读原文确认"
            break
    if e["freshness"] == "archive":
        e["priorityReason"] = "历史内容，不作为新快讯提醒"
    if e["freshness"] == "unknown":
        e["priorityReason"] = "发布时间未知，不作为新快讯提醒"
    e["channel"] = e.get("channel") or (
        "x"
        if e.get("source", "").startswith("X ·")
        else "official"
        if "官网" in e.get("source", "") or "RSS" in e.get("source", "")
        else "opennews"
    )
    e["evidence"] = (
        "团队成员个人表述"
        if e["channel"] == "team"
        else "官方账号表述"
        if e["channel"] == "x"
        else "官网表述"
        if e["channel"] == "official"
        else "媒体 / 聚合转述"
    )
    from reader_quality import quality

    e.update(quality(e))
    return e


def curate(rows, current=None, projects=None):
    current = current or int(time.time() * 1000)
    groups = {}
    for row in rows:
        e = annotate(row, current)
        if e["channel"] == "opennews" and not relevant(
            e["p"],
            e.get("title", "") + " " + e.get("summary", ""),
            next((p for p in (projects or []) if p["id"] == e["p"]), None),
        ):
            continue
        key = (
            e["p"],
            canonical_url(e.get("url", ""))
            if e.get("url")
            else e.get("id")
            or hashlib.sha256(
                (e.get("title", "") + e.get("summary", "")).encode()
            ).hexdigest(),
        )
        source = {"name": e.get("source"), "url": e.get("url"), "channel": e["channel"]}
        if key not in groups:
            e["sourcesList"] = [source]
            e["duplicateCount"] = 1
            groups[key] = e
        else:
            g = groups[key]
            g["duplicateCount"] += 1
            if source not in g["sourcesList"]:
                g["sourcesList"].append(source)
            g["discoveredAt"] = min(
                g.get("discoveredAt", current), e.get("discoveredAt", current)
            )
            if not g.get("publishedAt") and e.get("publishedAt"):
                g["publishedAt"] = e["publishedAt"]
    for e in groups.values():
        e["sourceCount"] = len(e["sourcesList"])
        e["independenceNote"] = "来源入口数量不代表独立信源数量；仅合并相同原文链接。"
    return sorted(
        groups.values(), key=lambda e: e.get("publishedAt") or 0, reverse=True
    )
