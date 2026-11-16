# engine/api/routes/console_agent.py
"""控制台助手的 HTTP 接口(界面上的悬浮窗)。

与 `/mcp`、`/api/agent/exits` 同一套权限与账本,不另开一套:

- 工具清单来自出口(`tool_specs`),按会话身份收窄(`tool_visible`);
- 每次改世界的调用都落到 `run_tool`,走同一条闸门、同一本账;
- 多一道人工批准:会话开着 `confirm` 时,改世界的调用先经批准才执行;只读工具不受此约束。

多步循环在插件里(`console-agent` 的 `console.chat` 能力),这里只把事件流转成 SSE、
接住待批调用。没有提供者时如实报错,不塞一个内置循环。
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
    """开会话的请求体;各字段不填时按当前身份可给的全部。"""

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


def _dtos(session: store.ConsoleSession, registry_: Any, actor: Any = None) -> ConsoleSessionDTO:
    """会话当前状态;工具清单按**调用者当下**的权限算,而非创建时的快照。"""
    tools = [
        ConsoleToolDTO(
            name=t["name"],
            description=t["description"],
            permission=t["permission"],
            mutating=bool(t["mutating"]),
        )
        for t in store.describe_tools(session, registry_, actor)
    ]
    body = session.to_dict()
    body["permissions"] = sorted(store.effective_permissions(session, actor))
    return ConsoleSessionDTO(**body, available=tools)


async def _session(request: Request, session_id: str) -> store.ConsoleSession:
    """取会话并核对归属;他人的会话不可使用。"""
    try:
        found = await store.get_session(session_id)
    except store.SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except store.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    actor = actor_of(request)
    try:
        store._check_owner(found, actor)
    except store.SessionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return found


@router.post("/api/console/session")
async def open_session(request: Request, body: SessionOpenDTO | None = None) -> ConsoleSessionDTO:
    """开一个会话;授予的权限不超过调用者自己。"""
    require(request, "changes.read")
    from engine.api.auth import auth_required

    actor = actor_of(request)
    if actor is None and auth_required():
        raise HTTPException(status_code=401, detail="未登录或令牌无效")
    draft = body or SessionOpenDTO()
    tenant = tenant_scope(request, draft.tenant or None) or config.settings.default_tenant_slug
    try:
        session = await store.open_session(
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
    except store.StorageUnavailable as exc:
        # 不降级为内存会话:没有落库就没有审计
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _dtos(session, registry, actor)


@router.get("/api/console/session/{session_id}")
async def get_session(session_id: str, request: Request) -> ConsoleSessionDTO:
    require(request, "changes.read")
    return _dtos(await _session(request, session_id), registry, actor_of(request))


@router.patch("/api/console/session/{session_id}")
async def patch_session(
    session_id: str, request: Request, body: SessionPatchDTO
) -> ConsoleSessionDTO:
    """收窄会话的权限、资源、工具,或开关审批。收窄无需批准,放宽不越过当前身份。"""
    require(request, "changes.read")
    session = await _session(request, session_id)
    try:
        await store.update_session(
            session,
            actor=actor_of(request),
            permissions=body.permissions,
            bindings=body.bindings,
            tools=body.tools,
            confirm=body.confirm,
        )
    except store.SessionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except store.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _dtos(session, registry, actor_of(request))


@router.delete("/api/console/session/{session_id}")
async def close_session(session_id: str, request: Request) -> dict:
    require(request, "changes.read")
    session = await _session(request, session_id)
    return {"closed": await store.close_session(session.id)}


@router.get("/api/console/session/{session_id}/tools")
async def list_tools(session_id: str, request: Request) -> dict:
    """该会话当前可见的工具;与 `/mcp` 的 `tools/list` 同源。"""
    require(request, "changes.read")
    session = await _session(request, session_id)
    return {"tools": store.describe_tools(session, registry, actor_of(request))}


@router.get("/api/console/session/{session_id}/pending")
async def pending(session_id: str, request: Request) -> ConsolePendingDTO:
    """当前待批的调用;前端轮询绘制批准卡,没有则为 null。"""
    require(request, "changes.read")
    session = await _session(request, session_id)
    return ConsolePendingDTO(pending=store.describe_pending(store.pending_of(session)))


@router.get("/api/console/session/{session_id}/messages")
async def messages(session_id: str, request: Request) -> dict:
    """该会话的对话记录:消息、调用、结果、拒绝、超时。"""
    require(request, "changes.read")
    session = await _session(request, session_id)
    return {"messages": await store.history(session.id)}


@router.post("/api/console/session/{session_id}/pending/{call_id}")
async def decide(
    session_id: str, call_id: str, request: Request, body: DecisionDTO
) -> dict:
    """记录允许或拒绝;允许后仍需出口闸门判定,两关都要过。"""
    require(request, "changes.execute")
    session = await _session(request, session_id)
    try:
        await store.decide(session, call_id, body.allow, body.reason, actor=actor_of(request))
    except store.SessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


def _event(kind: str, data: dict[str, Any]) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(
    session: store.ConsoleSession, message: str, actor: Any = None
) -> AsyncIterator[str]:
    """把 agent 提供者的事件流转成 SSE。

    前端需要文本增量、工具调用、工具结果、错误与收尾;提供者的事件正好一一对应,
    这里只做字段映射。提供者从注册表来(`console.chat`),不是本地 new 出来的。
    """
    from engine.agent.provider import AgentUnavailable, build_agent

    # 模型不可用:先记录用户消息,再报可检索的错误。
    await store.record(session, "user", message)

    if store.pending_of(session) is not None:
        # 上一轮还在等人点"允许"。再来一轮会把两个待批混在一起,批准谁都不清楚。
        yield _event("error", {"message": "上一轮还有待批准的调用没处理,先允许或拒绝它"})
        yield _event("done", {"steps": [], "actions": session.actions})
        return

    try:
        agent = build_agent(session=session, registry=registry, actor=actor)
    except AgentUnavailable as exc:
        await store.record(session, "error", str(exc))
        yield _event("error", {"message": str(exc)})
        yield _event("done", {"steps": [], "actions": session.actions})
        return
    except Exception as exc:  # noqa: BLE001 - 提供者自己的失败要回到界面上
        logger.warning("控制台助手构造 agent 失败", exc_info=True)
        reason = f"{type(exc).__name__}: {exc}"
        await store.record(session, "error", reason)
        yield _event("error", {"message": reason})
        yield _event("done", {"steps": [], "actions": session.actions})
        return
    steps: list[dict[str, Any]] = []
    said: list[str] = []
    try:
        async with agent.run(message, tape=session.id) as stream:
            async for event in stream:
                kind = getattr(event, "kind", "")
                data = dict(getattr(event, "data", {}) or {})
                if kind == "text":
                    delta = str(data.get("delta", ""))
                    said.append(delta)
                    yield _event("delta", {"text": delta})
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
        # 工具同步执行完毕,运行中没有"等待批准"的中间态
        await store.record(session, "assistant", "".join(said), {"steps": steps})
        yield _event("done", {"steps": steps, "actions": session.actions})
    except Exception as exc:  # noqa: BLE001 - 一轮对话的失败要回到界面上,不是 500
        logger.warning("控制台助手这一轮失败", exc_info=True)
        await store.record(session, "error", f"{type(exc).__name__}: {exc}")
        yield _event("error", {"message": f"{type(exc).__name__}: {exc}"})
        yield _event("done", {"steps": steps, "actions": session.actions})


@router.post("/api/console/session/{session_id}/turn")
async def turn(session_id: str, request: Request, body: TurnDTO) -> StreamingResponse:
    """发一句话,返回事件流(text/event-stream)。

    一问一答,用 SSE 即可,无需 WebSocket 的双向通道。
    """
    require(request, "changes.read")
    session = await _session(request, session_id)
    return StreamingResponse(
        _stream(session, body.message, actor_of(request)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/console/tools")
async def available_tools(request: Request) -> dict:
    """当前身份可授予的工具全集;前端面板从中选取。"""
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
