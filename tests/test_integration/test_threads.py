# tests/test_integration/test_threads.py
"""话题:PR 评论与 issue 评论是同一件事,只是落在同一张纸的两面。

这一层要回答一个问题:同一个话题上再提一次改动,平台知道该接着哪个分支吗。
"""

from __future__ import annotations

import asyncio

from engine.change_unit import JsonlLedger
from engine.change_unit.threads import open_pull_on, topic_of

TOPIC = "ChenXu233/GweiOps#7"


def _row(unit, *, topic, head, verdict="kept", handle="7", capability="pr.open", url=""):
    return {
        "id": unit,
        "verdict": verdict,
        "handle": handle,
        "intent": {"topic": topic, "tool": capability},
        "effect": {
            "capability": capability,
            "args": {"repo": "ChenXu233/GweiOps", "head": head},
        },
        "facts": {"url": url},
    }


class FakeLedger:
    def __init__(self, rows):
        self.rows = rows

    async def latest(self, tenant="", limit=200):
        return self.rows[:limit]


def test_a_topic_is_repo_and_number():
    assert topic_of("ChenXu233/GweiOps", 7) == "ChenXu233/GweiOps#7"
    assert topic_of("", 7) == ""


def test_the_open_pull_on_a_topic_is_found():
    ledger = FakeLedger([_row("u1", topic=TOPIC, head="gwei/a", url="https://x/pull/7")])

    found = asyncio.run(open_pull_on(ledger, "default", TOPIC))

    assert found == {
        "repo": "ChenXu233/GweiOps",
        "head": "gwei/a",
        "pull": "7",
        "url": "https://x/pull/7",
    }


def test_a_rolled_back_pull_no_longer_counts():
    """撤掉的 PR 不算"还开着":下次该新开一个,而不是往已经关掉的分支上提交。"""
    ledger = FakeLedger([
        _row("u1", topic=TOPIC, head="gwei/a", verdict="rolled_back"),
    ])

    assert asyncio.run(open_pull_on(ledger, "default", TOPIC)) is None


def test_another_topic_does_not_leak_in():
    rows = [
        _row("u1", topic="ChenXu233/GweiOps#9", head="gwei/other"),
        _row("u2", topic=TOPIC, head="gwei/mine"),
    ]

    found = asyncio.run(open_pull_on(FakeLedger(rows), "default", TOPIC))

    assert found["head"] == "gwei/mine"


def test_a_broken_ledger_is_not_a_crash():
    class Broken:
        async def latest(self, **kwargs):
            raise RuntimeError("db down")

    assert asyncio.run(open_pull_on(Broken(), "default", TOPIC)) is None


def test_the_ledger_records_the_topic(tmp_path):
    """话题要记在单元上 —— 下次评论时平台就是靠它认出这条线的。"""
    from engine.agent import ToolCall, run_tool

    class Provider:
        binding = "github"
        tenant = ""

        async def window(self, effect, handle):
            from engine.change_unit import Window

            return Window(unbounded=True, source="fake")

        async def execute(self, task, args):
            return {"handle": "7"}

        async def undo(self, task, args, handle):
            return {}

        async def verify(self, effect, handle):
            return True, {}

    class Registry:
        def declared_effects(self):
            return {"pr.open": {"label": "开 PR", "args": ["repo", "head", "files"]}}

        def effect_decl(self, capability, tenant="", binding=""):
            from engine.plugin_manager.manifest import EffectDecl

            return Provider(), EffectDecl(
                capability="pr.open",
                execute_task="open_pull",
                undo_task="close_pull",
                undo_kind="symmetric",
                window_read="pull_open",
                verify=({"query": "pull_open", "expect": "true"},),
                label="开 PR",
                execute_args=("repo", "head", "files"),
            )

    ledger = JsonlLedger(tmp_path / "l.jsonl")
    asyncio.run(
        run_tool(
            ToolCall("pr.open", {"repo": "Chenxu233/GweiOps", "head": "gwei/a", "files": []}),
            registry=Registry(),
            ledger=ledger,
            tenant="default",
            binding="github",
            topic=TOPIC,
        )
    )

    rows = asyncio.run(ledger.latest())
    assert rows[-1]["intent"]["topic"] == TOPIC
