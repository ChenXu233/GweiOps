# plugins/builtin/agents/intent-builder/plugin.py
"""intent 提供者的参考实现。

现在它用已有的 issue.analyze / patch.generate 拼出一个 intent;
将来换成 harness 时,这个插件整体被替换,调用方(工作流)一行不改。

推理提供者只产出 intent,不执行效果,也不持有下游凭据。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from engine.change_unit.intent import Intent, parse_intent
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

Resolver = Callable[[str, dict], Awaitable[dict]]


def _default_resolver() -> Resolver:
    from engine.plugin_manager import registry

    async def resolve(capability: str, params: dict) -> dict:
        return await registry.run_capability(capability, params)

    return resolve


class IntentBuilder(PluginBase):
    def __init__(self, resolver: Optional[Resolver] = None) -> None:
        self._resolve = resolver or _default_resolver()
        self.binding = ""
        self.tenant = ""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="intent-builder",
            version="0.1.0",
            type=PluginType.AGENT,
            description="把信号与已有分析组装成 intent(harness 接缝的参考实现)",
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
        intent = await self.propose(params)
        return intent.to_dict()

    async def propose(self, params: dict[str, Any]) -> Intent:
        signal = params.get("signal") or {}
        if not isinstance(signal, dict) or not signal.get("title"):
            raise ValueError("signal 缺少 title")

        analysis = params.get("analysis")
        if analysis is None:
            analysis = await self._resolve(
                "issue.analyze",
                {"issue": {"title": signal.get("title", ""), "body": signal.get("body", "")}},
            )

        patches = params.get("patches")
        if patches is None and params.get("want_patches"):
            patches = list(
                (await self._resolve(
                    "patch.generate",
                    {"title": signal.get("title", ""), "body": signal.get("body", "")},
                )).get("patches", [])
            )

        return parse_intent(self._assemble(signal, analysis, patches or []))

    @staticmethod
    def _assemble(
        signal: dict[str, Any], analysis: dict[str, Any], patches: list[dict]
    ) -> dict[str, Any]:
        from engine.shared.render import format_suggestion_reply as _format_suggestion_reply

        evidence = [{"kind": "issue", "ref": f"{signal.get('repo', '')}#{signal.get('issue_number', '')}"}]
        if analysis.get("labels"):
            evidence.append({"kind": "labels", "ref": ",".join(analysis["labels"])})
        if analysis.get("llm_analysis"):
            evidence.append({"kind": "analysis", "ref": str(analysis["llm_analysis"])[:280]})

        body = _format_suggestion_reply(
            {
                "title": signal.get("title", ""),
                "repo_full_name": signal.get("repo", ""),
                "issue_number": signal.get("issue_number", 0),
            },
            patches,
        ) if patches else (analysis.get("reply") or analysis.get("llm_analysis") or "")

        effects = [
            {
                "capability": "comment.create",
                "args": {
                    "repo": signal.get("repo", ""),
                    "issue_number": signal.get("issue_number", 0),
                    "body": body,
                },
            }
        ]

        return {
            "summary": f"针对 {signal.get('title', '')} 提出 {len(patches)} 个候选补丁" if patches
                       else f"针对 {signal.get('title', '')} 给出回评",
            "evidence": evidence,
            "effects": effects,
            "rationale": "复用现有 issue.analyze / patch.generate 的结论;效果只提议,不执行。",
        }
