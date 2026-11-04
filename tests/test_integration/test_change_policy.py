# tests/test_integration/test_change_policy.py
"""策略与阻断出口:什么时候可以直接做,阻断之后人怎么接手。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from engine.change_unit import (
    BLOCK,
    EXECUTE,
    AwayWindow,
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

# 2026-11-04 周三 / 11-06 周五 / 11-09 周一
WEDNESDAY_NOON = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
FRIDAY_EVENING = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)
MONDAY_MORNING = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)


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
# 策略:都收敛到"人到能反应过来时,还撤得回来吗"
# ---------------------------------------------------------------------------


def test_unknown_window_blocks():
    provider = FakeProvider(pre=Window())
    unit = asyncio.run(apply(_unit(), provider, at=WEDNESDAY_NOON))
    assert unit.verdict == VERDICT_BLOCKED
    assert "读不到" in unit.reason
    assert provider.executed == 0


def test_window_shorter_than_human_latency_blocks():
    provider = FakeProvider(pre=Window(seconds=3600, source="revision"))
    unit = asyncio.run(apply(_unit(), provider, at=WEDNESDAY_NOON))
    assert unit.verdict == VERDICT_BLOCKED
    assert "盖不住" in unit.reason
    assert provider.executed == 0


def test_window_longer_than_human_latency_runs():
    provider = FakeProvider(pre=Window(seconds=9 * 3600, source="revision"))
    unit = asyncio.run(apply(_unit(), provider, at=WEDNESDAY_NOON))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1
    assert unit.facts["gate"].startswith("窗口 9 小时")


def test_weekend_raises_the_bar_for_bounded_windows():
    """周五傍晚:要盖住的不是 8 小时,是到周一早上。"""
    provider = FakeProvider(pre=Window(seconds=9 * 3600, source="revision"))
    unit = asyncio.run(apply(_unit(), provider, at=FRIDAY_EVENING))
    assert unit.verdict == VERDICT_BLOCKED
    assert "无人值守" in unit.reason
    assert provider.executed == 0


def test_weekend_still_allows_symmetric_undo():
    """对称撤销不依赖下游保留任何东西,周末也撤得回来。"""
    provider = FakeProvider(pre=Window(unbounded=True, source="project_present"))
    unit = asyncio.run(apply(_unit(), provider, at=FRIDAY_EVENING))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_allow_list_narrows_the_night_scope():
    policy = Policy(allow_capabilities=("compose.scale",))
    blocked = asyncio.run(
        apply(_unit("comment.create"), FakeProvider(), policy=policy, at=WEDNESDAY_NOON)
    )
    assert blocked.verdict == VERDICT_BLOCKED
    assert "不在夜间放行范围" in blocked.reason

    allowed = asyncio.run(
        apply(_unit("compose.scale"), FakeProvider(), policy=policy, at=WEDNESDAY_NOON)
    )
    assert allowed.verdict == VERDICT_KEPT


def test_policy_decide_is_pure():
    decision = Policy().decide(_unit(), Window(seconds=60), WEDNESDAY_NOON)
    assert decision.action == BLOCK
    assert decision.response_s == Policy().human_response_s


# ---------------------------------------------------------------------------
# 无人值守时段本身
# ---------------------------------------------------------------------------


def test_away_window_bounds():
    away = AwayWindow()  # 周五 18:00 → 周一 09:00
    assert away.contains(datetime(2026, 11, 6, 17, 59, tzinfo=timezone.utc)) is False
    assert away.contains(datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)) is True
    assert away.contains(datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)) is True
    assert away.contains(MONDAY_MORNING) is True
    assert away.contains(datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)) is False
    assert away.contains(WEDNESDAY_NOON) is False


def test_away_window_ends_at_next_boundary():
    away = AwayWindow()
    assert away.ends_at(FRIDAY_EVENING) == datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    assert away.ends_at(MONDAY_MORNING) == datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    # 不在窗口里时,"下一次结束"是下一个周一,而不是本周一(已经过去了)
    assert away.ends_at(WEDNESDAY_NOON) == datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def test_response_seconds_is_constant_outside_away():
    policy = Policy()
    assert policy.response_seconds(WEDNESDAY_NOON) == 8 * 3600
    inside = policy.response_seconds(FRIDAY_EVENING)
    assert inside == int(
        (datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc) - FRIDAY_EVENING).total_seconds()
    )


# ---------------------------------------------------------------------------
# 阻断的出口:放行 / 否决
# ---------------------------------------------------------------------------


def test_approve_runs_even_when_window_is_unknown(tmp_path):
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    provider = FakeProvider(pre=Window(), post=Window(unbounded=True))

    unit = asyncio.run(apply(_unit(), provider, ledger, at=WEDNESDAY_NOON))
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
    unit = asyncio.run(apply(unit, provider, ledger, at=WEDNESDAY_NOON))
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