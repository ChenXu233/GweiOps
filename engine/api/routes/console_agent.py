# engine/api/routes/console_agent.py
"""控制台助手 —— 界面右上角那个小窗口背后的两条接口。

它和 `/mcp`、`/api/agent/exits` 是同一件事的第三种说法:能做什么、做一次会怎样。
所以这里不另开一套权限、不另记一本账:

- 工具清单来自出口(`tool_specs`),按会话身份收窄(`tool_visible`);
- 每次改世界的调用都落到 `run_tool`,走同一条闸门、同一本账;
- 唯一的差别是**多了一道人的允许** —— 会话开着 `confirm` 时,改世界的调用先摆到
  人面前,点了允许才执行。只读工具不受这条约束。

循环不在这里:推一版、看一眼、改主意的多步循环交给 bub(`engine/agent/loop.py`),
这个文件只负责把事件流摊给前端、把等待批准的那一次接住。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from engine.agent import console as store
from engine.api.auth import actor_of, require, tenant_scope
from engine.api.schemas import (
    ConsolePendingDTO,
    ConsoleSessionDTO,
    ConsoleToolDTO,
)
from engine.auth.keys import permission_for_tool, tool_visible
from engine.plugin_manager import registry
from engine.shared.config import config

router = APIRouter()
logger = logging.getLogger(__name__)


class SessionOpenDTO(BaseModel):
    """开一个会话。三样都可以不填:不填就按这个身份能给的全部算。"""

    permissions: list[str] | None = None
    bindings: list[str] | None = None
    tools: list[str] | None = None
    confirm: bool = True
    model: str = ""
    binding: str = ""
    tenant: str = ""


class SessionPatchDTO(BaseModel):
    permissions: list[str] | None = None
    bindings: list[str] | None = None
    tools: list[str] | None = None
    confirm: bool | None = None


class TurnDTO(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class DecisionDTO(BaseModel):
    allow: bool
    reason: str = ""


def _dtos(session: store.ConsoleSession, registry_: Any) -> ConsoleSessionDTO:
    tools = [
        ConsoleToolDTO(
            name=t["name"],
            description=t["description"],
            permission=t["permission"],
            mutating=bool(t["mutating"]),
        )
        for t in store.describe_tools(session, registry_)
    ]
    return ConsoleSessionDTO(**session.to_dict(), available=tools)


def _session(request: Request, session_id: str) -> store.ConsoleSession:
    """取会话,并核对它属于当前这个身份。别人的会话不能借来用 —— 那是借权限。"""
    try:
        found = store.get_session(session_id)
    except store.SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    actor = actor_of(request)
    if actor is not None and found.actor and found.actor != actor.name:
        raise HTTPException(status_code=403, detail="这个会话不是你的")
    if actor is not None and actor.tenant and found.tenant and actor.tenant != found.tenant:
        raise HTTPException(status_code=403, detail="这个会话不属于你的租户")
    return found


@router.post("/api/console/session")
async def open_session(request: Request, body: SessionOpenDTO | None = None) -> ConsoleSessionDTO:
    """开一个会话。签出去的权限不会超过调用者自己的。"""
    require(request, "changes.read")
    from engine.api.auth import auth_required

    actor = actor_of(request)
    if actor is None and auth_required():
        raise HTTPException(status_code=401, detail="未登录或令牌无效")
    draft = body or SessionOpenDTO()
    tenant = tenant_scope(request, draft.tenant or None) or config.settings.default_tenant_slug
    try:
        session = store.open_session(
            actor=actor,
            tenant=tenant,
            binding=draft.binding or config.settings.default_binding,
            permissions=draft.permissions,
            bindings=draft.bindings,
            tools=draft.tools,
            confirm=draft.confirm,
            model=draft.model,
        )
    except store.SessionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _dtos(session, registry)


@router.get("/api/console/session/{session_id}")
async def get_session(session_id: str, request: Request) -> ConsoleSessionDTO:
    require(request, "changes.read")
    return _dtos(_session(request, session_id), registry)


@router.patch("/api/console/session/{session_id}")
async def patch_session(
    session_id: str, request: Request, body: SessionPatchDTO
) -> ConsoleSessionDTO:
    """收窄会话的权限、资源、工具,或者开关"要不要人点"。收窄不需要别人的批准,放宽不会越过这个人。"""
    require(request, "changes.read")
    session = _session(request, session_id)
    try:
        store.update_session(
            session,
            actor=actor_of(request),
            permissions=body.permissions,
            bindings=body.bindings,
            tools=body.tools,
            confirm=body.confirm,
        )
    except store.SessionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _dtos(session, registry)


@router.delete("/api/console/session/{session_id}")
async def close_session(session_id: str, request: Request) -> dict:
    require(request, "changes.read")
    session = _session(request, session_id)
    return {"closed": store.close_session(session.id)}


@router.get("/api/console/session/{session_id}/tools")
async def list_tools(session_id: str, request: Request) -> dict:
    """这个会话此刻看得见的工具。与 `/mcp` 的 `tools/list` 同一份事实来源。"""
    require(request, "changes.read")
    session = _session(request, session_id)
    return {"tools": store.describe_tools(session, registry)}


@router.get("/api/console/session/{session_id}/pending")
async def pending(session_id: str, request: Request) -> ConsolePendingDTO:
    """正在等人点的那一次。前端轮询它画那张批准卡;没有就是 null。"""
    require(request, "changes.read")
    session = _session(request, session_id)
    return ConsolePendingDTO(pending=store.describe_pending(store.pending_of(session)))


@router.post("/api/console/session/{session_id}/pending/{call_id}")
async def decide(
    session_id: str, call_id: str, request: Request, body: DecisionDTO
) -> dict:
    """人点了允许或拒绝。允许之后才轮到出口判它能不能改世界 —— 两关都要过。"""
    require(request, "changes.execute")
    session = _session(request, session_id)
    try:
        store.decide(session, call_id, body.allow, body.reason)
    except store.SessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


def _event(kind: str, data: dict[str, Any]) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(session: store.ConsoleSession, message: str) -> AsyncIterator[str]:
    """把 bub 的事件流摊成 SSE。

    前端要的是"正在说"和"正在做什么":文本增量、工具调用、工具结果、批准卡、
    收尾。bub 的事件正好是这几种,这里只做改名,不改含义。
    """
    from engine.agent.loop import HAS_BUB, session_agent

    if not HAS_BUB:  # pragma: no cover - 只在没装 bub 的部署里走到
        yield _event("error", {"message": "这台机器的引擎没装 bub,控制台助手起不来"})
        yield _event("done", {})
        return

    agent = session_agent(session=session, registry=registry)
    steps: list[dict[str, Any]] = []
    try:
        async with agent.run(message, tape=session.id) as stream:
            async for event in stream:
                kind = getattr(event, "kind", "")
                data = dict(getattr(event, "data", {}) or {})
                if kind == "text":
                    yield _event("delta", {"text": data.get("delta", "")})
                elif kind == "tool_call":
                    for call in data.get("tool_calls") or ():
                        steps.append({"tool": call.get("name", "")})
                        yield _event(
                            "tool",
                            {"name": call.get("name", ""), "args": call.get("arguments", "")},
                        )
                elif kind == "tool_result":
                    results = data.get("tool_results") or []
                    yield _event("tool_result", {"results": results})
                elif kind == "usage":
                    # 计量与显示都不该让这一轮断掉
                    continue
        # 工具是同步跑完的,批准卡也就没有"等"的中间态:一次运行里点过允许就执行过了
        yield _event("done", {"steps": steps, "actions": session.actions})
    except Exception as exc:  # noqa: BLE001 - 一轮对话的失败要回到界面上,不是 500
        logger.warning("控制台助手这一轮失败", exc_info=True)
        yield _event("error", {"message": f"{type(exc).__name__}: {exc}"})
        yield _event("done", {"steps": steps, "actions": session.actions})


@router.post("/api/console/session/{session_id}/turn")
async def turn(session_id: str, request: Request, body: TurnDTO) -> StreamingResponse:
    """说一句,拿回一条事件流(text/event-stream)。

    用 SSE 而不是 WebSocket:这是一问一答,断了就重说一句,不需要双向。
    """
    require(request, "changes.read")
    session = _session(request, session_id)
    return StreamingResponse(
        _stream(session, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/console/tools")
async def available_tools(request: Request) -> dict:
    """这个身份能给出去的工具全集:开面板时挑的就是它,前端不自己编。"""
    require(request, "changes.read")
    from engine.agent.tools import tool_specs

    actor = actor_of(request)
    out = []
    for spec in tool_specs(registry):
        function = spec.get("function") or {}
        name = str(function.get("name") or "")
        if not name or not tool_visible(name, actor, getattr(registry, "tool_bindings", None)):
            continue
        out.append(
            {
                "name": name,
                "description": str(function.get("description") or name),
                "permission": permission_for_tool(name),
                "mutating": name in registry.declared_effects(),
            }
        )
    return {
        "tools": out,
        "resources": sorted(getattr(registry, "resources", lambda: [])()),
        "default_binding": config.settings.default_binding,
    }


__all__ = ["router"]
