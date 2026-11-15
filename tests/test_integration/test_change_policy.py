# tests/test_integration/test_change_policy.py
"""策略与阻断出口:什么能自动做,阻断之后人怎么接手。

契约第 4 节:变更分两类——自动收敛(名单里点名、能自己收敛)与人在回路(其余全部)。
这里的用例只回答第一类怎么判;缺省是"空 = 一律等人"。
"""

from __future__ import annotations

import asyncio

import pytest

from engine.change_unit import (
    BLOCK,
    ChangeUnit,
    Effect,
    JsonlLedger,
    Policy,
    VERDICT_BLOCKED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    VERDICT_VETOED,
    Window,
    apply,
    approve,
    veto,
)

BINDING = "local"


class FakeProvider:
    binding = BINDING
    tenant = ""

    def __init__(
        self,
        *,
        pre: Window | None = None,
        post: Window | None = None,
        handle: str | None = "h-1",
        verify_result: tuple[bool, dict] = (True, {"running": 2}),
    ) -> None:
        self.pre = pre or Window(unbounded=True, source="fake")
        self.post = post or Window(unbounded=True, source="fake")
        self.handle = handle
        self.verify_result = verify_result
        self.executed = 0
        self.undone = 0

    async def window(self, effect, handle):
        return self.post if handle is not None else self.pre

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": self.handle}

    async def undo(self, task, args, handle):
        self.undone += 1
        return {}

    async def verify(self, effect, handle):
        return self.verify_result


def _unit(capability: str = "compose.scale", verdict: str = "") -> ChangeUnit:
    unit = ChangeUnit(
        intent={"summary": "把 web 扩到 2 副本"},
        effect=Effect(
            task="scale",
            args={"service": "web"},
            undo_task="undo_scale",
            capability=capability,
        ),
        binding=BINDING,
    )
    if verdict:
        unit.verdict = verdict
    return unit


# ---------------------------------------------------------------------------
# 判定:名单决定"要不要人",窗口决定"能不能自己收敛"
# ---------------------------------------------------------------------------


def test_empty_allow_list_blocks_everything(monkeypatch):
    """缺省口径:什么都没点名,一律等人。窗口再长也不自动做。"""
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "autonomous_capabilities", "")

    provider = FakeProvider(pre=Window(unbounded=True))
    unit = asyncio.run(apply(_unit(), provider))

    assert unit.verdict == VERDICT_BLOCKED
    assert "不在自动收敛范围" in unit.reason
    assert provider.executed == 0


def test_listed_capability_runs_without_a_human():
    policy = Policy(autonomous_capabilities=("compose.scale",))
    provider = FakeProvider(pre=Window(unbounded=True, source="project_present"))

    unit = asyncio.run(apply(_unit(), provider, policy=policy))

    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1
    assert unit.facts["gate"].startswith("能力 compose.scale 已列入自动收敛范围")


def test_capability_outside_the_list_blocks():
    policy = Policy(autonomous_capabilities=("compose.scale",))
    provider = FakeProvider()

    blocked = asyncio.run(apply(_unit("comment.create"), provider, policy=policy))

    assert blocked.verdict == VERDICT_BLOCKED
    assert "不在自动收敛范围" in blocked.reason
    assert provider.executed == 0


def test_wildcard_allows_every_capability():
    policy = Policy(autonomous_capabilities=("*",))
    provider = FakeProvider()

    unit = asyncio.run(apply(_unit("anything.at.all"), provider, policy=policy))

    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_unknown_window_blocks_even_when_listed():
    """点名了也不够:读不到窗口,就兑现不了撤销。"""
    policy = Policy(autonomous_capabilities=("compose.scale",))
    provider = FakeProvider(pre=Window())

    unit = asyncio.run(apply(_unit(), provider, policy=policy))

    assert unit.verdict == VERDICT_BLOCKED
    assert "读不到" in unit.reason
    assert provider.executed == 0


def test_a_short_window_is_enough():
    """窗口只对验证观察期负责,不再拿去比"人多久会醒"。"""
    policy = Policy(autonomous_capabilities=("compose.scale",))
    provider = FakeProvider(pre=Window(seconds=60, source="revision"))

    unit = asyncio.run(apply(_unit(), provider, policy=policy))

    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_a_count_based_window_does_not_block():
    """按次数保留的下游(_kubectl rollout undo_)不该被当成不可逆。"""
    policy = Policy(autonomous_capabilities=("compose.scale",))
    provider = FakeProvider(
        pre=Window(unbounded=True, estimated=True, source="revision_history")
    )

    unit = asyncio.run(apply(_unit(), provider, policy=policy))

    assert unit.verdict == VERDICT_KEPT
    assert "算不出到期" in unit.facts["gate"]


def test_policy_decide_is_pure():
    decision = Policy().decide(_unit(), Window(seconds=60))
    assert decision.action == BLOCK
    assert "不在自动收敛范围" in decision.reason


def test_default_policy_reads_the_deployment_setting(monkeypatch):
    from engine.shared.config import config
    from engine.change_unit.runner import _default_policy

    monkeypatch.setattr(config.settings, "autonomous_capabilities", " compose.scale , comment.create ")
    policy = _default_policy()
    assert policy.autonomous_capabilities == ("compose.scale", "comment.create")

    monkeypatch.setattr(config.settings, "autonomous_capabilities", "")
    assert _default_policy().autonomous_capabilities == ()


# ---------------------------------------------------------------------------
# 阻断的出口:放行 / 否决
# ---------------------------------------------------------------------------


def test_approve_runs_even_when_window_is_unknown(tmp_path):
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    provider = FakeProvider(pre=Window(), post=Window(unbounded=True))

    unit = asyncio.run(apply(_unit(), provider, ledger))
    assert unit.verdict == VERDICT_BLOCKED

    unit = asyncio.run(approve(unit, provider, ledger, by="值班人", reason="现在就做"))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1
    assert unit.facts["authorized_by"] == "值班人"
    assert unit.facts["blocked_reason"].startswith("窗口读不到")

    rows = asyncio.run(ledger.read())
    assert [row["verdict"] for row in rows] == [VERDICT_BLOCKED, VERDICT_KEPT]
    assert rows[1]["facts"]["authorized_by"] == "值班人"


def test_approve_of_irreversible_is_recorded_as_irreversible():
    """人放了手,但撤销兑现不了——账本不许把它写成"可撤"。"""
    provider = FakeProvider(pre=Window(), post=Window())
    unit = _unit(verdict=VERDICT_BLOCKED)
    unit = asyncio.run(approve(unit, provider))
    assert provider.executed == 1
    assert unit.verdict == VERDICT_IRREVERSIBLE
    assert "读不到窗口" in unit.reason


def test_approve_still_rolls_back_when_verify_fails():
    provider = FakeProvider(pre=Window(), verify_result=(False, {"error": "5xx"}))
    unit = _unit(verdict=VERDICT_BLOCKED)
    unit = asyncio.run(approve(unit, provider))
    assert unit.verdict == VERDICT_ROLLED_BACK
    assert provider.undone == 1


def test_approve_is_not_swallowed_by_idempotency(tmp_path):
    """被阻断的单元已经有同键记录:放行不能被"上次已经做完"短接。"""
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    provider = FakeProvider(pre=Window())

    unit = _unit()
    unit.idempotency_key = "wf-1:effects:effect:0"
    unit = asyncio.run(apply(unit, provider, ledger))
    assert unit.verdict == VERDICT_BLOCKED
    assert provider.executed == 0

    unit = asyncio.run(approve(unit, provider, ledger, by="值班人"))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1
    assert [row["verdict"] for row in asyncio.run(ledger.read())] == [VERDICT_BLOCKED, VERDICT_KEPT]


def test_approve_requires_a_blocked_unit():
    with pytest.raises(ValueError):
        asyncio.run(approve(_unit(verdict=VERDICT_KEPT), FakeProvider()))


def test_veto_appends_a_decision_row(tmp_path):
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    unit = _unit(verdict=VERDICT_BLOCKED)
    unit = asyncio.run(veto(unit, ledger, by="值班人", reason="等周一"))
    assert unit.verdict == VERDICT_VETOED
    assert unit.facts["vetoed_by"] == "值班人"
    assert [row["verdict"] for row in asyncio.run(ledger.read())] == [VERDICT_VETOED]


def test_veto_refuses_an_executed_unit():
    with pytest.raises(ValueError):
        asyncio.run(veto(_unit(verdict=VERDICT_KEPT)))
