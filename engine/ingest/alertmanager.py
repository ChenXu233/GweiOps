# engine/ingest/alertmanager.py
"""Alertmanager webhook → 信号。

一次投递是分组后的多条告警;一条告警就是一个信号。
只收 firing:resolved 说的是"事情过去了",不是"哪里出了事",不该起工作流。
"""

from __future__ import annotations

from typing import Any

from .signal import SignalError, normalize

# Alertmanager 的习惯值是 warning,信号口径只有三档
_SEVERITY = {
    "critical": "critical",
    "warning": "medium",
    "warn": "medium",
    "info": "low",
    "none": "low",
}


def _severity(raw: str | None) -> str:
    return _SEVERITY.get((raw or "").lower(), "medium")


def _subject(labels: dict[str, Any]) -> str:
    """主体优先取服务,取不到再退到 job / 实例 / 告警名。"""
    for key in ("service", "job", "instance", "alertname"):
        value = labels.get(key)
        if value:
            return str(value)
    return "unknown"


def from_alert(alert: dict[str, Any]) -> dict[str, Any] | None:
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    title = annotations.get("summary") or labels.get("alertname")
    if not title:
        return None

    return normalize(
        source="alertmanager",
        subject=_subject(labels),
        title=str(title),
        detail=str(annotations.get("description") or ""),
        severity=_severity(labels.get("severity")),
        ref=str(alert.get("fingerprint") or ""),
        extra={
            "alertname": str(labels.get("alertname") or ""),
            "labels": dict(labels),
            "annotations": dict(annotations),
            "started_at": str(alert.get("startsAt") or ""),
        },
    )


def parse_alerts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """一条投递里的 firing 告警,按 fingerprint 去重(没有就按标题)。"""
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return []

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for alert in alerts:
        if not isinstance(alert, dict) or alert.get("status") != "firing":
            continue
        try:
            signal = from_alert(alert)
        except SignalError:
            continue
        if signal is None:
            continue
        key = signal["ref"] or signal["title"]
        if key in seen:
            continue
        seen.add(key)
        out.append(signal)
    return out
