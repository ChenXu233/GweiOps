# plugins/builtin/adapters/alertmanager/plugin.py
"""Alertmanager → 信号。

一次投递是分组后的多条告警;一条 firing 告警就是一个信号。
只收 firing:resolved 说的是"事情过去了",不是"哪里出了事",不该起工作流。

这里没有平台的事:它只把 Alertmanager 的字段名翻译成信号。换一个告警系统
(Caddy、云雀、Grafana、PagerDuty……),换的就是这一层——核心的
`/webhook/<source>` 不认识任何一家的字段与签名,它只问三件事:
配没配、签名对不对、这条投递里有哪些信号。
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict

from engine.ingest.events import header_value
from engine.ingest.signal import SignalError, normalize
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

from .config import AlertmanagerConfig

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


def to_signal(alert: dict[str, Any]) -> dict[str, Any] | None:
    """一条告警 → 一条信号。没有标题的告警不是"哪里出了什么事",跳过。"""
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    title = annotations.get("summary") or labels.get("alertname")
    if not title:
        return None

    started = str(alert.get("startsAt") or "")
    return normalize(
        source="alertmanager",
        subject=_subject(labels),
        title=str(title),
        detail=str(annotations.get("description") or ""),
        severity=_severity(labels.get("severity")),
        ref=str(alert.get("fingerprint") or ""),
        # 同一个 fingerprint 再次 firing 是另一次发作:没有这一层,去重会把
        # 昨晚那条和今早这条算成同一条,第二次就没人管了。
        occurrence=started,
        extra={
            "alertname": str(labels.get("alertname") or ""),
            "labels": dict(labels),
            "annotations": dict(annotations),
            "started_at": started,
        },
    )


def signals_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
            signal = to_signal(alert)
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


class AlertmanagerAdapter(PluginBase):
    """把 Alertmanager 的投递翻译成信号,交给平台的统一入口。"""

    # 核心按这个名把 /webhook/<source> 的投递交过来。
    source = "alertmanager"
    # 这类投递产出的是信号,不是"issue/comment/merge"那种事件。
    produces = "signal"
    # 没配密钥时,入口按这个名字告诉人该去填什么。
    config_hint = "ALERTMANAGER_WEBHOOK_TOKEN"

    def __init__(self) -> None:
        self.config = AlertmanagerConfig()
        # 变更单元里的目标与租户:告警不按目标隔离,给空值。
        self.binding = ""
        self.tenant = ""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="alertmanager-adapter",
            version="0.1.0",
            type=PluginType.ADAPTER,
            description="把 Alertmanager 的告警翻译成信号;一条 firing 告警就是一个信号",
            capabilities=["webhook.receive", "webhook.verify"],
            config={"optional": ["ALERTMANAGER_WEBHOOK_TOKEN"]},
        )

    async def on_startup(self) -> None:
        # 人在页面上刚填完令牌:重建一次配置,不用重启。
        self.config = AlertmanagerConfig()

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return self.webhook_configured()

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "error", "message": f"Unknown task: {task}"}

    # -- Webhook ------------------------------------------------------

    def webhook_configured(self) -> bool:
        return bool(self.config.token)

    def verify_webhook(self, headers: Dict[str, Any], body: bytes) -> bool:
        """共享令牌比对。用常数时间比较:普通 == 会把答案按耗时漏出去。"""
        if not self.webhook_configured():
            return False
        given = header_value(headers, "X-Gwei-Token") or ""
        return hmac.compare_digest(given, self.config.token)

    def parse_signals(self, headers: Dict[str, Any], body: bytes) -> list[dict[str, Any]]:
        try:
            payload = json.loads(body or b"{}")
        except (TypeError, ValueError):
            raise SignalError("投递不是合法 JSON") from None
        if not isinstance(payload, dict):
            raise SignalError("投递不是 JSON 对象")
        return signals_from_payload(payload)
