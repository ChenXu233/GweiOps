# plugins/builtin/actions/platform-mcp/plugin.py
"""平台自己的读口 —— 账本、事故、话题。

这三样不是"外部世界",是这台机器自己记下的事。任何把 GweiOps 接进来的 agent,
第一件事都是问它们:最近改了什么、哪一场卡住了、这个话题上的 PR 还开着吗。

只读,所以不产生变更单元——看账本不会写账。
"""

from __future__ import annotations

from typing import Any, Dict

from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType


def _limit(raw: Any, default: int = 20, ceiling: int = 200) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, ceiling))


def _brief(row: Dict[str, Any]) -> Dict[str, Any]:
    """账本一行太长,挑出人(和外面的 agent)真正要看的几样。"""
    intent = row.get("intent") if isinstance(row.get("intent"), dict) else {}
    effect = row.get("effect") if isinstance(row.get("effect"), dict) else {}
    facts = row.get("facts") if isinstance(row.get("facts"), dict) else {}
    return {
        "unit": row.get("id", ""),
        "verdict": row.get("verdict", ""),
        "reason": row.get("reason", ""),
        "capability": effect.get("capability", ""),
        "summary": intent.get("summary", ""),
        "by": intent.get("by", ""),
        "topic": intent.get("topic", ""),
        "incident": row.get("incident_id", ""),
        "handle": row.get("handle", ""),
        "url": facts.get("url", ""),
        "at": row.get("created_at", ""),
    }


class PlatformMcpAction(PluginBase):
    """只读能力:把平台记下的事交出去,不改任何东西。"""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="platform-mcp",
            version="0.1.0",
            type=PluginType.ACTION,
            description="把平台自己记下的事(账本、事故、话题)做成只读能力",
            capabilities=["changes.read", "incidents.read", "topic.read"],
        )

    async def on_startup(self) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "read_changes":
            return await self._changes(params)
        if task == "read_incidents":
            return await self._incidents(params)
        if task == "read_topic":
            return await self._topic(params)
        return {"status": "error", "message": f"Unknown task: {task}"}

    # -- 三个读口 --------------------------------------------------

    async def _changes(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from engine.change_unit import create_ledger

        tenant = str(params.get("tenant") or "")
        verdict = str(params.get("verdict") or "")
        topic = str(params.get("topic") or "")
        capability = str(params.get("capability") or "")

        rows = await create_ledger().latest(tenant=tenant, limit=_limit(params.get("limit")))
        items = [_brief(row) for row in rows if isinstance(row, dict)]
        if verdict:
            items = [item for item in items if item["verdict"] == verdict]
        if topic:
            items = [item for item in items if item["topic"] == topic]
        if capability:
            items = [item for item in items if item["capability"] == capability]
        return {"items": items, "count": len(items)}

    async def _incidents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from engine.incidents import create_incident_store

        store = create_incident_store()
        incident_id = str(params.get("id") or "")
        if incident_id:
            row = await store.get(incident_id)
            return {"incident": row} if row else {"incident": None, "reason": "没有这一场"}
        rows = await store.list(
            str(params.get("tenant") or "") or None, limit=_limit(params.get("limit"))
        )
        return {"items": rows, "count": len(rows)}

    async def _topic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from engine.change_unit import create_ledger
        from engine.change_unit.threads import open_pull_on

        topic = str(params.get("topic") or "")
        if not topic:
            return {"pull": None, "reason": "要给出 topic,形如 owner/repo#12"}
        tenant = str(params.get("tenant") or "")
        pull = await open_pull_on(create_ledger(), tenant, topic)
        return {"topic": topic, "pull": pull}
