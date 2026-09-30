"""Single-owner reader preferences, with field-level optimistic concurrency."""

import json, threading, re
from pathlib import Path

FIELDS = {
    "hiddenProjects",
    "pinnedProjects",
    "projectGroups",
    "projectOrder",
    "unreadProjectsOnly",
    "saved",
    "read",
    "readerViews",
    "readerFeedback",
}


def validate(values):
    if not isinstance(values, dict) or not values.keys() <= FIELDS:
        raise ValueError("偏好字段无效")
    for key, value in values.items():
        if key in ("readerViews", "readerFeedback"):
            if not isinstance(value, list) or len(value) > (
                30 if key == "readerViews" else 300
            ):
                raise ValueError("视图或反馈数量超出限制")
            for item in value:
                if not isinstance(item, dict):
                    raise ValueError("视图或反馈格式无效")
                if key == "readerViews":
                    allowed = {
                        "id",
                        "name",
                        "channels",
                        "topics",
                        "include",
                        "exclude",
                        "projectIds",
                        "savedOnly",
                        "type",
                        "minLength",
                    }
                    if (
                        not item.keys() <= allowed
                        or not isinstance(item.get("name"), str)
                        or not 1 <= len(item["name"]) <= 40
                    ):
                        raise ValueError("视图名称无效")
                    for field in (
                        "channels",
                        "topics",
                        "include",
                        "exclude",
                        "projectIds",
                    ):
                        terms = item.get(field, [])
                        if (
                            not isinstance(terms, list)
                            or len(terms) > 20
                            or any(
                                not isinstance(x, str) or len(x) > 100 for x in terms
                            )
                        ):
                            raise ValueError("筛选条件无效")
                    if type(item.get("savedOnly", False)) != bool or item.get(
                        "type", "all"
                    ) not in ("all", "news", "market", "combo"):
                        raise ValueError("筛选类型无效")
                    if (
                        type(item.get("minLength", 0)) != int
                        or not 0 <= item.get("minLength", 0) <= 10000
                    ):
                        raise ValueError("文章长度无效")
                else:
                    if not item.keys() <= {
                        "id",
                        "kind",
                        "value",
                        "projectId",
                        "eventKey",
                    } or item.get("kind") not in ("unrelated", "topic", "source"):
                        raise ValueError("反馈无效")
                    if any(
                        not isinstance(v, str) or len(v) > 2000 for v in item.values()
                    ):
                        raise ValueError("反馈值无效")
                if not isinstance(item.get("id"), str) or not re.fullmatch(
                    "[a-zA-Z0-9_-]{1,80}", item["id"]
                ):
                    raise ValueError("标识无效")
        elif key == "unreadProjectsOnly":
            if not isinstance(value, bool):
                raise ValueError("筛选值无效")
        elif key == "projectGroups":
            if (
                not isinstance(value, dict)
                or len(value) > 100
                or any(
                    not isinstance(k, str)
                    or len(k) > 100
                    or not isinstance(v, str)
                    or len(v) > 20
                    for k, v in value.items()
                )
            ):
                raise ValueError("分组无效")
        else:
            if not isinstance(value, list) or len(value) > (
                5000 if key in ("saved", "read") else 100
            ):
                raise ValueError("偏好列表过长")
            if key in ("saved", "read"):
                if any(type(x) != int or not 0 <= x <= 9007199254740991 for x in value):
                    raise ValueError("资讯标识无效")
            elif any(not isinstance(x, str) or not 1 <= len(x) <= 100 for x in value):
                raise ValueError("项目标识无效")
    return values


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {}
        if self.path.exists():
            self.data = validate(json.loads(self.path.read_text()))

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def update(self, payload):
        values = validate(payload.get("values"))
        base = payload.get("base")
        if not isinstance(base, dict) or set(base) != set(values):
            raise ValueError("缺少修改前的偏好")
        with self.lock:
            conflicts = [
                k
                for k, v in values.items()
                if self.data.get(k) != base[k] and self.data.get(k) != v
            ]
            if conflicts:
                return {"values": self.snapshot(), "conflicts": conflicts}, 409
            updated = {**self.data, **values}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(updated, ensure_ascii=False))
            tmp.replace(self.path)
            self.data = updated
            return {"values": self.snapshot()}, 200
