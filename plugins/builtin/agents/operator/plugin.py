# plugins/builtin/agents/operator/plugin.py
"""operator —— 循环在这里,不在平台里。

平台只提供出口([engine/agent/tools.py]):什么算离开沙箱、每次离开怎么记账。
怎么想、想几步、看到结果之后怎么改主意,是插件的事——和 intent-builder、
sensor、fixer 同一类东西,换一个实现就换一种 agent。

这一版在平台进程里跑,所以它没有 shell:能看(只读出口)、能改(变更单元),
不能编辑代码。要 shell 的那个,是去驱动 harness 子进程的另一个插件——
同一个接缝,换实现。

它也不执行"计划":每一步都是一个独立的变更单元,各自可撤、各自记账。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from engine.agent import ToolCall, run_tool, tool_specs
from engine.change_unit import create_ledger
from engine.llm.client import LLMService
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

# 一次事故最多几次出口调用。够它看两眼看一步再收尾,又不会把账单跑飞。
DEFAULT_MAX_EXITS = 8

SYSTEM_PROMPT = """你是值班的运维 agent。你只能通过给定的工具改变外部世界。

规则:
1. 每次改世界的调用都会经过平台判定,可能被拒绝或撤销。被拒绝不是错误,是结论。
2. 被拒绝或回滚时,读 reason,换办法或者停手。同一个动作不要反复试。
3. 拿不准就先看,不要猜。没有把握时什么都不做,是合格的处理。
4. 收工时用一两句话说清楚:做了什么、结果如何、还剩什么没解决。
"""


class OperatorAgent(PluginBase):
    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        registry: Any = None,
        ledger: Any = None,
        max_exits: int = DEFAULT_MAX_EXITS,
    ) -> None:
        self.llm = llm_service or LLMService()
        self._registry = registry
        self._ledger = ledger
        self.max_exits = max_exits
        self.binding = ""
        self.tenant = ""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="operator",
            version="0.1.0",
            type=PluginType.AGENT,
            description="带出口的值班 agent",
            capabilities=["incident.handle"],
        )

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: dict[str, Any]) -> dict[str, Any]:
        if task != "handle":
            return {"status": "error", "message": f"Unknown task: {task}"}
        return await self.handle(params)

    # ------------------------------------------------------------------

    def _reg(self) -> Any:
        if self._registry is not None:
            return self._registry
        from engine.plugin_manager import registry

        return registry

    async def handle(self, params: dict[str, Any]) -> dict[str, Any]:
        signal = params.get("signal") or {}
        if not isinstance(signal, dict) or not signal.get("title"):
            raise ValueError("signal 缺少 title")

        reg = self._reg()
        specs = tool_specs(reg)
        if not specs:
            return {
                "summary": "这个部署里没有声明过任何出口,agent 无从下手。",
                "steps": [],
                "counts": {},
                "exhausted": False,
            }

        # 整场事故共用一本账:每一步都是一个独立单元,但落在一起才看得出经过。
        ledger = self._ledger if self._ledger is not None else create_ledger()
        tenant = str(params.get("tenant") or "")
        binding = str(params.get("binding") or "")
        idem_base = str(params.get("idem_base") or "")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(signal)},
        ]

        steps: list[dict[str, Any]] = []
        used = 0
        say = ""
        budget = max(1, self.max_exits)

        while used < budget:
            turn = await self.llm.call_with_tools(messages, specs)
            say = turn.content or say
            if not turn.tool_calls:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content or "",
                    "tool_calls": [
                        {
                            "id": call.get("id") or f"call-{used}",
                            "type": "function",
                            "function": {
                                "name": call.get("name", ""),
                                "arguments": json.dumps(
                                    call.get("args") or {}, ensure_ascii=False
                                ),
                            },
                        }
                        for call in turn.tool_calls
                    ],
                }
            )

            for call in turn.tool_calls:
                call_id = call.get("id") or f"call-{used}"
                if used >= budget:
                    # 每个 tool_call 都必须有回音,否则下一轮对话不合法。
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": json.dumps(
                                {"ok": False, "reason": "这次事故的工具次数用完了"},
                                ensure_ascii=False,
                            ),
                        }
                    )
                    continue

                result = await run_tool(
                    ToolCall(str(call.get("name") or ""), dict(call.get("args") or {})),
                    registry=reg,
                    ledger=ledger,
                    tenant=tenant,
                    binding=binding,
                    idem_base=idem_base,
                    index=used,
                    summary=str(signal.get("title") or ""),
                )
                used += 1
                steps.append(
                    {
                        "index": used,
                        "tool": call.get("name", ""),
                        "args": dict(call.get("args") or {}),
                        "result": result.to_dict(),
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result.to_dict(), ensure_ascii=False),
                    }
                )

        return {
            "summary": say or "没有可执行的动作",
            "steps": steps,
            "counts": _counts(steps),
            "exhausted": used >= budget,
        }


def _counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for step in steps:
        result = step.get("result") or {}
        key = str(result.get("verdict") or ("ok" if result.get("ok") else "error"))
        out[key] = out.get(key, 0) + 1
    return out


def _user_prompt(signal: dict[str, Any]) -> str:
    payload = json.dumps(signal, ensure_ascii=False, indent=2)
    if len(payload) > 4000:
        payload = payload[:4000] + "\n…(已截断)"
    return (
        "一条告警:" + payload + "\n\n"
        "工具会告诉你这个部署里能做什么、每个动作的参数。"
        "改世界的动作被拒绝时,reason 里会写清楚为什么。"
    )
