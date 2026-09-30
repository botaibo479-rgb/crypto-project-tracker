"""Local source-backed opinion journal. Rules classify wording, never real positions."""

import copy, json, re, threading, time
from crypto_tracker.store import jsonstore

DAY = 86400000
VERSION = "explicit-wording-v1"


def classify(text, project):
    # Require one explicit subject and directional statement in the same sentence.
    symbol = re.escape(project["symbol"])
    handle = re.escape(project.get("account", ""))
    subject = rf"(?:\${symbol}\b|@{handle}\b)" if handle else rf"\${symbol}\b"
    if re.search(
        r'\b(if|unless|might|could|would|put|puts|call|calls|hedge|hedging|not|quote)\b|如果|假如|可能|期权|对冲|并非|不是|不看|不做|他说|她说|转述|\b(?:said|says|was|used to|no longer)\b|[“”"「」]|https?://(?:x|twitter)\.com/\S+/status/',
        text,
        re.I,
    ):
        return "unclear"
    positive = rf"(?:I(?: am|\x27m)?\s+(?:bullish|long)\s+(?:on\s+)?{subject}|我(?:看好|看多|做多){subject})"
    negative = rf"(?:I(?: am|\x27m)?\s+(?:bearish|short)\s+(?:on\s+)?{subject}|我(?:看空|做空){subject})"
    pos = bool(re.search(positive, text, re.I))
    neg = bool(re.search(negative, text, re.I))
    return (
        "positive" if pos and not neg else "concern" if neg and not pos else "unclear"
    )


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}
        for k, v in [
            ("posts", {}),
            ("coverage", {}),
            ("watches", []),
            ("changes", []),
            ("enabled", []),
            ("tracking", []),
            ("enabledAt", {}),
            ("runs", {}),
        ]:
            self.data.setdefault(k, v)

    def save(self):
        jsonstore.write(self.path, self.data)

    def watches(self, pid):
        with self.lock:
            return copy.deepcopy(
                [w for w in self.data["watches"] if pid in w["projectIds"]]
            )

    def configure(self, payload, ids):
        with self.lock:
            action = payload.get("action")
            pid = payload.get("projectId")
            if action == "alerts":
                if pid not in ids:
                    raise ValueError("项目不存在")
                self.data["enabled"] = [p for p in self.data["enabled"] if p != pid] + (
                    [pid] if payload.get("enabled") is True else []
                )
                self.data["enabledAt"][pid] = time.time() * 1000
            elif action in ("watch", "remove"):
                handle = str(payload.get("account", "")).strip().lstrip("@").lower()
                if not re.fullmatch("[a-z0-9_]{1,15}", handle):
                    raise ValueError("账号格式无效")
                old = [w for w in self.data["watches"] if w["account"] != handle]
                if action == "watch":
                    projects = payload.get("projectIds", [])
                    note = str(payload.get("note", "")).strip()
                    if (
                        not isinstance(projects, list)
                        or not projects
                        or any(p not in ids for p in projects)
                    ):
                        raise ValueError("请选择有效项目")
                    if len(old) >= 20 or len(note) > 300:
                        raise ValueError("最多 20 个账号，备注最多 300 字")
                    old.append(
                        dict(
                            account=handle,
                            projectIds=list(dict.fromkeys(projects)),
                            note=note,
                        )
                    )
                self.data["watches"] = old
            else:
                raise ValueError("未知操作")
            self.save()

    def ingest(self, project, result, at):
        pid = project["id"]
        with self.lock:
            previous = self.data["coverage"].get(pid, {})
            posts = self.data["posts"].setdefault(pid, {})
            if result.get("status") == "ok":
                for row in sorted(
                    result.get("posts", []), key=lambda x: x["publishedAt"]
                ):
                    ident = row["id"]
                    if ident in posts:
                        continue
                    row = {
                        **row,
                        "stance": classify(row["text"], project)
                        if not row.get("quoted")
                        else "unclear",
                        "observedAt": at,
                        "version": VERSION,
                    }
                    prior = max(
                        (
                            p
                            for p in posts.values()
                            if p["account"] == row["account"]
                            and p["publishedAt"] < row["publishedAt"]
                        ),
                        key=lambda p: p["publishedAt"],
                        default=None,
                    )
                    if (
                        pid in self.data["enabled"]
                        and previous.get("lastSuccessAt")
                        and previous.get("status") == "ok"
                        and row["publishedAt"]
                        > max(
                            previous["lastSuccessAt"],
                            self.data["enabledAt"].get(pid, 0),
                        )
                        and at - row["publishedAt"] < DAY
                        and prior
                        and row["publishedAt"] - prior["publishedAt"] <= 7 * DAY
                        and {prior["stance"], row["stance"]} == {"positive", "concern"}
                    ):
                        self.data["changes"].append(
                            dict(p=pid, before=prior, after=row, at=at)
                        )
                    posts[ident] = row
                self.data["posts"][pid] = {
                    p["id"]: p
                    for p in sorted(posts.values(), key=lambda p: p["publishedAt"])[
                        -1500:
                    ]
                    if p["publishedAt"] >= at - 30 * DAY
                }
            self.data["coverage"][pid] = {
                "status": result.get("status"),
                "attemptedAt": at,
                "lastSuccessAt": at
                if result.get("status") == "ok"
                else previous.get("lastSuccessAt"),
                "startedAt": previous.get("startedAt") or at,
                "limited": result.get("limited", True),
                "watchErrors": result.get("watchErrors", []),
            }
            runs = self.data["runs"].setdefault(pid, [])
            runs.append(
                {
                    "at": at,
                    "ok": result.get("status") == "ok"
                    and not result.get("limited", True)
                    and not result.get("watchErrors"),
                }
            )
            self.data["runs"][pid] = [r for r in runs if r["at"] >= at - 3 * DAY][-200:]
            self.data["changes"] = self.data["changes"][-100:]
            self.save()

    def track(self, event, pid, market, at):
        with self.lock:
            key = str(event["id"]) + ":" + pid
            if any(t["id"] == key for t in self.data["tracking"]):
                return
            if len(self.data["tracking"]) >= 100:
                raise ValueError("最多跟踪 100 条，请先移除旧观察")
            if not market.get("price") or abs(at - market.get("priceAt", 0)) > 180000:
                raise ValueError("缺少新鲜行情，稍后重试")
            self.data["tracking"].append(
                dict(
                    id=key,
                    p=pid,
                    title=event["title"],
                    url=event.get("url", ""),
                    startedAt=at,
                    priceAt=market["priceAt"],
                    price=market["price"],
                    samples={},
                    source=market.get("source", "Binance"),
                )
            )
            self.save()

    def sample(self, markets, at):
        with self.lock:
            changed = False
            for t in self.data["tracking"]:
                m = markets.get(t["p"], {})
                for label, offset in [("1h", 3600000), ("24h", DAY), ("7d", 7 * DAY)]:
                    due = t["startedAt"] + offset
                    if (
                        label not in t["samples"]
                        and 0 <= m.get("priceAt", 0) - due <= 180000
                        and abs(at - m.get("priceAt", 0)) <= 180000
                        and m.get("price")
                    ):
                        t["samples"][label] = {
                            "price": m["price"],
                            "at": m["priceAt"],
                            "change": (m["price"] / t["price"] - 1) * 100,
                        }
                        changed = True
            if changed:
                self.save()

    def remove_track(self, key):
        with self.lock:
            self.data["tracking"] = [t for t in self.data["tracking"] if t["id"] != key]
            self.save()

    def snapshot(self, pid, at):
        with self.lock:
            posts = sorted(
                self.data["posts"].get(pid, {}).values(),
                key=lambda p: p["publishedAt"],
                reverse=True,
            )
            recent = [p for p in posts if at - DAY <= p["publishedAt"] <= at]
            prior = [p for p in posts if at - 2 * DAY <= p["publishedAt"] < at - DAY]
            authors = {p["account"] for p in recent}
            older = {p["account"] for p in prior}
            counts = [sum(p["account"] == a for p in recent) for a in authors]
            coverage = self.data["coverage"].get(pid, {})
            runs = self.data["runs"].get(pid, [])
            window = [r for r in runs if r["at"] >= at - 2 * DAY]
            comparable = (
                bool(window)
                and window[0]["at"] <= at - 2 * DAY + 3600000
                and window[-1]["at"] >= at - 3600000
                and all(r["ok"] for r in window)
                and all(
                    b["at"] - a["at"] <= 3600000 for a, b in zip(window, window[1:])
                )
            )
            # Search is capped and not exhaustive: never publish a population growth rate.
            return copy.deepcopy(
                dict(
                    posts=[p for p in posts if p["publishedAt"] >= at - 7 * DAY][:200],
                    coverage=coverage,
                    attention={
                        "authors24h": len(authors),
                        "posts24h": len(recent),
                        "newInSample": len(authors - older) if comparable else None,
                        "topShare": max(counts) / len(recent) if recent else None,
                    },
                    watches=self.data["watches"],
                    changes=[c for c in self.data["changes"] if c["p"] == pid],
                    enabled=pid in self.data["enabled"],
                    tracking=[t for t in self.data["tracking"] if t["p"] == pid],
                    version=VERSION,
                )
            )
