# tests/test_integration/test_pipeline_intent.py
"""工作流接过 intent:没有提供者时兜底,有效果时走变更单元。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import engine.workflows.pipeline as pipeline
from engine.change_unit import Effect, Window


PAYLOAD = {
    "tenant_slug": "default",
    "repo_full_name": "ChenXu233/GweiOps",
    "issue_number": 7,
    "issue_github_id": 1,
    "repo_github_id": 2,
    "title": "崩溃",
    "body": "打开就崩",
    "source": "issue",
}


class FakeProvider:
    binding = "github"
    tenant = ""

    def __init__(self):
        self.executed = 0
        self.verified = 0

    def effect(self, capability, **args):
        return Effect(
            task="create_comment",
            args=args,
            undo_task="delete_comment",
            undo_kind="symmetric",
            capability=capability,
        )

    async def window(self, effect, handle):
        return Window(unbounded=True, source="fake")

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "42"}

    async def undo(self, task, args, handle):
        return {"deleted": handle}

    async def verify(self, effect, handle):
        self.verified += 1
        return True, {"found": True}


def test_propose_falls_back_without_provider():
    with patch.object(pipeline.registry, "run_capability", AsyncMock(side_effect=LookupError("none"))):
        intent = asyncio.run(
            pipeline._propose_intent_impl(PAYLOAD, {"reply": "建议这样改"}, [])
        )
    assert intent["effects"][0]["capability"] == "comment.create"
    assert intent["effects"][0]["args"]["body"] == "建议这样改"


def test_propose_falls_back_to_no_effect_without_reply():
    with patch.object(pipeline.registry, "run_capability", AsyncMock(side_effect=LookupError("none"))):
        intent = asyncio.run(pipeline._propose_intent_impl(PAYLOAD, {}, []))
    assert intent["effects"] == []


def test_apply_effects_runs_unit_and_records(tmp_path):
    provider = FakeProvider()
    intent = {
        "version": 1,
        "summary": "回评",
        "evidence": [{"kind": "issue", "ref": "#7"}],
        "effects": [{"capability": "comment.create", "args": {"body": "hi"}}],
        "rationale": "r",
    }
    allow = AsyncMock(return_value={"allowed": True, "payload": {"body": "hi"}})

    with patch.object(pipeline.registry, "resolve", return_value=provider), \
         patch.object(pipeline.hooks, "apply", allow), \
         patch.object(pipeline.config.settings, "change_ledger_path", str(tmp_path / "l.jsonl")):
        out = asyncio.run(pipeline._apply_effects_impl(intent, PAYLOAD, "wf-1:effects"))

    assert provider.executed == 1
    assert provider.verified == 1
    assert out["applied"][0]["verdict"] == "kept"
    assert out["applied"][0]["handle"] == "42"


def test_apply_effects_skips_vetoed_comment(tmp_path):
    provider = FakeProvider()
    intent = {
        "summary": "回评",
        "effects": [{"capability": "comment.create", "args": {"body": "hi"}}],
    }
    deny = AsyncMock(return_value={"allowed": False, "payload": {}})

    with patch.object(pipeline.registry, "resolve", return_value=provider), \
         patch.object(pipeline.hooks, "apply", deny), \
         patch.object(pipeline.config.settings, "change_ledger_path", str(tmp_path / "l.jsonl")):
        out = asyncio.run(pipeline._apply_effects_impl(intent, PAYLOAD, "wf-2:effects"))

    assert provider.executed == 0
    assert out["applied"][0]["verdict"] == "vetoed"


def test_apply_effects_without_effects_is_noop(tmp_path):
    provider = FakeProvider()
    intent = {"summary": "不用动", "effects": []}
    with patch.object(pipeline.registry, "resolve", return_value=provider), \
         patch.object(pipeline.config.settings, "change_ledger_path", str(tmp_path / "l.jsonl")):
        out = asyncio.run(pipeline._apply_effects_impl(intent, PAYLOAD, "wf-3:effects"))
    assert out["applied"] == []
