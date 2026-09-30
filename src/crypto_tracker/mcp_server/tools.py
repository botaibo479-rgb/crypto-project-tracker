"""MCP tools for Hermes Agent.

Read tools only read the collector's store (readOnlyHint). Write tools queue a
command in the spool and wait briefly for the collector's validated result;
they carry no readOnlyHint, so a Hermes server entry with ``trust: untrusted``
asks the user before each call. This process holds no provider credential and
performs no network I/O.
"""

import asyncio
import functools
import inspect
import time
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from crypto_tracker.core import alerts as alert_rules
from crypto_tracker.core.digest import make_digest
from crypto_tracker.core.events import now
from crypto_tracker.mcp_server import render
from crypto_tracker.mcp_server.reader import Reader
from crypto_tracker.store import spool

INSTRUCTIONS = (
    "Crypto project tracker: curated news, official and team X posts, KOL "
    "discussants, Binance market snapshots, OpenNews signals and rule-based alerts "
    "for a user-defined watchlist. Start with tracker_project_brief, then drill "
    "down. Always cite the url of each item you rely on; the data is a sample, not "
    "complete coverage, and nothing here is trading advice. " + render.UNTRUSTED_NOTE
)
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
LOOKUP = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)
HOUR = 3600000
RuleType = Literal[
    "price",
    "oi",
    "level",
    "ema200",
    "ema",
    "combo",
    "news",
    "listing",
    "funding",
    "liquidation",
    "flow",
]


def default_period(kind):
    if kind in alert_rules.PROVIDER_TYPES:
        return "event"
    return {"price": "24h", "oi": "1h"}.get(kind, "4h")


def guarded(fn):
    """Report validation errors (ValueError) to the model as tool errors."""
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ValueError as e:
                raise ToolError(str(e)[:300]) from None

    else:

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ValueError as e:
                raise ToolError(str(e)[:300]) from None

    return wrapper


def build(paths, wait_seconds=15.0):
    reader = Reader(paths)
    mcp = MCPServer("crypto-tracker", instructions=INSTRUCTIONS)

    def tool(annotations):
        return lambda fn: mcp.tool(annotations=annotations)(guarded(fn))

    def envelope(**result):
        fresh = reader.freshness()
        result["collector"] = {
            "last_write": render.iso(fresh["collector_last_write"]),
            "stale": fresh["stale"],
            "opennews_credential": fresh["credential"].get("opennews", "unknown"),
        }
        result["note"] = render.UNTRUSTED_NOTE
        return result

    def events_for(pid=None, since_hours=24, channel=None, topic=None):
        since = now() - since_hours * HOUR
        rows = []
        for e in reader.curated():
            if pid and pid not in (e.get("projectIds") or [e.get("p")]):
                continue
            if (e.get("publishedAt") or e.get("discoveredAt") or 0) < since:
                continue
            if channel and (e.get("channel") or "official_site") != channel:
                continue
            if topic and topic not in str(e.get("topic", "")):
                continue
            rows.append(e)
        return rows

    def ranked(rows):
        return sorted(
            rows,
            key=lambda e: (
                bool(e.get("high")),
                e.get("qualityScore", 0),
                e.get("publishedAt") or 0,
            ),
            reverse=True,
        )

    def kols(pid, limit=12):
        social = reader.live().get("social", {}).get(pid, {})
        week = now() - 7 * 24 * HOUR
        people = [
            a
            for a in social.get("discussants", [])
            if int(a.get("followers") or 0) >= 20000
            and week <= (a.get("publishedAt") or 0) <= now() + 300000
        ]
        return social, [render.person(a) for a in people[:limit]]

    async def command(kind, payload):
        try:
            ident = spool.submit(paths.spool, kind, payload)
        except PermissionError:
            raise ValueError("无法写入命令队列：检查 TRACKER_HOME/spool 权限")
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            result = spool.results(paths.store).get(ident)
            if result:
                return {"command_id": ident, **result}
            await asyncio.sleep(0.25)
        return {
            "command_id": ident,
            "status": "queued",
            "note": "采集器尚未处理；稍后用 tracker_command_result 查询。若持续排队，检查采集器服务是否运行。",
        }

    # ---------------- read tools ----------------

    @tool(READ)
    def tracker_list_projects() -> dict:
        """List watched projects with ids, symbols, official X accounts, websites and team size."""
        rows = [
            {
                "id": p["id"],
                "name": p.get("name"),
                "symbol": p.get("symbol"),
                "x_account": p.get("account") or None,
                "website": render.https(p.get("website")),
                "identity": p.get("identity"),
                "team_members": len(p.get("team", [])),
                "aliases": p.get("aliases", []),
                "rootdata_source": render.https(p.get("teamSourceUrl")),
            }
            for p in reader.projects()
        ]
        return envelope(projects=rows)

    @tool(READ)
    def tracker_project_brief(project: str, hours: int = 24) -> dict:
        """One-call overview of a project: market snapshot, top events, official/team posts,
        KOL discussants, OpenNews signals, fired alerts and source health for the last
        `hours` (1-168). `project` accepts id, symbol or name."""
        p = reader.project(project)
        pid = p["id"]
        hours = max(1, min(int(hours), 168))
        since = now() - hours * HOUR
        rows = [e for e in events_for(pid, hours) if not e.get("lowInformation")]
        live = reader.live()
        social, people = kols(pid, 5)
        fired = [
            a
            for a in reader.alerts().get("alerts", [])
            if a.get("p") == pid and a.get("at", 0) >= since
        ]
        result = envelope(
            project={"id": pid, "name": p.get("name"), "symbol": p.get("symbol")},
            window_hours=hours,
            market=render.market(live.get("markets", {}).get(pid)),
            top_events=[render.event(e) for e in ranked(rows)[:8]],
            official_posts=[render.event(e) for e in rows if e.get("channel") == "x"][
                :5
            ],
            team_posts=[render.event(e) for e in rows if e.get("channel") == "team"][
                :5
            ],
            kol_discussants=people,
            signals=[
                render.signal(s)
                for s in reader.signals()
                if s.get("p") == pid and (s.get("publishedAt") or 0) >= since
            ][:8],
            alerts_fired=[
                {
                    "rule": a.get("ruleName"),
                    "type": a.get("type"),
                    "title": render.clean(a.get("title"), 160),
                    "at": render.iso(a.get("at")),
                    "url": render.https((a.get("evidence") or {}).get("url")),
                }
                for a in fired[-10:]
            ],
            sources={
                name: s.get("status")
                for name, s in live.get("sources", {}).get(pid, {}).items()
            },
            social_status=social.get("status"),
            event_count=len(rows),
        )
        return render.fit(result, "top_events")

    @tool(READ)
    def tracker_events(
        project: str | None = None,
        since_hours: int = 24,
        channel: Literal["opennews", "x", "team", "subscription", "official_site"]
        | None = None,
        topic: str | None = None,
        min_quality: int = 0,
        important_only: bool = False,
        include_low_information: bool = False,
        limit: int = 20,
    ) -> dict:
        """Curated, de-duplicated events (news, official X, team X, RSS, official sites),
        newest and most important first. Filter by project, channel, topic text, quality
        score (0-100) and time window (hours, max 720)."""
        pid = reader.project(project)["id"] if project else None
        rows = events_for(pid, max(1, min(int(since_hours), 720)), channel, topic)
        rows = [
            e
            for e in rows
            if e.get("qualityScore", 0) >= min_quality
            and (e.get("high") or not important_only)
            and (include_low_information or not e.get("lowInformation"))
        ]
        limit = max(1, min(int(limit), 50))
        result = envelope(
            total=len(rows),
            events=[render.event(e) for e in ranked(rows)[:limit]],
        )
        return render.fit(result, "events")

    @tool(READ)
    def tracker_event_detail(event_id: str) -> dict:
        """Full record of one event: complete text, related reports, cluster reasoning
        and later progress candidates."""
        for e in reader.curated():
            ids = [e.get("id")] + [x.get("id") for x in e.get("relatedItems") or []]
            if event_id in ids:
                return render.fit(envelope(event=render.event(e, detail=True)), "event")
        raise ValueError("事件不存在或已超出保留窗口")

    @tool(READ)
    def tracker_market(project: str) -> dict:
        """Latest Binance USD-M perpetual snapshot collected for a project: price, 24h
        change, volume, EMA200/360 on closed 4h candles with cross state, and 1h OI change."""
        p = reader.project(project)
        m = reader.live().get("markets", {}).get(p["id"])
        return envelope(project=p["id"], market=render.market(m))

    @tool(READ)
    def tracker_kol(project: str) -> dict:
        """Recent discussants of a project's official X account (last 7 days, at least
        20,000 followers), ordered by sample persistence and content form. KOL identity
        is not verified."""
        p = reader.project(project)
        social, people = kols(p["id"])
        return envelope(
            project=p["id"],
            status=social.get("status"),
            method=render.clean(social.get("message"), 200),
            discussants=people,
        )

    @tool(READ)
    def tracker_viewpoints(project: str, limit: int = 20) -> dict:
        """Source-backed opinion journal for a project: attention statistics, recent posts
        with conservative stance labels (explicit first-person wording only), stance
        changes, watched accounts and price tracking of events."""
        p = reader.project(project)
        snap = reader.viewpoints(p["id"])
        posts = [
            {
                "account": x.get("account"),
                "stance": x.get("stance"),
                "text": render.clean(x.get("text"), 300),
                "url": render.https(x.get("url")),
                "published_at": render.iso(x.get("publishedAt")),
                "watched": x.get("watched"),
                "untrusted_content": True,
            }
            for x in snap.get("posts", [])[: max(1, min(int(limit), 50))]
        ]
        result = envelope(
            project=p["id"],
            method=snap.get("version"),
            attention=snap.get("attention"),
            coverage=snap.get("coverage"),
            changes=[
                {
                    "account": c["after"].get("account"),
                    "before": c["before"].get("stance"),
                    "after": c["after"].get("stance"),
                    "before_url": render.https(c["before"].get("url")),
                    "after_url": render.https(c["after"].get("url")),
                    "at": render.iso(c.get("at")),
                }
                for c in snap.get("changes", [])[-10:]
            ],
            watched_accounts=[
                {"account": w["account"], "projects": w["projectIds"]}
                for w in snap.get("watches", [])
            ],
            price_tracking=snap.get("tracking", []),
            alerts_enabled=snap.get("enabled"),
            posts=posts,
        )
        return render.fit(result, "posts")

    @tool(READ)
    def tracker_team(project: str, days: int = 30) -> dict:
        """Team members linked to a project (with evidence and verification labels) and
        their recent posts that explicitly mention the project."""
        p = reader.project(project)
        members = [
            {
                "account": a.get("account"),
                "role": render.clean(a.get("role"), 80),
                "identity": a.get("identity"),
                "evidence": render.https(
                    a.get("rootdataEvidence") or a.get("evidence")
                ),
            }
            for a in p.get("team", [])
        ]
        posts = events_for(p["id"], max(1, min(int(days), 30)) * 24, channel="team")
        observation = p.get("rootdataObservation") or {}
        result = envelope(
            project=p["id"],
            members=members,
            rootdata={
                "source": render.https(p.get("teamSourceUrl")),
                "status": observation.get("status"),
                "checked_at": render.iso(observation.get("checkedAt")),
                "unresolved_candidates": len(observation.get("candidates", [])),
                "note": observation.get("note"),
            },
            posts=[render.event(e) for e in ranked(posts)[:20]],
        )
        return render.fit(result, "posts")

    @tool(READ)
    def tracker_signals(
        project: str | None = None,
        kind: Literal["listing", "funding", "liquidation", "flow", "oi", "price"]
        | None = None,
        since_hours: int = 24,
        limit: int = 20,
    ) -> dict:
        """OpenNews classified signals: exchange announcements, funding-rate events,
        large liquidations, fund flows and short-term OI/price moves."""
        pid = reader.project(project)["id"] if project else None
        since = now() - max(1, min(int(since_hours), 168)) * HOUR
        rows = [
            s
            for s in reader.signals()
            if (not pid or s.get("p") == pid)
            and (not kind or s.get("providerKind") == kind)
            and (s.get("publishedAt") or 0) >= since
        ]
        result = envelope(
            total=len(rows),
            signals=[render.signal(s) for s in rows[: max(1, min(int(limit), 50))]],
            funding_history=[
                {
                    "title": render.clean(i.get("title"), 120),
                    "at": render.iso(i.get("at")),
                    "url": render.https(i.get("url")),
                    "source": i.get("source"),
                }
                for i in (reader.funding(pid) if pid else [])
            ][:10],
        )
        return render.fit(result, "signals")

    @tool(READ)
    def tracker_macro_calendar() -> dict:
        """High-importance macro events for about the next two weeks (provider data;
        may be unavailable)."""
        cal = reader.calendar()
        return envelope(
            status=cal.get("status"),
            error=cal.get("errorMessage"),
            items=[
                {
                    "title": render.clean(i.get("title"), 160),
                    "date": i.get("date"),
                    "estimated": i.get("estimated"),
                    "importance": i.get("importance"),
                    "url": render.https(i.get("url")),
                }
                for i in cal.get("items", [])[:50]
            ],
        )

    @tool(READ)
    def tracker_alerts(since_hours: int = 24, limit: int = 30) -> dict:
        """Alert rules and alerts fired in the window, each with its evidence."""
        data = reader.alerts()
        since = now() - max(1, min(int(since_hours), 720)) * HOUR
        fired = [a for a in data.get("alerts", []) if a.get("at", 0) >= since]
        return envelope(
            rules=[
                {
                    k: r.get(k)
                    for k in [
                        "id",
                        "p",
                        "type",
                        "name",
                        "period",
                        "threshold",
                        "cooldownMinutes",
                        "listingScope",
                        "on",
                    ]
                }
                for r in data.get("rules", [])
            ],
            fired=[
                {
                    "id": a.get("id"),
                    "rule": a.get("ruleName"),
                    "project": a.get("p"),
                    "type": a.get("type"),
                    "title": render.clean(a.get("title"), 200),
                    "at": render.iso(a.get("at")),
                    "evidence": a.get("evidence"),
                    "untrusted_content": True,
                }
                for a in fired[-max(1, min(int(limit), 100)) :]
            ],
        )

    @tool(READ)
    def tracker_digest(date: str | None = None) -> dict:
        """Daily digest (source excerpts, up to three per project) for `date` (YYYY-MM-DD,
        local day). Defaults to yesterday; computed live if the collector has not stored it."""
        stored = reader.digests()
        if date and date in stored:
            digest = stored[date]
        elif not date and stored:
            digest = stored[sorted(stored)[-1]]
        else:
            digest = make_digest(reader.curated(), reader.projects())
        items = [
            {
                "projects": x.get("projectNames"),
                "text": render.clean(x.get("detail") or x.get("title"), 400),
                "url": render.https(x.get("url")),
                "published_at": render.iso(x.get("publishedAt")),
                "quality": x.get("qualityScore"),
                "untrusted_content": True,
            }
            for x in digest.get("items", [])
        ]
        return render.fit(
            envelope(
                date=digest.get("date"),
                method=digest.get("method"),
                eligible=digest.get("eligibleCount"),
                items=items,
            ),
            "items",
        )

    @tool(READ)
    def tracker_status() -> dict:
        """Collector health: last write, per-collector timings and errors, per-project
        source status, RSS subscriptions and credential presence (never the value)."""
        live = reader.live()
        return envelope(
            collectors={
                name: {
                    "last_completed": render.iso(c.get("lastCompletedAt")),
                    "last_error": c.get("lastError"),
                    "last_error_at": render.iso(c.get("lastErrorAt")),
                }
                for name, c in live.get("collectors", {}).items()
            },
            sources={
                pid: {name: s.get("status") for name, s in statuses.items()}
                for pid, statuses in live.get("sources", {}).items()
            },
            rss={
                p["id"]: [
                    {
                        "id": s.get("id"),
                        "label": s.get("label"),
                        "url": s.get("url"),
                        "enabled": s.get("enabled"),
                        "status": s.get("status"),
                    }
                    for s in reader.rss(p["id"]).get("sources", [])
                ]
                for p in reader.projects()
            },
            pending_commands=len(list(paths.spool.glob("*.json")))
            if paths.spool.exists()
            else 0,
        )

    @tool(READ)
    def tracker_command_result(command_id: str) -> dict:
        """Outcome of a previously queued write command."""
        result = spool.results(paths.store).get(command_id)
        if not result:
            return {"command_id": command_id, "status": "queued_or_unknown"}
        return {"command_id": command_id, **result}

    # ---------------- lookups through the collector ----------------

    @tool(LOOKUP)
    async def tracker_search_projects(query: str) -> dict:
        """Search CoinGecko (via the collector) for a project to add; returns candidate
        coin ids, names, symbols and market-cap rank."""
        return await command("search_projects", {"query": query})

    @tool(LOOKUP)
    async def tracker_prepare_project(coin_id: str) -> dict:
        """Fetch CoinGecko details (name, symbol, homepage, X account) for a coin id so
        the user can review them before tracker_add_project."""
        return await command("prepare_project", {"coinId": coin_id})

    # ---------------- write tools (approval required) ----------------

    @tool(WRITE)
    async def tracker_add_project(
        name: str,
        symbol: str,
        x_account: str = "",
        website: str = "",
        coin_id: str = "",
        aliases: list[str] | None = None,
        contracts: list[str] | None = None,
        exclude_terms: list[str] | None = None,
        rootdata_url: str = "",
    ) -> dict:
        """Add a project to the watchlist (max 20). Aliases, contract addresses and
        exclude terms refine news matching; rootdata_url (a RootData project page whose
        X link matches x_account) enables team discovery."""
        return await command(
            "add_project",
            {
                "name": name,
                "symbol": symbol,
                "account": x_account,
                "website": website,
                "coinId": coin_id,
                "aliases": aliases or [],
                "contracts": contracts or [],
                "excludeTerms": exclude_terms or [],
                "rootdataUrl": rootdata_url,
            },
        )

    @tool(DESTRUCTIVE)
    async def tracker_remove_project(project: str) -> dict:
        """Stop tracking a project and drop its collected events."""
        return await command(
            "remove_project", {"projectId": reader.project(project)["id"]}
        )

    @tool(WRITE)
    async def tracker_add_team_member(
        project: str, x_account: str, evidence_url: str, role: str = "团队成员"
    ) -> dict:
        """Link an X account to a project's team. evidence_url (https) must document the
        role; the member is labelled unverified."""
        return await command(
            "add_team_member",
            {
                "projectId": reader.project(project)["id"],
                "account": x_account,
                "evidence": evidence_url,
                "role": role,
            },
        )

    @tool(WRITE)
    async def tracker_set_rootdata_source(project: str, url: str) -> dict:
        """Set the RootData project page used for team discovery. The page's X link must
        match the project's official X account."""
        return await command(
            "set_rootdata_source",
            {"projectId": reader.project(project)["id"], "url": url},
        )

    @tool(WRITE)
    async def tracker_rss(
        project: str,
        action: Literal["add", "toggle", "discover", "economy"],
        url: str = "",
        label: str = "",
        source_id: str = "",
        enabled: bool = True,
    ) -> dict:
        """Manage free RSS/Atom sources: add a feed url (GitHub, Medium, Mirror and
        Telegram links are converted), toggle a source by id, discover feeds from the
        project website, or set economy mode (skip paid keyword search while RSS is healthy)."""
        pid = reader.project(project)["id"]
        if action == "add":
            return await command(
                "add_rss_source", {"projectId": pid, "url": url, "label": label}
            )
        if action == "discover":
            return await command("discover_rss", {"projectId": pid})
        if action == "economy":
            return await command(
                "rss_action",
                {"projectId": pid, "action": "economy", "enabled": enabled},
            )
        return await command("rss_action", {"projectId": pid, "id": source_id})

    @tool(WRITE)
    async def tracker_upsert_alert_rule(
        project: str,
        type: RuleType,
        name: str,
        threshold: float = 5,
        period: Literal["1h", "4h", "1d", "24h", "event"] | None = None,
        cooldown_minutes: int = 60,
        listing_scope: Literal["all", "listing"] = "all",
        enabled: bool = True,
        rule_id: str | None = None,
    ) -> dict:
        """Create or update an alert rule (max 40). Types: price (|24h change| >= threshold
        %), oi (|1h OI change| >= threshold %), level (close crosses above threshold),
        ema200 / ema (close crosses EMA200 / both EMAs; period 1h/4h/1d), combo (EMA cross
        and 1h OI >= threshold %), news (important news), listing / funding / liquidation
        (threshold = min USD, 0 = any) / flow (OpenNews events). Closed-candle confirmation;
        alerts fire only for events after the rule is created."""
        payload = {
            "p": reader.project(project)["id"],
            "type": type,
            "name": name,
            "threshold": threshold,
            "period": period or default_period(type),
            "cooldownMinutes": cooldown_minutes,
            "listingScope": listing_scope,
            "on": enabled,
        }
        if rule_id:
            payload["id"] = rule_id
        return await command("upsert_rule", payload)

    @tool(DESTRUCTIVE)
    async def tracker_alert_rule_action(
        rule_id: str, action: Literal["toggle", "delete"]
    ) -> dict:
        """Pause/resume (toggle) or delete an alert rule."""
        return await command("rule_action", {"id": rule_id, "action": action})

    @tool(WRITE)
    async def tracker_watch_account(
        x_account: str,
        projects: list[str],
        note: str = "",
        remove: bool = False,
    ) -> dict:
        """Add (or remove) an X account to the opinion journal for the given projects,
        regardless of follower count (max 20 accounts). Does not follow anyone on X."""
        if remove:
            return await command("unwatch_account", {"account": x_account})
        ids = [reader.project(p)["id"] for p in projects]
        return await command(
            "watch_account", {"account": x_account, "projectIds": ids, "note": note}
        )

    @tool(WRITE)
    async def tracker_viewpoint_alerts(project: str, enabled: bool) -> dict:
        """Enable or disable stance-change records for a project's opinion journal."""
        return await command(
            "viewpoint_alerts",
            {"projectId": reader.project(project)["id"], "enabled": enabled},
        )

    @tool(WRITE)
    async def tracker_track_event(
        project: str, event_id: str, stop: bool = False
    ) -> dict:
        """Start (or stop) tracking price change 1h/24h/7d after an event, from a fresh
        Binance price at the time of the request. Not a performance claim."""
        pid = reader.project(project)["id"]
        if stop:
            return await command("untrack_event", {"id": event_id + ":" + pid})
        return await command("track_event", {"projectId": pid, "eventId": event_id})

    @tool(WRITE)
    async def tracker_request_refresh(project: str | None = None) -> dict:
        """Ask the collector to re-collect one project (or all) now. Rate limited to once
        per 5 minutes per project; consumes provider quota."""
        payload = {"projectId": reader.project(project)["id"]} if project else {}
        return await command("refresh", payload)

    @tool(WRITE)
    async def tracker_set_calendar_mapping(
        project: str, coingecko_slug: str = "", defillama_protocol_id: str = ""
    ) -> dict:
        """Map a project to its DefiLlama protocol id so disclosed funding rounds are
        collected (requires the collector's DefiLlama key)."""
        return await command(
            "set_calendar_mapping",
            {
                "projectId": reader.project(project)["id"],
                "slug": coingecko_slug,
                "protocolId": defillama_protocol_id,
            },
        )

    return mcp
