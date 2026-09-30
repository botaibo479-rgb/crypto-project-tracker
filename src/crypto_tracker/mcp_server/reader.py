"""Read-only view of the collector's store. The MCP server never writes it."""

import os

from crypto_tracker.core import viewpoints
from crypto_tracker.core.event_clusters import cluster
from crypto_tracker.core.events import now
from crypto_tracker.core.news_quality import curate
from crypto_tracker.core.reader_quality import presentation
from crypto_tracker.store import jsonstore, projects as project_store

STALE_MS = 5 * 60000


class Reader:
    def __init__(self, paths):
        self.paths = paths
        self._curated = (None, None)

    def json(self, name, default):
        return jsonstore.read(self.paths.file(name), default) or default

    def live(self):
        return self.json("live-cache.json", {})

    def projects(self):
        live = self.live()
        if live.get("projects"):
            return live["projects"]
        return project_store.active(
            project_store.load(self.paths.file("projects.json"))
        )

    def project(self, pid):
        pid = str(pid or "").strip().lower()
        for p in self.projects():
            if pid in (p["id"].lower(), p["symbol"].lower(), p.get("name", "").lower()):
                return p
        raise ValueError(
            "未知项目 %r；可用：%s" % (pid, ", ".join(p["id"] for p in self.projects()))
        )

    def curated(self):
        """Curated, clustered events, cached until live-cache.json changes."""
        path = self.paths.file("live-cache.json")
        try:
            stamp = os.stat(path).st_mtime_ns
        except FileNotFoundError:
            return []
        key, value = self._curated
        if key == stamp:
            return value
        live = self.live()
        projects = live.get("projects") or self.projects()
        value = presentation(
            cluster(curate(list(live.get("events", [])), projects=projects))
        )
        self._curated = (stamp, value)
        return value

    def signals(self):
        return self.json("intelligence.json", {}).get("events", [])

    def calendar(self):
        return self.json("intelligence.json", {}).get("calendar", {})

    def alerts(self):
        return self.json("alerts.json", {"rules": [], "alerts": []})

    def digests(self):
        return self.json("delivery.json", {}).get("digests", {})

    def viewpoints(self, pid):
        return viewpoints.Store(self.paths.file("viewpoints.json")).snapshot(pid, now())

    def rss(self, pid):
        return self.json("public-sources.json", {}).get("projects", {}).get(pid, {})

    def funding(self, pid):
        items = self.json("project-calendar.json", {}).get("items", [])
        return [i for i in items if i.get("p") == pid and i.get("kind") == "funding"]

    def freshness(self):
        live = self.live()
        persisted = live.get("persistedAt")
        return {
            "collector_last_write": persisted,
            "stale": not persisted or now() - persisted > STALE_MS,
            "credential": live.get("credential", {}),
        }
