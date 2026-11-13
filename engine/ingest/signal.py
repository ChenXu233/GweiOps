# engine/ingest/signal.py
"""信号归一化 —— 不同来源进来,同一种说法出去。

信号只说"哪里出了什么事",不说"该做什么"。动作属于 intent,不属于信号:
把它分开,issue 和监控才能走同一条链路,而平台不必理解任何一方的语法。

来源专有的字段(仓库名、告警标签)随信号一起交出去,由 intent 提供者决定用不用。
"""

from __future__ import annotations

from typing import Any

SOURCES = ("github", "alertmanager")
SEVERITIES = ("critical", "medium", "low")


class SignalError(ValueError):
    """信号形状不合法。"""


def normalize(
    *,
    source: str,
    subject: str,
    title: str,
    detail: str = "",
    severity: str = "medium",
    ref: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组装一条信号。畸形直接抛,不做猜测性修补。"""
    if source not in SOURCES:
        raise SignalError(f"未知信号来源: {source!r}")
    if not subject:
        raise SignalError("信号缺少 subject")
    if not title:
        raise SignalError("信号缺少 title")

    signal: dict[str, Any] = {
        "source": source,
        "subject": subject,
        "title": title,
        "detail": detail,
        "severity": severity if severity in SEVERITIES else "medium",
        "ref": ref,
    }
    signal.update(extra or {})
    return signal


def from_github(payload: dict[str, Any]) -> dict[str, Any]:
    """GitHub issue / 评论载荷 → 信号。

    repo 与 issue_number 留在信号里:回评这种效果需要它们。
    trigger 记的是触发方式(issue 还是评论),不是来源。
    """
    repo = payload.get("repo_full_name")
    number = payload.get("issue_number")
    if not repo or number is None:
        raise SignalError("GitHub 载荷缺少 repo_full_name / issue_number")

    return normalize(
        source="github",
        subject=f"{repo}#{number}",
        title=payload.get("title") or "",
        detail=payload.get("body") or "",
        severity=payload.get("severity") or "medium",
        ref=str(number),
        extra={
            "repo": repo,
            "issue_number": number,
            "trigger": payload.get("source", "issue"),
            "topic": payload.get("topic") or f"{repo}#{number}",
        },
    )
