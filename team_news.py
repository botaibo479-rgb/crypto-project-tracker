"""Collect attributed project-related posts, never infer project facts from job titles."""

import json, re, time
from concurrent.futures import ThreadPoolExecutor
from news_quality import relevant


def project_related(project, text):
    if any(w.casefold() in text.casefold() for w in project.get("excludeTerms", [])):
        return False
    account = project.get("account", "")
    return bool(
        relevant(project["id"], text, project)
        or (account and re.search(r"(?<!\w)@" + re.escape(account) + r"\b", text, re.I))
    )


def collect(project, request, timestamp, event_factory):
    members = [
        a
        for a in project.get("team", [])
        if a.get("account") and "待核实" not in a.get("identity", "")
    ]

    def fetch(member):
        handle = member["account"]
        out = []
        status = {"account": handle, "status": "error", "count": 0}
        try:
            response = json.loads(
                request(
                    "https://ai.6551.io/open/twitter_user_tweets",
                    {
                        "username": handle,
                        "maxResults": 20,
                        "product": "Latest",
                        "includeReplies": False,
                        "includeRetweets": False,
                    },
                )
            )
            if response.get("success") is False:
                raise ValueError("provider_failure")
            rows = response.get("data", [])
            if isinstance(rows, dict):
                rows = rows.get("tweets", rows.get("list", []))
            if not isinstance(rows, list):
                raise ValueError("unexpected_response")
            now = int(time.time() * 1000)
            for row in rows:
                author = row.get("userScreenName", "")
                tid = str(row.get("id", ""))
                text = row.get("text") or ""
                date = timestamp(row.get("createdAt", ""))
                if (
                    author.lower() != handle.lower()
                    or not tid.isdigit()
                    or not date
                    or not now - 30 * 86400000 <= date <= now + 300000
                ):
                    continue
                if (
                    text.startswith("RT @")
                    or row.get("isRetweet")
                    or not project_related(project, text)
                ):
                    continue
                e = event_factory(
                    project["id"],
                    text[:140],
                    "https://x.com/" + author + "/status/" + tid,
                    date,
                    "团队 X · @" + author,
                    text,
                )
                e.update(
                    channel="team",
                    author=author,
                    authorRole=member.get("role", "团队成员"),
                    authorEvidence=member.get("evidence"),
                    matchReason="团队资料关联 + 推文明确提及项目；不是项目官方公告",
                    uncertain="团队成员个人表述，尚未独立核实；职位依据见人物资料。",
                )
                out.append(e)
            status.update(
                status="ok", count=len(out), returnedCount=len(rows), lastSuccessAt=now
            )
        except Exception:
            status["message"] = "账号采集失败；保留上次内容"
        return out, status

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, members))
    events = [e for batch, _ in results for e in batch]
    statuses = [s for _, s in results]
    success = sum(s["status"] == "ok" for s in statuses)
    return events, {
        "status": "ok"
        if members and success == len(members)
        else "partial"
        if success
        else "error"
        if members
        else "limited",
        "count": len(events),
        "accounts": statuses,
        "lastSuccessAt": int(time.time() * 1000) if success else None,
        "message": f"团队账号 {success}/{len(members)} 采集成功；每账号最多 20 条，保留近 30 天明确相关内容",
    }
