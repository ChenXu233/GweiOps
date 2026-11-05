# plugins/builtin/agents/intent-llm/plugin.py
"""让模型起草 intent —— 环里第一次出现模型,所以约束写死在代码里。

它只产出意图:做什么、为什么、依据什么。执行权、判定权、撤销权都不在这里:
模型点了 compose.scale,平台照常读窗口、照常按人的响应时延判定、验证不过照样回滚。

所以这个插件只有一条硬约束:**不许编**。

- 模型挂了、答非所问、答不出 JSON → 空 effects,理由写进 rationale。
- 模型点了这个部署里没人声明过的能力 → 从 effects 里剔除,并写明剔了什么。
- 空 effects 是合法结论("现在不需要动"),不是失败。

参数名从清单里来,不从模型想象里来:菜单由 registry.declared_effects() 给出,
它只包含真的声明过 execute / undo / window / verify 的能力。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable, Optional

from engine.change_unit.intent import Intent, parse_intent
from engine.llm.client import LLMService
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

SYSTEM_PROMPT = """你是运维变更的意图提供者。你只提出意图,不执行任何操作,也拿不到下游凭据。

硬性要求:
1. 只输出一个 JSON 对象。不要解释,不要 Markdown 围栏。
2. 字段:summary(一句话)、evidence(数组)、effects(数组)、rationale(为什么这么做)。
3. evidence 每项形如 {"kind": "...", "ref": "..."};kind 用信号来源、history 之类的短词,ref 是可核对的原文。
4. effects 每项形如 {"capability": "...", "args": {...}}。capability 只能取「可用能力」里列出的值,
   args 只能用该能力后面列出的参数名,值要能从信号或近期结论里推出来;推不出来就不要提这个动作。
5. 拿不准就给 "effects": []。空的效果是合法结论,编一个动作出来不是。
"""

_SIGNAL_LIMIT = 4000


def _registry_menu() -> dict[str, dict[str, Any]]:
    from engine.plugin_manager import registry

    return registry.declared_effects()


def _decline(signal: dict[str, Any], why: str) -> Intent:
    """没有动作也是一种结论。理由要能让早上的人读懂,不能只写"失败"。"""
    return parse_intent(
        {
            "summary": f"信号「{signal.get('title', '')}」这次没有可执行的动作",
            "evidence": [
                {
                    "kind": signal.get("source", "signal"),
                    "ref": signal.get("subject") or signal.get("title", ""),
                }
            ],
            "effects": [],
            "rationale": why,
        }
    )


def _extract_json(text: Any) -> dict[str, Any]:
    """模型爱把 JSON 包在围栏里,前后再带一句客套。只取第一个 { 到最后一个 }。"""
    if not isinstance(text, str):
        raise ValueError("回答不是文本")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回答里没有 JSON 对象")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON 不是对象")
    return value


def _history_note(history: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in history:
        verdict = str(row.get("verdict") or "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
    detail = "、".join(f"{k} {v}" for k, v in sorted(counts.items()))
    return f"最近 {len(history)} 条账本结论:{detail}"


def _user_prompt(
    signal: dict[str, Any],
    menu: dict[str, dict[str, Any]],
    history: list[dict[str, Any]],
) -> str:
    payload = json.dumps(signal, ensure_ascii=False, indent=2)
    if len(payload) > _SIGNAL_LIMIT:
        payload = payload[:_SIGNAL_LIMIT] + "\n…(已截断)"

    lines = ["信号:", payload, "", "可用能力(只有这些能被接受):"]
    for capability, decl in sorted(menu.items()):
        args = "、".join(decl.get("args") or []) or "无参数"
        label = decl.get("label") or ""
        lines.append(f"- {capability}({args}) {label}".rstrip())

    if history:
        lines += [
            "",
            "这个租户最近的账本结论(参考,不要照抄):",
            json.dumps(history, ensure_ascii=False, indent=2),
        ]

    lines += ["", "只输出 JSON。"]
    return "\n".join(lines)


def _accept(
    intent: Intent, menu: dict[str, dict[str, Any]], history: list[dict[str, Any]]
) -> Intent:
    """模型给的东西里,只有能兑现的部分留下。"""
    kept: list[dict[str, Any]] = []
    dropped: set[str] = set()
    for effect in intent.effects:
        capability = effect["capability"]
        if capability in menu:
            kept.append(effect)
        else:
            dropped.add(capability)

    rationale = intent.rationale
    if dropped:
        names = "、".join(sorted(dropped))
        rationale += f"(模型还提了 {names},但这个部署里没有插件声明它们,已剔除)"

    evidence = list(intent.evidence)
    if history:
        evidence.append({"kind": "history", "ref": _history_note(history)})

    return replace(
        intent,
        effects=tuple(kept),
        evidence=tuple(evidence),
        rationale=rationale,
    )


class LLMIntentPlanner(PluginBase):
    # 这个提供者要用账本证据。工作流看到它才去读履历,别的实现不用为此付一次查询。
    wants_history = True

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        menu_provider: Optional[Callable[[], dict[str, dict[str, Any]]]] = None,
    ) -> None:
        self.llm = llm_service or LLMService()
        self.menu_provider = menu_provider or _registry_menu
        self.binding = ""
        self.tenant = ""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="intent-llm",
            version="0.1.0",
            type=PluginType.AGENT,
            description="让模型起草 intent;拿不准就给空 effects",
            capabilities=["intent.propose"],
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
        if task != "propose":
            return {"status": "error", "message": f"Unknown task: {task}"}
        return (await self.propose(params)).to_dict()

    async def propose(self, params: dict[str, Any]) -> Intent:
        signal = params.get("signal") or {}
        if not isinstance(signal, dict) or not signal.get("title"):
            raise ValueError("signal 缺少 title")

        menu = self.menu_provider()
        if not menu:
            return _decline(
                signal, "这个部署里没有插件声明过可撤销的效果,能提的动作是空的。"
            )

        history = params.get("history") or []
        try:
            answer = await self.llm.call(
                SYSTEM_PROMPT, _user_prompt(signal, menu, history)
            )
            intent = parse_intent(_extract_json(answer.content))
        except Exception as exc:
            return _decline(
                signal,
                f"模型没有给出可用的 intent,这次不猜({type(exc).__name__}: {exc})",
            )

        return _accept(intent, menu, history)
