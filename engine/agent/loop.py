# engine/agent/loop.py
"""把 bub 的循环接到这台机器上:模型走 litellm,工具走出。

bub 要一个 `ModelClient`(而不是某个厂商的客户端),理由是模型源自己带着降级、
凭据与超时。这里给的那一个只有一件事:**把 bub 的 messages/tools 翻译成 litellm
的调用**。所以控制台助手的模型沿用引擎已有的 `LLM_*` 配置,与其它 agent 插件
共用同一份凭据,不新开一套。

翻译只在两条边上做:出去(messages、tools)和回来(文本、tool_calls)。中间那段
——推一版、看一眼、改主意的循环——是 bub 的,这里不重写。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping

from engine.llm.client import LLMService

try:  # bub 是控制台助手的 loop;没装时这一条 import 失败,由路由给一句人话
    import republic
    from republic.events import Completed, TextDelta, ToolCallReady
    from bub.core.tools import Tool

    HAS_BUB = True
except ImportError:  # pragma: no cover - 只在没装 bub 的部署里走到
    republic = None  # type: ignore[assignment]
    HAS_BUB = False


def model_spec(llm: LLMService) -> str:
    """`provider:model`。前缀与 litellm 那套一致,只是分隔符换成冒号。

    bub 只拿它当标识与事件里的 `model` 字段;真正调谁由下面的 `open_stream` 决定。
    """
    built = llm._build_model_string()
    if "/" in built:
        provider, _, name = built.partition("/")
        return f"{provider}:{name}"
    return f"openai:{built}"


async def chat(
    llm: LLMService, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> dict[str, Any]:
    """一次补全。没有可用模型时如实回一句,不抛 —— 抛了这轮对话就断在半路。"""
    if not llm.enabled:
        return {
            "content": "这台机器还没有配模型(LLM_API_KEY 为空),我说不了话;工具清单是能看的。",
            "tool_calls": [],
        }
    result = await llm.call_with_tools(messages, tools, max_retries=1)
    return {
        "content": result.content,
        "tool_calls": [
            {"id": c.get("id") or "", "name": c.get("name") or "", "args": c.get("args") or {}}
            for c in result.tool_calls
        ],
    }


def _messages_for_litellm(messages: list[Any]) -> list[dict[str, Any]]:
    """republic 的 Message → litellm 的 dict。只翻它真会用到的那几栏。"""
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, dict):
            out.append(dict(message))
            continue
        row: dict[str, Any] = {"role": message.role}
        text = getattr(message, "text", "")
        if text:
            row["content"] = text
        calls = getattr(message, "tool_calls", ()) or ()
        if calls:
            row["content"] = row.get("content") or ""
            row["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments or "{}"},
                }
                for call in calls
            ]
        answered = getattr(message, "tool_call", None)
        if answered is not None:
            row["tool_call_id"] = answered.id
            row["role"] = "tool"
        out.append(row)
    return out


def _tools_for_litellm(tools: list[Any]) -> list[dict[str, Any]]:
    """bub 的 Tool → OpenAI 函数定义。参数 schema 是 bub 从出口清单算出来的那份。"""
    out: list[dict[str, Any]] = []
    for tool in list(tools or ()):
        # bub 交过来的是 republic.Tool:name / description / parameters 三个字段
        schema: dict[str, Any] = {}
        to_schema = getattr(tool, "to_schema", None)
        if callable(to_schema):
            built = to_schema()
            schema = built if isinstance(built, dict) else {}
        if not schema and getattr(tool, "name", None):
            schema = {
                "name": tool.name,
                "description": getattr(tool, "description", "") or "",
                "parameters": dict(getattr(tool, "parameters", None) or {}),
            }
        if not schema and isinstance(tool, dict):
            schema = dict(tool)
        out.append(
            {
                "type": "function",
                "function": {
                    "name": schema.get("name") or "",
                    "description": schema.get("description") or "",
                    "parameters": schema.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


class _ScriptedStream:
    """一次已经拿到的补全,装成 bub 认的流。

    bub 要的是"事件流 + 结束时的 response"。litellm 是一次性返回的,所以这里
    直接把结果摊成事件:文本一段、工具调用若干、usage 一条、Completed 收尾。
    """

    def __init__(self, response: Any, events: list[Any]) -> None:
        self.response = response
        self._events = events

    async def __aenter__(self) -> "_ScriptedStream":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def __aiter__(self) -> AsyncIterator[Any]:
        for event in self._events:
            yield event


class LiteLLMModelClient:
    """bub 的模型源:一次补全翻成 republic 的事件流。"""

    max_tokens = None

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm
        self.spec = model_spec(llm)
        self.last_usage: dict[str, Any] = {}

    @asynccontextmanager
    async def open_stream(
        self, messages: list[Any], *, spec: str, options: Mapping[str, Any]
    ) -> AsyncIterator[tuple[str, Any]]:
        tool_list = list(options.get("tools") or ())
        answer = await chat(self.llm, _messages_for_litellm(messages), _tools_for_litellm(tool_list))

        events: list[Any] = []
        text = str(answer.get("content") or "")
        if text:
            events.append(TextDelta(text))
        calls = []
        for raw in answer.get("tool_calls") or ():
            call = republic.ToolCall(
                id=str(raw.get("id") or f"call-{len(calls)}"),
                name=str(raw.get("name") or ""),
                arguments=json.dumps(raw.get("args") or {}, ensure_ascii=False),
            )
            calls.append(call)
            events.append(ToolCallReady(call))
        parts = (republic.Text(text),) if text else ()
        response = republic.Response(
            message=republic.Message("assistant", parts, tool_calls=tuple(calls)),
            model=self.spec,
        )
        events.append(Completed(response))
        provider, _, _name = self.spec.partition(":")
        yield provider, _ScriptedStream(response, events)


def session_agent(*, session: Any, registry: Any, llm: LLMService | None = None):
    """一个会话用的 bub agent。

    子类只改写一件事:**每次运行都把会话当下的工具清单交给模型**。会话的权限
    被改窄之后,下一步就看不见那些工具了 —— 工具清单不是构造时定死的。
    """
    if not HAS_BUB:  # pragma: no cover - 只在没装 bub 的部署里走到
        raise RuntimeError("没有安装 bub,控制台助手起不来")

    from bub.core import Agent
    from bub.core.tools import model_tools

    from engine.agent.console import MAX_STEPS, SYSTEM_PROMPT, bub_tools

    class SessionAgent(Agent):
        """按会话现算工具,其余照 bub 的规矩来。"""

        async def prepare_tools(self, tape: Any, prompt: Any) -> list[Any]:
            return model_tools(bub_tools(session, registry))

    return SessionAgent(
        model=LiteLLMModelClient(llm or LLMService()),
        system_prompt=SYSTEM_PROMPT,
        max_steps=MAX_STEPS,
        name="gweiops-console",
    )


__all__ = ["HAS_BUB", "LiteLLMModelClient", "chat", "model_spec", "session_agent"]
