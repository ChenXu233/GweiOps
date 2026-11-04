# engine/change_unit/intent.py
"""intent 的形状 —— 推理提供者唯一被允许产出的东西。

它描述「打算做什么」,不描述「已经做了什么」:效果由控制面按 binding 解析后执行,
提供者拿不到下游凭据,也拿不到执行结果。

校验在控制面做:形状不对就是 blocked,不重试——重试归提供者,判断归平台。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INTENT_VERSION = 1

_DEFAULT_SUMMARY = "(无摘要)"


class IntentError(ValueError):
    """意图形状不合法。"""


@dataclass(frozen=True)
class Intent:
    summary: str
    evidence: tuple[dict[str, Any], ...]
    effects: tuple[dict[str, Any], ...]
    rationale: str
    version: int = INTENT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "effects": list(self.effects),
            "rationale": self.rationale,
        }


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise IntentError(message)


def parse_intent(payload: Any) -> Intent:
    """校验并规范化一个 intent。任何形状问题都抛 IntentError。"""
    _require(isinstance(payload, dict), "intent 必须是对象")

    summary = payload.get("summary")
    _require(isinstance(summary, str) and summary.strip() != "", "summary 必须是非空字符串")

    evidence = payload.get("evidence", [])
    _require(isinstance(evidence, list), "evidence 必须是列表")
    for item in evidence:
        _require(isinstance(item, dict), "evidence 的每一项必须是对象")
        _require(bool(item.get("kind")), "evidence 项缺少 kind")

    effects = payload.get("effects", [])
    _require(isinstance(effects, list), "effects 必须是列表")
    # effects 允许为空:结论是"不用动"也是合法判断,不该逼提供者编一个动作出来。
    for item in effects:
        _require(isinstance(item, dict), "effects 的每一项必须是对象")
        capability = item.get("capability")
        _require(
            isinstance(capability, str) and capability.strip() != "",
            "effect 缺少 capability",
        )
        _require(isinstance(item.get("args", {}), dict), "effect 的 args 必须是对象")

    rationale = payload.get("rationale", "")
    _require(isinstance(rationale, str), "rationale 必须是字符串")

    version = payload.get("version", INTENT_VERSION)
    _require(isinstance(version, int), "version 必须是整数")

    return Intent(
        summary=summary.strip(),
        evidence=tuple(evidence),
        effects=tuple(
            {"capability": item["capability"], "args": dict(item.get("args", {}))}
            for item in effects
        ),
        rationale=rationale,
        version=version,
    )
