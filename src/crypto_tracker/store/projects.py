"""Watched projects: seed defaults, user additions and validation.

The collector owns projects.json; the MCP server only reads it and submits
changes through the spool.
"""

import json
import re
import urllib.parse
from pathlib import Path

from crypto_tracker import config
from crypto_tracker.core.news_quality import QUERIES
from crypto_tracker.store import jsonstore

SEED = Path(__file__).resolve().parent.parent / "seed"


def default_projects():
    return json.loads((SEED / "default_projects.json").read_text())


def merge_rootdata_team(projects):
    """Reviewed public RootData team snapshot; preserve existing official/user evidence."""
    for member in json.loads((SEED / "rootdata_team.json").read_text()):
        project = next((p for p in projects if p["id"] == member["project"]), None)
        if not project:
            continue
        project["teamSourceUrl"] = member["projectEvidence"]
        team = project.setdefault("team", [])
        existing = next(
            (a for a in team if a["account"].lower() == member["account"].lower()), None
        )
        if existing:
            existing["rootdataEvidence"] = member["evidence"]
            existing["rootdataCheckedAt"] = member["checkedAt"]
        else:
            team.append(dict(member))


def register_query(project):
    QUERIES.setdefault(
        project["id"], '"' + project["name"] + '" OR "$' + project["symbol"] + '"'
    )


def load(path):
    """All projects, including removed tombstones (filter with ``active``)."""
    projects = default_projects()
    for saved in jsonstore.read(path, []) or []:
        if not isinstance(saved, dict) or "id" not in saved:
            continue
        existing = next((p for p in projects if p["id"] == saved["id"]), None)
        if existing:
            existing.update(saved)
        else:
            projects.append(saved)
    merge_rootdata_team(projects)
    for project in projects:
        register_query(project)
    return projects


def active(projects):
    return [p for p in projects if not p.get("removed")]


def save(path, projects):
    jsonstore.write(path, projects)


def find(projects, pid):
    return next((p for p in active(projects) if p["id"] == pid), None)


def add(projects, project):
    if any(
        p["symbol"] == project["symbol"] or p["id"] == project["id"]
        for p in active(projects)
    ):
        raise ValueError("该代币已经存在")
    if len(active(projects)) >= config.MAX_PROJECTS:
        raise ValueError(f"最多支持 {config.MAX_PROJECTS} 个项目")
    projects[:] = [p for p in projects if p["id"] != project["id"]]
    projects.append(project)
    register_query(project)


def remove(projects, pid):
    project = find(projects, pid)
    if not project:
        raise ValueError("项目不存在")
    project["removed"] = True


def add_team_member(projects, pid, account, role, evidence):
    handle = str(account).removeprefix("@")
    if not re.fullmatch("[A-Za-z0-9_]{1,15}", handle):
        raise ValueError("账号格式无效")
    project = find(projects, pid)
    if not project:
        raise ValueError("项目不存在")
    team = project.setdefault("team", [])
    if any(a["account"].lower() == handle.lower() for a in team):
        raise ValueError("账号已添加")
    team.append(
        {
            "account": handle,
            "role": str(role or "团队成员")[:80],
            "evidence": clean_url(str(evidence)),
            "identity": "用户添加 · 待核实",
        }
    )


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
