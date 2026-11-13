# engine/api/routes/agent.py
"""出口 —— 沙箱里的 agent 改变外部世界的唯一通道。

这里只暴露两件事:能做什么(出口清单),做一次(走闸门)。
它不排队、不重试、不执行计划:每一次调用都是一个独立的变更单元,
各自读窗口、各自判定、各自记账。

次数上限在平台这一侧,因为循环搬到沙箱里之后,平台看不到"它在想第几步",
只看得见"它已经点了多少次"。这个上限属于出口,不属于 agent 的自觉。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from engine.agent import ToolCall, run_tool, tool_specs
from engine.api.auth import by_of, tenant_scope
from engine.change_unit import create_ledger
from engine.plugin_manager import registry
from engine.shared.config import config

router = APIRouter()
logger = logging.getLogger(__name__)


class ExitCallDTO(BaseModel):
    """一次出口调用。args 的形状由出口清单决定,这里只兜住外层。"""

    model_config = ConfigDict(extra="allow")

    args: dict[str, Any] = {}
    call_id: str = ""  # 带上的话,重发同一次调用只复用结论,不二次外呼
    incident_id: str = ""  # 这一次事故的编号;同一次事故的变更共用它
    binding: str = ""
    tenant: str = ""
    summary: str = ""


def _an_hour_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")


async def _exits_in_the_last_hour(tenant: str) -> int:
    """这一小时里,这个租户从出口做了几次变更。只读调用不落账,所以不占额度。"""
    rows = await create_ledger().latest(tenant=tenant)
    since = _an_hour_ago()
    used = 0
    for row in rows:
        intent = row.get("intent")
        if not isinstance(intent, dict) or intent.get("via") != "exit":
            continue
        if str(row.get("created_at") or "") >= since:
            used += 1
    return used


async def _topic_of(incident_id: str) -> str:
    """这一场事故对应的话题。读不到就是空 —— 没记下来,不猜一个。"""
    if not incident_id:
        return ""
    try:
        from engine.incidents import create_incident_store

        row = await create_incident_store().get(incident_id)
    except Exception:  # noqa: BLE001 - 事件库不可用不该让出口断掉
        return ""
    return str((row or {}).get("topic") or "")


async def _workspace_files(incident_id: str, paths: Any) -> list[dict[str, Any]]:
    """工作区里的改动 → 提交能用的 files。

    内容由平台读,不由 agent 塞进参数:它只要说"我改了东西",读哪几个文件是
    平台对着仓库算得出来的。paths 给了就只要那几个。
    """
    from engine.harness import workspace as ws

    if not incident_id:
        raise ws.WorkspaceError("出口调用要带 incident_id,平台才知道去哪读工作区")
    root = config.settings.harness_workspace_root
    wanted = [paths] if isinstance(paths, str) else list(paths or [])
    return await ws.collect(
        ws.repo_of(root, incident_id), ws.workspace_of(root, incident_id), wanted
    )


@router.get("/api/agent/exits")
async def list_exits(request: Request) -> dict:
    """出口清单:名字、说明、声明的参数名。参数类型不声明,清单也没说。"""
    return {"tools": tool_specs(registry)}


@router.post("/api/agent/exits/{name}")
async def call_exit(name: str, request: Request, call: ExitCallDTO) -> dict:
    tenant = tenant_scope(request, call.tenant or None) or ""
    binding = call.binding or config.settings.default_binding
    actor = by_of(request, "")

    if name in registry.declared_effects():
        limit = max(0, config.settings.agent_max_exits_per_hour)
        if limit:
            used = await _exits_in_the_last_hour(tenant)
            if used >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"这个租户这一小时已经通过出口改了 {used} 次,到上限 {limit} 了;"
                        "停手,由人接手"
                    ),
                )

    # 参数可以放 args 里,也可以直接放顶层 —— 出口清单给的是"这个动作要哪些参数",
    # 照着它把参数写在最外层是最自然的读法。只认 args 的话,那种调用会变成
    # "一个参数都没给",然后被平台补上 files 当成一次空调用。
    envelope = {"args", "call_id", "incident_id", "binding", "tenant", "summary"}
    flat = {
        key: value
        for key, value in (call.model_extra or {}).items()
        if key not in envelope
    }
    args = {**flat, **dict(call.args or {})}
    declared = registry.declared_effects().get(name) or {}
    # paths 是"读哪几个文件"的简写,由出口消化掉,不跟着效果进账本。
    shorthand_paths = args.pop("paths", None)
    if "files" in (declared.get("args") or []) and not args.get("files"):
        from engine.harness.workspace import WorkspaceError

        try:
            args["files"] = await _workspace_files(call.incident_id, shorthand_paths)
        except WorkspaceError as exc:
            # 读不出改动不是"提交了空改动",说清楚并停在这里。
            return {"ok": False, "reason": f"读不出工作区的改动:{exc}"}

    result = await run_tool(
        ToolCall(name, args),
        registry=registry,
        ledger=create_ledger(),
        tenant=tenant,
        binding=binding,
        idem_base=(
            f"{actor}:{call.incident_id}:{call.call_id}" if call.call_id else ""
        ),
        summary=call.summary,
        actor=actor,
        incident_id=call.incident_id,
        topic=await _topic_of(call.incident_id),
    )
    logger.info(
        "exit %s by %s [%s/%s] -> %s",
        name,
        actor or "-",
        tenant or "-",
        binding or "-",
        result.verdict or ("ok" if result.ok else "error"),
    )
    return result.to_dict()
