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

    result = await run_tool(
        ToolCall(name, dict(call.args or {})),
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
