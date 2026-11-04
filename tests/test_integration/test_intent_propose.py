# tests/test_integration/test_intent_propose.py
"""intent 的形状与参考提供者:提供者只提议,不执行。"""

import asyncio
import importlib

import pytest

from engine.change_unit.intent import IntentError, parse_intent

builder_mod = importlib.import_module("plugins.builtin.agents.intent-builder.plugin")


class FakeResolver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, capability, params):
        self.calls.append((capability, params))
        if capability == "issue.analyze":
            return {"labels": ["bug"], "llm_analysis": "根因是空指针", "reply": "建议修复空指针"}
        if capability == "patch.generate":
            return {
                "patches": [
                    {"type": "PATCH", "risk": "低", "description": "加判空", "diff": "--- a\n+++ b"}
                ]
            }
        raise LookupError(capability)


SIGNAL = {"source": "issue", "repo": "ChenXu233/GweiOps", "issue_number": 1,
          "title": "空指针崩溃", "body": "打开页面就崩"}


def test_parse_intent_rejects_missing_summary():
    with pytest.raises(IntentError, match="summary"):
        parse_intent({"evidence": [], "effects": [{"capability": "c", "args": {}}]})


def test_parse_intent_allows_no_effect():
    """结论是"不用动"也是合法判断,不该逼提供者编一个动作出来。"""
    intent = parse_intent({"summary": "s", "effects": []})
    assert intent.effects == ()


def test_parse_intent_rejects_effect_without_capability():
    with pytest.raises(IntentError, match="capability"):
        parse_intent({"summary": "s", "effects": [{"args": {}}]})


def test_parse_intent_normalizes():
    intent = parse_intent(
        {"summary": "  做点什么  ", "evidence": [{"kind": "issue", "ref": "#1"}],
         "effects": [{"capability": "comment.create", "args": {"body": "x"}}]}
    )
    assert intent.summary == "做点什么"
    assert intent.version == 1
    assert intent.to_dict()["effects"][0]["capability"] == "comment.create"


def test_propose_uses_given_analysis_without_call():
    resolver = FakeResolver()
    builder = builder_mod.IntentBuilder(resolver=resolver)
    intent = asyncio.run(
        builder.propose({"signal": SIGNAL, "analysis": {"reply": "已有结论"}})
    )
    assert resolver.calls == []
    assert intent.effects[0]["capability"] == "comment.create"
    assert intent.effects[0]["args"]["repo"] == "ChenXu233/GweiOps"
    assert intent.effects[0]["args"]["body"] == "已有结论"


def test_propose_fetches_analysis_when_missing():
    resolver = FakeResolver()
    builder = builder_mod.IntentBuilder(resolver=resolver)
    intent = asyncio.run(builder.propose({"signal": SIGNAL}))
    assert [c[0] for c in resolver.calls] == ["issue.analyze"]
    assert intent.evidence[1]["kind"] == "labels"


def test_propose_fetches_patches_when_asked():
    resolver = FakeResolver()
    builder = builder_mod.IntentBuilder(resolver=resolver)
    intent = asyncio.run(builder.propose({"signal": SIGNAL, "want_patches": True}))
    assert [c[0] for c in resolver.calls] == ["issue.analyze", "patch.generate"]
    assert "候选补丁" in intent.summary
    assert "方案 1" in intent.effects[0]["args"]["body"]


def test_propose_requires_title():
    builder = builder_mod.IntentBuilder(resolver=FakeResolver())
    with pytest.raises(ValueError, match="title"):
        asyncio.run(builder.propose({"signal": {"body": "x"}}))


def test_execute_task_returns_jsonable_dict():
    builder = builder_mod.IntentBuilder(resolver=FakeResolver())
    out = asyncio.run(
        builder.execute_task("propose", {"signal": SIGNAL, "analysis": {"reply": "r"}})
    )
    assert set(out) == {"version", "summary", "evidence", "effects", "rationale"}
    assert isinstance(out["effects"], list)
