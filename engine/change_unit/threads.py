# engine/change_unit/threads.py
"""话题 —— 一条 issue / PR 上的全部变更。

GitHub 把 PR 的评论也当作 `issue_comment` 发出来:在"评论"这件事上,issue 与 PR
本来就分不开(PR 在 API 里就是一个带上 pull_request 字段的 issue)。分得开的是
平台这一侧:一次讨论是一个话题,话题上的每次改动是一个变更单元;同一个话题上
已经有打开的 PR 时,新的改动接着那个分支走,而不是再开一个。

"接着哪个分支"不是让 agent 猜的:账本里记着上一次开出来的 PR 与它的分支。
"""

from __future__ import annotations

from typing import Any

# 这些结论之后,那条单元就不算"还开着"了
_DEAD_VERDICTS = ("rolled_back", "vetoed", "failed", "blocked")


def topic_of(repo: str, number: Any) -> str:
    """话题的写法:owner/repo#number。"""
    if not repo or number is None:
        return ""
    return f"{repo}#{number}"


def _alive(row: dict[str, Any], dead: set[str]) -> bool:
    return (
        row.get("verdict") == "kept"
        and str(row.get("id") or "") not in dead
    )


async def open_pull_on(
    ledger: Any, tenant: str, topic: str, limit: int = 200
) -> dict[str, Any] | None:
    """这个话题上一次开出来、此刻仍然打开的 PR。

    判"仍然打开"用账本自己的话:同一条单元后面出现过撤销/否决,就不再算开着。
    读不到账本就返回 None —— 没有证据不等于没有 PR,但这里只能按没有处理,
    调用方仍然可以让 agent 自己去看仓库。
    """
    if not topic or ledger is None:
        return None
    try:
        rows = await ledger.latest(tenant=tenant, limit=limit)
    except Exception:
        return None

    dead = {
        str(row.get("id") or "")
        for row in rows
        if isinstance(row, dict) and row.get("verdict") in _DEAD_VERDICTS
    }

    for row in rows:  # latest 是倒序,第一条命中的就是最近那次
        if not isinstance(row, dict) or not _alive(row, dead):
            continue
        intent = row.get("intent")
        effect = row.get("effect")
        if not isinstance(intent, dict) or not isinstance(effect, dict):
            continue
        if intent.get("topic") != topic or effect.get("capability") != "pr.open":
            continue
        args = effect.get("args") or {}
        head = str(args.get("head") or "")
        if not head:
            continue
        facts = row.get("facts") or {}
        return {
            "repo": str(args.get("repo") or ""),
            "head": head,
            "pull": str(row.get("handle") or ""),
            "url": str(facts.get("url") or ""),
        }
    return None


__all__ = ["open_pull_on", "topic_of"]
