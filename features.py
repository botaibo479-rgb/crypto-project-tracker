import json, re, time, threading, urllib.parse, datetime as dt
import account_profiles
import discussion_quality
import reading_text
from news_quality import relevant
from runtime_config import DATA_DIR
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent
TLOCK = threading.Lock()
APATH = DATA_DIR / "avatars.json"
try:
    AVATARS = json.loads(APATH.read_text())
except Exception:
    AVATARS = {}


def needs_translation(text):
    return bool(re.search("[A-Za-z]{3,}", text)) and len(
        re.findall("[\u4e00-\u9fff]", text)
    ) < max(3, len(re.findall("[A-Za-z]", text)) // 3)


# Machine translation is intentionally not performed here: source text was sent to
# an unofficial Google endpoint, exposing the watchlist. The agent translates on
# demand; readers see the original text.
def translated(text):
    if not needs_translation(text):
        return reading_text.readable(text)
    return None


def translation_status():
    return {"status": "disabled", "retryAt": None}


def text_translation_status(text):
    if translated(text) is not None:
        return {"status": "ready", "retryAt": None}
    return {"status": "disabled", "retryAt": None, "attempts": 0}


def localize(e):
    e = dict(e)
    if e.get("relatedItems"):
        e["relatedItems"] = [localize(item) for item in e["relatedItems"]]
    e["translationDetails"] = {
        field: text_translation_status(e.get(field, ""))
        for field in ["title", "summary"]
    }
    e["titleZh"] = translated(e.get("title", ""))
    e["summaryZh"] = translated(e.get("summary", ""))
    e["translationStatus"] = (
        "ready"
        if e["titleZh"] is not None and e["summaryZh"] is not None
        else "pending"
    )
    return e


def search_projects(query, request):
    if not 2 <= len(query) <= 80:
        raise ValueError("请输入至少两个字符")
    if query.startswith("@"):
        return {"candidates": [], "manual": True}
    d = json.loads(
        request(
            "https://api.coingecko.com/api/v3/search?"
            + urllib.parse.urlencode({"query": query})
        )
    )
    return {
        "candidates": [
            {
                "coinId": p["id"],
                "name": p["name"],
                "symbol": p["symbol"],
                "rank": p.get("market_cap_rank"),
            }
            for p in d.get("coins", [])[:8]
        ]
    }


def clean_url(value):
    u = urllib.parse.urlsplit(value.strip())
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.hostname in ["localhost", "127.0.0.1", "::1"]
    ):
        raise ValueError("官网和证据链接须为有效 HTTPS 地址")
    return value.strip()


def prepare_project(payload, request):
    coin = payload.get("coinId", "")
    if coin:
        if not re.fullmatch("[a-z0-9-]{1,100}", coin):
            raise ValueError("项目标识无效")
        d = json.loads(
            request(
                "https://api.coingecko.com/api/v3/coins/"
                + coin
                + "?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false"
            )
        )
        links = d.get("links") or {}
        home = next(
            (x for x in links.get("homepage", []) if x.startswith("https://")), ""
        )
        account = links.get("twitter_screen_name") or ""
        name = d["name"]
        symbol = d["symbol"].upper()
        identity = "CoinGecko 项目资料，官网及账号待人工复核"
    else:
        name = str(payload.get("name", "")).strip()
        symbol = str(payload.get("symbol", "")).upper().strip()
        home = str(payload.get("website", "")).strip()
        account = str(payload.get("account", "")).strip().removeprefix("@")
        identity = "用户填写，尚未核实身份"
    if "<" in name or ">" in name:
        raise ValueError("项目名称不能包含 HTML 标记")
    if not 1 <= len(name) <= 100 or not re.fullmatch("[A-Z0-9]{1,20}", symbol):
        raise ValueError("请输入项目名称与有效代币符号")
    if account and not re.fullmatch("[A-Za-z0-9_]{1,15}", account):
        raise ValueError("X 账号格式无效")
    if home:
        clean_url(home)
    return dict(
        coinId=coin,
        id=coin or ("custom-" + symbol.lower()),
        name=name,
        symbol=symbol,
        website=home,
        account=account,
        identity=identity,
        bg="#e5edf5",
        color="#486a8e",
        mark=symbol[0],
        custom=True,
    )


def confirm_project(payload):
    # Save the fields the user reviewed, without fetching over their edits.
    coin = str(payload.get("coinId", "")).strip()
    if coin and not re.fullmatch("[a-z0-9-]{1,100}", coin):
        raise ValueError("项目标识无效")
    project = prepare_project({k: v for k, v in payload.items() if k != "coinId"}, None)
    if coin:
        project.update(
            id=coin,
            coinId=coin,
            identity="参考 CoinGecko 项目资料，由用户确认；身份尚未独立核实",
            identitySource="https://www.coingecko.com/en/coins/" + coin,
        )
    project.update(match_fields(payload))
    return project


def match_fields(payload):
    result = {}
    for key in ["aliases", "contracts", "excludeTerms"]:
        raw = payload.get(key, [])
        values = (
            [x.strip() for x in re.split(r"[,，\n]", raw) if x.strip()]
            if isinstance(raw, str)
            else raw
        )
        if (
            not isinstance(values, list)
            or len(values) > 12
            or any(
                not isinstance(x, str) or not 2 <= len(x) <= 100 or "<" in x or ">" in x
                for x in values
            )
        ):
            raise ValueError("别名、合约地址与排除词每项 2–100 字，最多 12 项")
        result[key] = list(dict.fromkeys(values))
    return result


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
        APATH.parent.mkdir(exist_ok=True)
        tmp = APATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(AVATARS))
        tmp.replace(APATH)


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
