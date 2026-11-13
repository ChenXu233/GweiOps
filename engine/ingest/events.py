# engine/ingest/events.py
"""Webhook 归一化事件 —— 各来源的语法到平台这一侧的唯一种说法。

适配器负责验签、解析与翻译:GitHub 的 `pull_request`、GitLab 的
`merge_request`、CNB 的 `PullRequestEvent` 在这里都只是"一次合并"。
核心不认识任何一家的字段名,只认这几个键。

事件字典:
- `kind`: issue | comment | merge | ping
- `source`: github | gitlab | cnb(适配器自己 declare 的名字)
- `repo` / `repo_id`: 仓库全名与来源侧数字 ID
- `change_id` / `number`: 来源侧的变更 ID 与人类编号(issue/MR/PR 通用)
- `title` / `body` / `action`
- `is_pull`: 这条评论是不是落在合并请求上
- `base_ref` / `head_ref` / `merge_sha`: 合并事件的基线、分支与合并提交
"""

from __future__ import annotations

from typing import Any

KINDS = ("issue", "comment", "merge", "ping")


class EventError(ValueError):
    """适配器给的事件形状不对。坏形状在入口就拒掉,不流进工作流。"""


def event(
    *,
    kind: str,
    source: str,
    repo: str = "",
    repo_id: Any = None,
    change_id: Any = None,
    number: Any = None,
    title: str = "",
    body: str = "",
    action: str = "",
    is_pull: bool = False,
    base_ref: str = "",
    head_ref: str = "",
    merge_sha: str = "",
    url: str = "",
    sender: str = "",
) -> dict[str, Any]:
    """组装一条归一化事件。畸形直接抛,不做猜测性修补。"""
    if kind not in KINDS:
        raise EventError(f"未知事件类型: {kind!r}")
    if not source:
        raise EventError("事件缺少 source")
    if kind == "ping":
        return {"kind": kind, "source": source}

    if not repo:
        raise EventError("事件缺少 repo")
    if number is None:
        raise EventError("事件缺少 number")
    return {
        "kind": kind,
        "source": source,
        "repo": str(repo),
        "repo_id": repo_id,
        "change_id": change_id,
        "number": number,
        "title": title or "",
        "body": body or "",
        "action": action or "",
        "is_pull": bool(is_pull),
        "base_ref": base_ref or "",
        "head_ref": head_ref or "",
        "merge_sha": merge_sha or "",
        "url": url or "",
        "sender": sender or "",
    }


def header_value(headers: Any, name: str) -> str:
    """大小写不敏感地取一个请求头;没有返回空串。"""
    if headers is None:
        return ""
    try:
        direct = headers.get(name)
    except AttributeError:
        direct = None
    if direct:
        return str(direct)
    lowered = name.lower()
    try:
        items = headers.items()
    except AttributeError:
        return ""
    for key, value in items:
        if str(key).lower() == lowered:
            return str(value or "")
    return ""
