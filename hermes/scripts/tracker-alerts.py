"""Hermes no-agent cron script: print new crypto-tracker alerts for delivery.

Install to ~/.hermes/scripts/ and schedule:
  hermes cron create "every 5m" --no-agent --script tracker-alerts.py \
    --deliver telegram --name crypto-tracker-alerts

Contract (Hermes script-only jobs): stdout is delivered verbatim; empty stdout is
a silent tick; a non-zero exit is delivered as an error. Standard library only,
read-only access to the collector store. Delivery state lives next to this
script, so every alert is printed at most once. The first run only records a
watermark, so history is never replayed.

TRACKER_HOME defaults to /var/lib/crypto-tracker (then ~/.local/share/crypto-tracker).
"""

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

WINDOW_MS = 3 * 3600000  # never deliver alerts older than this
STALE_MS = 15 * 60000
STALE_REPEAT_MS = 6 * 3600000
MAX_PER_RUN = 10
KEEP_IDS = 2000
HIDDEN = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]"
)


def home():
    if os.environ.get("TRACKER_HOME"):
        return Path(os.environ["TRACKER_HOME"])
    system = Path("/var/lib/crypto-tracker")
    return system if system.exists() else Path.home() / ".local/share/crypto-tracker"


def read(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_state(path, state):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def clean(text, limit=240):
    text = " ".join(HIDDEN.sub("", str(text or "")).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def when(ms):
    return dt.datetime.fromtimestamp(ms / 1000).astimezone().strftime("%m-%d %H:%M")


def https(url):
    url = str(url or "")
    return url if url.startswith("https://") else ""


def evidence_line(evidence):
    parts = []
    for key, label in [
        ("change24h", "24h 变化 %"),
        ("oiChange1h", "1h OI 变化 %"),
        ("close", "收盘"),
        ("level", "价位"),
        ("ema200", "EMA200"),
        ("amountUsd", "金额 USD"),
        ("threshold", "阈值"),
    ]:
        value = evidence.get(key)
        if isinstance(value, (int, float)):
            parts.append("%s %s" % (label, format(value, ".4g")))
    if evidence.get("source"):
        parts.append("来源 " + clean(evidence["source"], 60))
    return " · ".join(parts)


def format_alert(alert, names):
    evidence = alert.get("evidence") or {}
    lines = [
        "【Signal 提醒】%s · %s"
        % (names.get(alert.get("p"), alert.get("p")), clean(alert.get("ruleName"), 60)),
        clean(alert.get("title")),
    ]
    detail = evidence_line(evidence)
    if detail:
        lines.append(detail)
    if https(evidence.get("url")):
        lines.append(https(evidence["url"]))
    lines.append("触发于 %s（规则提醒，非投资建议）" % when(alert["at"]))
    return "\n".join(lines)


def format_change(change, names):
    before, after = change.get("before") or {}, change.get("after") or {}
    label = {"positive": "看多", "concern": "看空"}
    return "\n".join(
        [
            "【观点变化线索】%s · @%s"
            % (
                names.get(change.get("p"), change.get("p")),
                clean(after.get("account"), 30),
            ),
            "%s → %s（按明确措辞归类，未推断真实仓位）"
            % (
                label.get(before.get("stance"), "?"),
                label.get(after.get("stance"), "?"),
            ),
            https(after.get("url")),
        ]
    ).strip()


def main():
    now = int(time.time() * 1000)
    store = home() / "store"
    state_path = Path(__file__).resolve().with_name(".crypto-tracker-alerts.state.json")
    state = read(state_path, None)
    if state is None:
        write_state(state_path, {"watermark": now, "delivered": [], "staleWarnedAt": 0})
        return 0
    live = read(store / "live-cache.json", {})
    names = {p["id"]: p.get("name") or p["id"] for p in live.get("projects", [])}
    delivered = set(state.get("delivered", []))
    since = max(state.get("watermark", now), now - WINDOW_MS)
    messages = []

    alerts = read(store / "alerts.json", {}).get("alerts", [])
    for alert in sorted(alerts, key=lambda a: a.get("at", 0)):
        key = "alert:" + str(alert.get("id"))
        if (
            key in delivered
            or not isinstance(alert.get("at"), int)
            or alert["at"] <= since
        ):
            continue
        messages.append((key, format_alert(alert, names)))

    for change in read(store / "viewpoints.json", {}).get("changes", []):
        at = change.get("at", 0)
        key = "viewpoint:%s:%s" % (
            change.get("p"),
            (change.get("after") or {}).get("id"),
        )
        if key in delivered or at <= since:
            continue
        messages.append((key, format_change(change, names)))

    persisted = live.get("persistedAt") or 0
    if (
        now - persisted > STALE_MS
        and now - state.get("staleWarnedAt", 0) > STALE_REPEAT_MS
    ):
        minutes = (now - persisted) // 60000 if persisted else None
        messages.append(
            (
                None,
                "【采集器告警】crypto-tracker 采集器%s未更新数据，提醒可能缺失。请检查 systemctl status crypto-tracker-collector。"
                % ("已 %d 分钟" % minutes if minutes is not None else "尚未"),
            )
        )
        state["staleWarnedAt"] = now

    shown = messages[:MAX_PER_RUN]
    if len(messages) > MAX_PER_RUN:
        shown.append(
            (
                None,
                "另有 %d 条提醒未展开，可在 Hermes 中调用 tracker_alerts 查看。"
                % (len(messages) - MAX_PER_RUN),
            )
        )
    for key, _ in messages:
        if key:
            delivered.add(key)
    state["delivered"] = sorted(delivered)[-KEEP_IDS:]
    write_state(state_path, state)
    if shown:
        sys.stdout.write("\n\n".join(text for _, text in shown) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PermissionError as error:
        sys.stderr.write("crypto-tracker store not readable: %s\n" % error.filename)
        sys.exit(1)
