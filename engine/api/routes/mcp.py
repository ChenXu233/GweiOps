# engine/api/routes/mcp.py
"""MCP —— 出口的另一种写法。

沙箱里的 agent 用 HTTP 调出口;别人的 agent(Claude Code、Cursor、dsh)说的是 MCP。
两边要的是同一件事:这台机器能做什么、做一次会怎样。

所以这里不另开一套权限,也不另记一本账:`tools/list` 就是出口清单,`tools/call`
就是出口调用。谁在这里点一下,和沙箱里的 agent 点一下,过的是同一条闸门、落的是
同一行账。

传输用 streamable HTTP(单端点、JSON-RPC 2.0):一个 URL 加一个令牌就能接上。不做
stdio 是因为身份与账本属于服务端——每个客户端各自起一个进程,账本就成了每个客户端的
私事,而不是这台机器的记录。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from engine.agent import ToolCall, run_tool, tool_specs
from engine.api.auth import actor_of, by_of, tenant_scope
from engine.change_unit import create_ledger
from engine.plugin_manager import registry
from engine.shared.config import config

router = APIRouter()
logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "gweiops", "version": "0.1.0"}
INSTRUCTIONS = (
    "这是 GweiOps 的出口。tools/list 列出这台机器能做的事;"
    "tools/call 每调用一次都会走变更闸门:判定此刻能不能撤、执行、验证、记账。"
    "被拒绝时 reason 会写明原因,不要对同一个动作反复试。"
)


def _tools() -> list[dict[str, Any]]:
    """出口清单翻译成 MCP 的工具清单。只有一份事实来源——`tool_specs`。"""
    out: list[dict[str, Any]] = []
    for spec in tool_specs(registry):
        function = spec.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        out.append(
            {
                "name": name,
                "description": str(function.get("description") or name),
                "inputSchema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out


def _result(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _text(payload: dict[str, Any], is_error: bool) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


async def _call_tool(request: Request, name: str, arguments: Any) -> dict[str, Any]:
    """一次工具调用 = 一次出口调用。"""
    args = dict(arguments or {})
    summary = str(args.pop("_summary", "") or "")
    incident_id = str(args.pop("_incident_id", "") or "")
    topic = str(args.pop("_topic", "") or "")
    binding = str(args.pop("_binding", "") or "") or config.settings.default_binding
    requested = args.pop("tenant", "")
    tenant = tenant_scope(request, str(requested) if isinstance(requested, str) else None) or ""

    is_effect = name in registry.declared_effects()
    actor = actor_of(request)
    if is_effect and actor is not None and not actor.can_write:
        return _text({"ok": False, "reason": f"这个身份只读,不能调用 {name}"}, True)

    if not is_effect:
        # 只读能力自己不知道租户是谁:把身份上的租户交给它,查询范围才收得住。
        args["tenant"] = tenant

    result = await run_tool(
        ToolCall(name, args),
        registry=registry,
        ledger=create_ledger(),
        tenant=tenant,
        binding=binding,
        summary=summary,
        actor=by_of(request, ""),
        incident_id=incident_id,
        topic=topic,
    )
    return _text(result.to_dict(), not result.ok)


async def _handle(request: Request, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "不是 JSON-RPC 2.0 消息")

    method = str(message.get("method") or "")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(msg_id, -32602, "params 必须是对象")

    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        )
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": _tools()})
    if method == "tools/call":
        name = str(params.get("name") or "")
        if not name:
            return _error(msg_id, -32602, "tools/call 缺 name")
        return _result(msg_id, await _call_tool(request, name, params.get("arguments")))

    return _error(msg_id, -32601, f"没有这个方法:{method}")


@router.post("/mcp")
async def mcp(request: Request):
    """单端点:请求是 JSON-RPC,响应也是(通知类消息返回 202)。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - 解析失败是客户端的事,不是 500
        return JSONResponse(_error(None, -32700, "请求体不是 JSON"), status_code=400)

    batch = isinstance(body, list)
    messages = body if batch else [body]
    replies: list[dict[str, Any]] = []
    for message in messages:
        reply = await _handle(request, message)
        if reply is not None:
            replies.append(reply)

    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if batch else replies[0])


@router.get("/mcp")
async def mcp_describe() -> JSONResponse:
    """MCP 只有一条 POST 通道;GET 只用来告诉人"这里是什么"。"""
    return JSONResponse(
        {
            "transport": "streamable-http",
            "endpoint": "/mcp",
            "protocol_version": PROTOCOL_VERSION,
            "tools": [tool["name"] for tool in _tools()],
            "auth": "X-Gwei-Token",
        },
        status_code=200,
    )


__all__ = ["router", "PROTOCOL_VERSION", "SERVER_INFO"]
