"""Background collection (formerly the web reader's server threads).

The collector is the only process that holds the provider token and the only
writer of TRACKER_HOME/store. It never listens on a port.
"""

import concurrent.futures as cf
import logging
import re
import threading
import time
import urllib.error

from crypto_tracker.core import alerts, digest, viewpoints
from crypto_tracker.core.collection_state import merge_news, social_result
from crypto_tracker.core.event_clusters import cluster
from crypto_tracker.core.events import news_event, now, timestamp
from crypto_tracker.core.news_quality import curate
from crypto_tracker.core.reader_quality import presentation
from crypto_tracker.net.http import error_label
from crypto_tracker.sources import (
    binance,
    defillama,
    intelligence,
    official_sites,
    opennews,
    rootdata,
    rss,
    social,
    team,
)
from crypto_tracker.store import jsonstore, projects as project_store, spool

log = logging.getLogger(__name__)

LIVE = "live-cache.json"
CADENCE = {
    "market": 60,
    "news": 1800,
    "social": 1800,
    "intelligence": 300,
    "alerts": 20,
    "digest": 60,
    "logos": 21600,
    "rootdata": 3600,
    "calendar": 21600,
    "spool": 2,
}
REFRESH_COOLDOWN_MS = 300000


def curated(events, projects):
    return presentation(cluster(curate(list(events), projects=projects)))


class Collector:
    def __init__(self, paths, request, defillama_key="", rsshub=""):
        self.paths = paths
        self.request = request
        self.defillama_key = defillama_key
        self.lock = threading.RLock()
        self.projects = project_store.load(paths.file("projects.json"))
        self.data = {
            "markets": {},
            "events": [],
            "sources": {},
            "social": {},
            "updatedAt": None,
            "refreshing": True,
            "collectors": {},
            "intelligenceEvents": [],
        }
        old = jsonstore.read(paths.file(LIVE), {}) or {}
        self.data.update(
            {
                k: old[k]
                for k in [
                    "markets",
                    "events",
                    "sources",
                    "social",
                    "updatedAt",
                    "collectors",
                ]
                if k in old
            }
        )
        social.configure(paths.file("avatars.json"))
        self.intelligence = intelligence.Store(paths.file("intelligence.json"))
        self.digests = digest.Store(paths.file("delivery.json"))
        self.alerts = alerts.Store(paths.file("alerts.json"))
        self.rss = rss.Store(paths.file("public-sources.json"), rsshub)
        self.calendar = defillama.Store(paths.file("project-calendar.json"))
        self.viewpoints = viewpoints.Store(paths.file("viewpoints.json"))
        self.charts = binance.Charts(request)
        self.refreshed = {}
        self.handlers = {
            "search_projects": self.cmd_search_projects,
            "prepare_project": self.cmd_prepare_project,
            "add_project": self.cmd_add_project,
            "remove_project": self.cmd_remove_project,
            "add_team_member": self.cmd_add_team_member,
            "set_rootdata_source": self.cmd_set_rootdata_source,
            "add_rss_source": self.cmd_add_rss_source,
            "rss_action": self.cmd_rss_action,
            "discover_rss": self.cmd_discover_rss,
            "upsert_rule": self.cmd_upsert_rule,
            "rules_template": self.cmd_rules_template,
            "rule_action": self.cmd_rule_action,
            "watch_account": self.cmd_watch_account,
            "unwatch_account": self.cmd_unwatch_account,
            "viewpoint_alerts": self.cmd_viewpoint_alerts,
            "track_event": self.cmd_track_event,
            "untrack_event": self.cmd_untrack_event,
            "refresh": self.cmd_refresh,
            "set_calendar_mapping": self.cmd_set_calendar_mapping,
        }
        assert set(self.handlers) == spool.KINDS

    # ---------- state ----------

    def active(self):
        with self.lock:
            return [dict(p) for p in project_store.active(self.projects)]

    def project_ids(self):
        return [p["id"] for p in self.active()]

    def project(self, pid):
        with self.lock:
            found = project_store.find(self.projects, pid)
            return dict(found) if found else None

    def persist(self):
        with self.lock:
            snapshot = {
                **self.data,
                "projects": project_store.active(self.projects),
                "credential": {
                    "opennews": "set" if self.request.has_token else "missing"
                },
                "persistedAt": now(),
            }
            jsonstore.write(self.paths.file(LIVE), snapshot)

    def save_projects(self):
        with self.lock:
            project_store.save(self.paths.file("projects.json"), self.projects)

    def status(self, name, **fields):
        with self.lock:
            self.data["collectors"].setdefault(name, {}).update(fields)

    def store_news(self, pid, items, statuses):
        with self.lock:
            merged, sources = merge_news(
                [e for e in self.data["events"] if e["p"] == pid],
                items,
                statuses,
                self.data["sources"].get(pid, {}),
                now(),
            )
            self.data["events"] = [
                e for e in self.data["events"] if e["p"] != pid
            ] + merged
            self.data["sources"][pid] = sources

    # ---------- collection units ----------

    def collect_market(self):
        self.status("market", running=True, lastStartedAt=now(), intervalSeconds=60)
        with self.lock:
            self.data["refreshing"] = True
        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(binance.market, p, self.request) for p in self.active()
            ]
            for future in cf.as_completed(futures):
                try:
                    pid, result = future.result()
                    with self.lock:
                        self.data["markets"][pid] = result
                except Exception as e:
                    self.status("market", lastError=error_label(e), lastErrorAt=now())
        with self.lock:
            self.data["updatedAt"] = now()
            self.data["refreshing"] = False
            markets = dict(self.data["markets"])
        self.viewpoints.sample(markets, now())
        self.status("market", running=False, lastCompletedAt=now())

    def refresh_news(self, p):
        free_events = self.rss.collect(p, news_event)
        events, statuses = opennews.provider_news(
            p, self.request, self.request.has_token, self.rss
        )
        events.extend(free_events)
        statuses["免费订阅"] = {
            "status": "ok" if self.rss.healthy(p["id"]) else "limited",
            "count": len(free_events),
            "message": "仅采集已确认订阅源；订阅管理可查看各源状态",
        }
        if self.request.has_token:
            team_events, team_status = team.collect(
                p, self.request, timestamp, news_event
            )
            events.extend(team_events)
            statuses["团队 X"] = team_status
        else:
            statuses["团队 X"] = {
                "status": "missing_credential",
                "message": "未连接团队推文采集",
            }
        try:
            try:
                public = official_sites.public_news(p, self.request)
            except (TimeoutError, urllib.error.URLError):
                public = official_sites.public_news(p, self.request)
            events.extend(public)
            statuses["官网资讯"] = {
                "status": "ok" if public else "limited",
                "count": len(public),
                "lastSuccessAt": now() if public else None,
                "message": (
                    "仅 Infrastructure 分类，发布时间未取得"
                    if p["id"] == "near"
                    else "官网索引 / RSS，非全网覆盖"
                )
                if public
                else "此官网未接入自动文章采集",
            }
        except Exception as e:
            statuses["官网资讯"] = {"status": "error", "message": error_label(e)}
        return p["id"], events, statuses

    def collect_news(self):
        self.status("news", running=True, lastStartedAt=now(), intervalSeconds=1800)
        with cf.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.refresh_news, p) for p in self.active()]
            for future in cf.as_completed(futures):
                try:
                    self.store_news(*future.result())
                except Exception as e:
                    self.status("news", lastError=error_label(e), lastErrorAt=now())
        self.status(
            "news", running=False, lastCompletedAt=now(), nextRunAt=now() + 1800000
        )

    def collect_social_project(self, project):
        if not self.request.has_token:
            result = {
                "status": "missing_credential",
                "message": "未配置 OPENNEWS_TOKEN；近期讨论者尚未采集",
                "discussants": [],
            }
            with self.lock:
                self.data["social"][project["id"]] = social_result(
                    self.data["social"].get(project["id"], {}), result, now()
                )
            return
        try:
            result = social.discover(
                project, self.request, timestamp, self.viewpoints.watches(project["id"])
            )
        except Exception as e:
            result = {"status": "error", "message": error_label(e), "discussants": []}
        self.viewpoints.ingest(project, result, now())
        with self.lock:
            self.data["social"][project["id"]] = social_result(
                self.data["social"].get(project["id"], {}), result, now()
            )

    def collect_social(self):
        self.status("social", running=True, lastStartedAt=now(), intervalSeconds=1800)
        for p in self.active():
            self.collect_social_project(p)
        self.status(
            "social", running=False, lastCompletedAt=now(), nextRunAt=now() + 1800000
        )

    def collect_intelligence(self):
        self.intelligence.collect(
            self.active(), self.request, timestamp, self.request.has_token
        )
        with self.lock:
            self.data["intelligenceEvents"] = self.intelligence.snapshot()["events"]

    def evaluate_alerts(self):
        projects = self.active()
        with self.lock:
            markets = dict(self.data["markets"])
            events = list(self.data["events"])
        grouped = curated(events, projects)
        news = [
            {**e, "p": pid} for e in grouped for pid in e.get("projectIds", [e["p"]])
        ]
        pairs = {
            (r["p"], r["period"])
            for r in self.alerts.snapshot()["rules"]
            if r["on"]
            and r["type"] in {"ema", "ema200", "level", "combo"}
            and r["period"] != "4h"
        }
        for pid, period in pairs:
            try:
                markets[(pid, period)] = alerts.chart_market(
                    markets.get(pid), self.charts.get(self.project(pid), period)
                )
            except Exception:
                markets[(pid, period)] = {}
        self.alerts.tick(markets, news + self.intelligence.snapshot()["events"], now())

    def build_digest(self):
        projects = self.active()
        with self.lock:
            events = list(self.data["events"])
        self.digests.tick(
            curated(events, projects), projects, self.alerts.snapshot()["alerts"]
        )

    def collect_logos(self):
        for p in self.active():
            if not p.get("account"):
                continue
            account = {"account": p["account"]}
            social.enrich_avatars([account] + p.get("team", []), self.request)
            with self.lock:
                target = project_store.find(self.projects, p["id"])
                if target is None:
                    continue
                if account.get("profile"):
                    target["accountProfile"] = account["profile"]
                if account.get("avatar"):
                    target["logo"] = account["avatar"]
                    target["logoSource"] = "https://x.com/" + p["account"]

    def collect_rootdata(self, project):
        try:
            result = rootdata.refresh(project, self.request, now())
            result, additions = rootdata.resolve_candidates(
                project, result, self.request, now()
            )
        except Exception:
            result = {
                **project.get("rootdataObservation", {}),
                "status": "error",
                "lastAttemptAt": now(),
            }
            additions = []
        with self.lock:
            target = project_store.find(self.projects, project["id"])
            if target is not None and target.get("teamSourceUrl") == project.get(
                "teamSourceUrl"
            ):
                target["rootdataObservation"] = result
                known = {
                    a["account"].lower()
                    for a in target.get("team", [])
                    if a.get("account")
                }
                target.setdefault("team", []).extend(
                    a for a in additions if a["account"].lower() not in known
                )
                self.save_projects()

    def collect_rootdata_due(self):
        for project in self.active():
            if not project.get("teamSourceUrl"):
                continue
            last = project.get("rootdataObservation", {}).get("lastAttemptAt", 0)
            if now() - last >= 86400000:
                self.collect_rootdata(project)

    def collect_calendar(self):
        self.calendar.collect(self.active(), self.defillama_key)

    def collect_free_project(self, p):
        items = self.rss.collect(p, news_event)
        with self.lock:
            statuses = dict(self.data["sources"].get(p["id"], {}))
        statuses["免费订阅"] = {
            "status": "ok" if self.rss.healthy(p["id"]) else "limited",
            "count": len(items),
            "message": "已确认订阅源",
        }
        self.store_news(p["id"], items, statuses)

    def collect_project(self, project):
        """Everything for one project; used after add and for on-demand refresh."""
        if project.get("account"):
            account = {"account": project["account"]}
            social.enrich_avatars([account], self.request)
            if account.get("avatar"):
                with self.lock:
                    target = project_store.find(self.projects, project["id"])
                    if target is not None:
                        target["logo"] = account["avatar"]
                        target["logoSource"] = "https://x.com/" + project["account"]
        pid, result = binance.market(project, self.request)
        with self.lock:
            self.data["markets"][pid] = result
        self.store_news(*self.refresh_news(project))
        self.collect_social_project(project)
        self.persist()

    # ---------- spool commands ----------

    def process_spool(self):
        for ident, command, error in spool.pending(self.paths.spool):
            kind = command["kind"] if command else None
            if error:
                spool.record(self.paths.store, ident, kind, "error", "无效命令文件")
                continue
            try:
                value = self.handlers[kind](command["payload"])
                spool.record(self.paths.store, ident, kind, "ok", value)
            except ValueError as e:
                spool.record(self.paths.store, ident, kind, "error", str(e)[:200])
            except Exception as e:
                log.warning("command %s failed: %s", kind, type(e).__name__)
                spool.record(self.paths.store, ident, kind, "error", error_label(e))

    def _background(self, target, *args):
        threading.Thread(target=self._safe, args=(target, *args), daemon=True).start()

    def _safe(self, target, *args):
        try:
            target(*args)
        except Exception as e:
            log.warning(
                "%s failed: %s", getattr(target, "__name__", "task"), type(e).__name__
            )

    def _require(self, pid):
        project = self.project(pid)
        if not project:
            raise ValueError("项目不存在")
        return project

    def cmd_search_projects(self, payload):
        return project_store.search_projects(
            str(payload.get("query", "")), self.request
        )

    def cmd_prepare_project(self, payload):
        return project_store.prepare_project(payload, self.request)

    def cmd_add_project(self, payload):
        project = project_store.confirm_project(payload)
        if payload.get("rootdataUrl"):
            project["teamSourceUrl"] = rootdata.validate_source(
                project, str(payload["rootdataUrl"]).strip(), self.request
            )
        with self.lock:
            project_store.add(self.projects, project)
            self.save_projects()
        if project.get("teamSourceUrl"):
            self._background(self.collect_rootdata, dict(project))
        self._background(self.rss.discover, dict(project))
        self._background(self.collect_project, dict(project))
        return {"project": project}

    def cmd_remove_project(self, payload):
        with self.lock:
            project_store.remove(self.projects, payload.get("projectId"))
            self.save_projects()
            pid = payload.get("projectId")
            self.data["events"] = [e for e in self.data["events"] if e["p"] != pid]
            self.data["markets"].pop(pid, None)
        self.persist()
        return {"removed": payload.get("projectId")}

    def cmd_add_team_member(self, payload):
        with self.lock:
            project_store.add_team_member(
                self.projects,
                payload.get("projectId"),
                payload.get("account", ""),
                payload.get("role", "团队成员"),
                payload.get("evidence", ""),
            )
            self.save_projects()
        return {"ok": True}

    def cmd_set_rootdata_source(self, payload):
        project = self._require(payload.get("projectId"))
        source = rootdata.validate_source(
            project, str(payload.get("url", "")).strip(), self.request
        )
        with self.lock:
            target = project_store.find(self.projects, project["id"])
            if target.get("teamSourceUrl") != source:
                target.pop("rootdataObservation", None)
            target["teamSourceUrl"] = source
            self.save_projects()
            project = dict(target)
        self._background(self.collect_rootdata, project)
        return {"teamSourceUrl": source}

    def cmd_add_rss_source(self, payload):
        project = self._require(payload.get("projectId"))
        self.rss.add(
            project["id"], str(payload.get("url", "")), str(payload.get("label", ""))
        )
        self._background(self.collect_free_project, project)
        return {"ok": True}

    def cmd_rss_action(self, payload):
        project = self._require(payload.get("projectId"))
        self.rss.action(project["id"], payload)
        return {"ok": True}

    def cmd_discover_rss(self, payload):
        project = self._require(payload.get("projectId"))
        self._background(self.rss.discover, project)
        return {"started": True}

    def cmd_upsert_rule(self, payload):
        return {"rule": self.alerts.upsert(payload, self.project_ids())}

    def cmd_rules_template(self, payload):
        return {"rules": self.alerts.batch(payload, self.project_ids())}

    def cmd_rule_action(self, payload):
        self.alerts.action(payload.get("id"), payload.get("action"))
        return {"ok": True}

    def cmd_watch_account(self, payload):
        self.viewpoints.configure({**payload, "action": "watch"}, self.project_ids())
        return {"ok": True}

    def cmd_unwatch_account(self, payload):
        self.viewpoints.configure({**payload, "action": "remove"}, self.project_ids())
        return {"ok": True}

    def cmd_viewpoint_alerts(self, payload):
        self.viewpoints.configure(
            {
                "action": "alerts",
                "projectId": payload.get("projectId"),
                "enabled": payload.get("enabled") is True,
            },
            self.project_ids(),
        )
        return {"ok": True}

    def cmd_track_event(self, payload):
        pid = payload.get("projectId")
        with self.lock:
            events = list(self.data["events"])
            market = dict(self.data["markets"].get(pid, {}))
        event = next(
            (
                e
                for e in cluster(curate(events, projects=self.active()))
                if str(e["id"]) == str(payload.get("eventId"))
                and pid in e.get("projectIds", [e["p"]])
            ),
            None,
        )
        if not event:
            raise ValueError("原始事件不存在或项目不匹配")
        self.viewpoints.track(event, pid, market, now())
        return {"ok": True}

    def cmd_untrack_event(self, payload):
        self.viewpoints.remove_track(payload.get("id"))
        return {"ok": True}

    def cmd_refresh(self, payload):
        pid = payload.get("projectId")
        targets = [self._require(pid)] if pid else self.active()
        started = []
        for project in targets:
            last = self.refreshed.get(project["id"], 0)
            if now() - last < REFRESH_COOLDOWN_MS:
                continue
            self.refreshed[project["id"]] = now()
            self._background(self.collect_project, project)
            started.append(project["id"])
        return {"started": started, "cooldownSeconds": REFRESH_COOLDOWN_MS // 1000}

    def cmd_set_calendar_mapping(self, payload):
        slug = str(payload.get("slug", ""))
        ident = str(payload.get("protocolId", ""))
        if slug and not re.fullmatch("[a-z0-9-]{1,100}", slug):
            raise ValueError("CoinGecko 标识无效")
        if ident and not re.fullmatch("[a-zA-Z0-9#_-]{1,100}", ident):
            raise ValueError("DefiLlama 协议 ID 无效")
        with self.lock:
            target = project_store.find(self.projects, payload.get("projectId"))
            if target is None:
                raise ValueError("项目不存在")
            target.update(calendarSlug=slug, calendarProtocolId=ident)
            self.save_projects()
        if self.defillama_key:
            self._background(self.collect_calendar)
        return {"ok": True}

    # ---------- scheduling ----------

    def due(self, name):
        with self.lock:
            last = self.data["collectors"].get(name, {}).get("lastCompletedAt", 0)
        return now() - last >= CADENCE[name] * 1000

    def run_once(self):
        """One full pass, for `--once` and tests."""
        for step in (
            self.process_spool,
            self.collect_market,
            self.collect_news,
            self.collect_social,
            self.collect_intelligence,
            self.collect_rootdata_due,
            self.evaluate_alerts,
            self.build_digest,
        ):
            self._safe(step)
        self.persist()

    def loop(self, name, step, persist=True):
        def run():
            while True:
                started = time.time()
                try:
                    if name in ("news", "social") and not self._needs(name):
                        time.sleep(min(60, CADENCE[name]))
                        continue
                    step()
                    self.status(name, lastCompletedAt=now())
                    if persist:
                        self.persist()
                except Exception as e:
                    self.status(name, lastError=error_label(e), lastErrorAt=now())
                    log.warning("%s loop failed: %s", name, type(e).__name__)
                delay = max(1, CADENCE[name] - (time.time() - started))
                if name in ("news", "social"):
                    delay = min(delay, 60)
                time.sleep(delay)

        threading.Thread(target=run, name=name, daemon=True).start()

    def _needs(self, name):
        if name == "social" and any(
            not self.viewpoints.snapshot(p["id"], now())["coverage"]
            for p in self.active()
        ):
            return True
        return self.due(name)

    def run_forever(self):
        self.loop("spool", self.process_spool, persist=False)
        self.loop("market", self.collect_market)
        self.loop("news", self.collect_news)
        self.loop("social", self.collect_social)
        self.loop("logos", self.collect_logos)
        self.loop("rootdata", self.collect_rootdata_due)
        self.loop("alerts", self.evaluate_alerts, persist=False)
        self.loop("intelligence", self.collect_intelligence)
        self.loop("digest", self.build_digest, persist=False)
        self.loop("calendar", self.collect_calendar, persist=False)
        log.info("collector running; projects=%d", len(self.active()))
        while True:
            time.sleep(3600)
