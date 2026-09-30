"""Local daily digests. Outbound delivery is handled by Hermes, never by this module."""

import datetime as dt, json, re, threading, time
from pathlib import Path
from crypto_tracker.store import jsonstore


def excerpt(text, limit=180):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    sentence = re.match(r"^.{12,180}?[。！？.!?](?:\s|$)", text)
    return sentence[0].strip() if sentence else text[:limit] + "…"


def make_digest(rows, projects, current=None):
    current = current or dt.datetime.now().astimezone()
    day = current.date() - dt.timedelta(days=1)
    start = dt.datetime.combine(day, dt.time.min).astimezone()
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min).astimezone()
    catalog = {p["id"]: p for p in projects}
    picked = []
    counts = {}
    eligible = [
        e
        for e in rows
        if not e.get("lowInformation")
        and e.get("qualityScore", 0) >= 30
        and start.timestamp() * 1000
        <= (e.get("publishedAt") or 0)
        < end.timestamp() * 1000
    ]
    for e in sorted(
        eligible,
        key=lambda e: (-e.get("qualityScore", 0), -(e.get("publishedAt") or 0)),
    ):
        pids = [p for p in e.get("projectIds", [e["p"]]) if p in catalog]
        if not pids or not any(counts.get(p, 0) < 3 for p in pids):
            continue
        for p in pids:
            counts[p] = counts.get(p, 0) + 1
        picked.append(
            {
                "id": e["id"],
                "projectNames": [catalog[p]["name"] for p in pids],
                "title": excerpt(e.get("summary") or e["title"]),
                "titleZh": excerpt(e.get("summaryZh") or e.get("titleZh")) or None,
                "detail": e.get("summary") or e["title"],
                "detailZh": e.get("summaryZh"),
                "url": e.get("url"),
                "publishedAt": e.get("publishedAt"),
                "qualityScore": e.get("qualityScore"),
            }
        )
    return {
        "date": str(day),
        "generatedAt": int(current.timestamp() * 1000),
        "timeZone": str(current.tzinfo),
        "items": picked,
        "eligibleCount": len(eligible),
        "method": "原文要点摘录，非 AI 推断",
    }


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {"outbox": {}, "digestHour": 8, "digests": {}}
        self.started = int(time.time() * 1000)
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except (ValueError, OSError):
                pass

    def save(self):
        jsonstore.write(self.path, self.data)

    def status(self):
        # Outbound delivery is owned by Hermes cron; this reader never pushes itself.
        with self.lock:
            return {
                "enabled": False,
                "status": "由 Hermes 网关推送；本地阅读器不直接外发",
                "digestHour": self.data["digestHour"],
                "lastDigestAt": self.data.get("lastDigestAt"),
                "deliveryResults": [],
            }

    def set_hour(self, hour):
        if type(hour) != int or not 0 <= hour <= 23:
            raise ValueError("请选择 0–23 点")
        with self.lock:
            self.data["digestHour"] = hour
            self.save()

    def tick(self, rows, projects, alerts, current=None):
        """Persist yesterday's digest once per day after the configured hour."""
        current = current or dt.datetime.now().astimezone()
        now = int(current.timestamp() * 1000)
        with self.lock:
            day = str(current.date() - dt.timedelta(days=1))
            if (
                current.hour >= self.data["digestHour"]
                and day not in self.data["digests"]
            ):
                digest = make_digest(rows, projects, current)
                self.data["digests"][day] = digest
                self.data["lastDigestAt"] = now
                self.data["digests"] = dict(sorted(self.data["digests"].items())[-14:])
                self.save()
