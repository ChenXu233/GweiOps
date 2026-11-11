# tests/test_integration/test_change_record.py
"""履历:账本里的旧结论,怎么变成下一次判定的证据。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from engine.change_unit import (
    BLOCK,
    EXECUTE,
    ChangeUnit,
    Effect,
    JsonlLedger,
    Policy,
    TrackRecord,
    VERDICT_BLOCKED,
    VERDICT_FAILED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_PENDING,
    VERDICT_ROLLED_BACK,
    VERDICT_UNKNOWN,
    VERDICT_VETOED,
    Window,
    apply,
    approve,
    summarize,
    track_record,
)

BINDING = "prod-web"
CAPABILITY = "compose.scale"
TENANT = "tenant-a"
NOON = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class FakeProvider:
    binding = BINDING
    tenant = ""

    def __init__(
        self,
        *,
        pre: Window | None = None,
        post: Window | None = None,
        handle: str | None = "h-1",
    ) -> None:
        self.pre = pre or Window(unbounded=True, source="fake")
        self.post = post or Window(unbounded=True, source="fake")
        self.handle = handle
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
        return True, {"running": 2}


def _unit(
    *,
    verdict: str = "",
    reason: str = "",
    tenant: str = TENANT,
    binding: str = BINDING,
    capability: str = CAPABILITY,
) -> ChangeUnit:
    unit = ChangeUnit(
        intent={"summary": "把 web 扩到 2 副本"},
        effect=Effect(
            task="scale",
            args={"service": "web"},
            undo_task="undo_scale",
            capability=capability,
        ),
        tenant=tenant,
        binding=binding,
        verdict=verdict,
        reason=reason,
    )
    return unit


def _row(verdict: str, **kw) -> dict:
    return _unit(verdict=verdict, **kw).to_dict()


def _seed(tmp_path, verdict: str, times: int = 3, **kw) -> JsonlLedger:
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    for _ in range(times):
        asyncio.run(ledger.append(_unit(verdict=verdict, **kw)))
    return ledger


# ---------------------------------------------------------------------------
# 聚合:什么算进分母,什么只是给人看
# ---------------------------------------------------------------------------


def test_no_history_is_empty_not_healthy():
    record = summarize([], binding=BINDING, capability=CAPABILITY)
    assert record.empty
    assert record.attempts == 0
    assert record.failure_rate == 0.0


def test_blocked_and_vetoed_stay_out_of_the_denominator():
    """拦住了不算摔过。把它们算成失败,等于因为正确地拦住而永久怀疑这个能力。"""
    rows = [_row(VERDICT_BLOCKED)] * 4 + [_row(VERDICT_VETOED)] * 2
    record = summarize(rows, binding=BINDING, capability=CAPABILITY)
    assert record.attempts == 0
    assert record.failures == 0
    assert record.blocked == 4
    assert record.vetoed == 2


def test_failed_stays_out_of_the_denominator_but_is_counted():
    """确定没动,对手上这个动作安不安全没有信息量;但它本身是个人要看的信号。"""
    rows = [_row(VERDICT_FAILED)] * 3 + [_row(VERDICT_KEPT)]
    record = summarize(rows, binding=BINDING, capability=CAPABILITY)
    assert record.attempts == 1
    assert record.failures == 0
    assert record.failed == 3


def test_unknown_counts_as_an_attempt_and_a_failure():
    """动没动都不知道,比已知撤不回来更说不清:进分母,也进失败数。"""
    rows = [_row(VERDICT_UNKNOWN), _row(VERDICT_KEPT)]
    record = summarize(rows, binding=BINDING, capability=CAPABILITY)
    assert record.attempts == 2
    assert record.failures == 1
    assert record.unknown == 1


def test_pending_rows_are_not_counted():
    record = summarize([_row(VERDICT_PENDING)], binding=BINDING, capability=CAPABILITY)
    assert record.attempts == 0


def test_other_binding_does_not_leak_in():
    rows = [_row(VERDICT_ROLLED_BACK, binding="prod-api")] * 3
    record = summarize(rows, binding=BINDING, capability=CAPABILITY)
    assert record.attempts == 0


def test_other_tenant_does_not_leak_in():
    rows = [_row(VERDICT_ROLLED_BACK, tenant="tenant-b")] * 3
    record = summarize(rows, binding=BINDING, capability=CAPABILITY, tenant=TENANT)
    assert record.attempts == 0


def test_irreversible_counts_as_a_failure_but_stays_distinct():
    rows = [_row(VERDICT_KEPT), _row(VERDICT_IRREVERSIBLE), _row(VERDICT_ROLLED_BACK)]
    record = summarize(rows, binding=BINDING, capability=CAPABILITY)
    assert record.attempts == 3
    assert record.failures == 2
    assert record.irreversible == 1
    assert record.rolled_back == 1


def test_lookback_keeps_the_newest_rows():
    # 账本给的是最新在前:最近两次是成的,再往前八次是回滚的
    rows = [_row(VERDICT_KEPT)] * 2 + [_row(VERDICT_ROLLED_BACK)] * 8
    record = summarize(rows, binding=BINDING, capability=CAPABILITY, lookback=2)
    assert record.attempts == 2
    assert record.kept == 2


def test_last_reason_comes_from_the_newest_attempt():
    rows = [
        _row(VERDICT_ROLLED_BACK, reason="验证未通过,已回滚"),
        _row(VERDICT_KEPT, reason="验证通过"),
    ]
    record = summarize(rows, binding=BINDING, capability=CAPABILITY)
    assert record.last_verdict == VERDICT_ROLLED_BACK
    assert record.last_reason == "验证未通过,已回滚"


def test_track_record_reads_the_ledger(tmp_path):
    ledger = _seed(tmp_path, VERDICT_ROLLED_BACK)
    record = asyncio.run(
        track_record(ledger, tenant=TENANT, binding=BINDING, capability=CAPABILITY)
    )
    assert record is not None
    assert record.attempts == 3
    assert record.failures == 3


def test_track_record_without_ledger_is_unknown_not_clean():
    assert asyncio.run(track_record(None, binding=BINDING)) is None


# ---------------------------------------------------------------------------
# 判定:窗口说撤得回来,履历说撤回来过没有
# ---------------------------------------------------------------------------


def _decide(record: TrackRecord | None, policy: Policy | None = None):
    return (policy or Policy()).decide(
        _unit(), Window(unbounded=True, source="fake"), NOON, record=record
    )


def test_repeated_failures_block_the_night_shot():
    record = TrackRecord(attempts=3, rolled_back=3, last_reason="验证未通过,已回滚")
    decision = _decide(record)
    assert decision.action == BLOCK
    assert "3/3" in decision.reason
    assert "验证未通过" in decision.reason


def test_two_failures_out_of_three_are_enough():
    decision = _decide(TrackRecord(attempts=3, rolled_back=2))
    assert decision.action == BLOCK


def test_one_failure_out_of_three_is_still_business_as_usual():
    decision = _decide(TrackRecord(attempts=3, rolled_back=1))
    assert decision.action == EXECUTE


def test_two_attempts_are_too_few_to_judge():
    decision = _decide(TrackRecord(attempts=2, rolled_back=2))
    assert decision.action == EXECUTE


def test_history_can_be_switched_off():
    policy = Policy(history_min_attempts=0)
    assert policy.wants_history() is False
    decision = _decide(TrackRecord(attempts=9, rolled_back=9), policy)
    assert decision.action == EXECUTE


def test_no_history_means_no_verdict_from_history():
    assert _decide(None).action == EXECUTE


# ---------------------------------------------------------------------------
# 接进推进器:同一个能力,摔过三次之后夜里不再自动做
# ---------------------------------------------------------------------------


def test_runner_blocks_after_three_rollbacks(tmp_path):
    ledger = _seed(tmp_path, VERDICT_ROLLED_BACK)
    provider = FakeProvider()
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))
    assert unit.verdict == VERDICT_BLOCKED
    assert "失败 3/3" in unit.reason
    assert provider.executed == 0


def test_runner_still_runs_when_history_is_good(tmp_path):
    ledger = _seed(tmp_path, VERDICT_KEPT)
    provider = FakeProvider()
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_runner_does_not_borrow_another_tenants_history(tmp_path):
    ledger = _seed(tmp_path, VERDICT_ROLLED_BACK, tenant="tenant-b")
    provider = FakeProvider()
    unit = asyncio.run(apply(_unit(tenant=TENANT), provider, ledger, at=NOON))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_a_human_in_the_room_can_still_go(tmp_path):
    """履历挡的是"机器自己决定";人在场时这是人的决定。"""
    ledger = _seed(tmp_path, VERDICT_ROLLED_BACK)
    provider = FakeProvider()
    unit = _unit(verdict=VERDICT_BLOCKED, reason="同类变更已经失败 3/3 次")
    result = asyncio.run(approve(unit, provider, ledger, by="值班"))
    assert result.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_rollback_writes_a_row_the_next_decision_can_read(tmp_path):
    """闭环:这一次的结论,是下一次判定的输入。"""
    ledger = _seed(tmp_path, VERDICT_ROLLED_BACK, times=2)
    provider = FakeProvider(post=Window(seconds=60, source="fake"))
    rolled = asyncio.run(apply(_unit(), provider, ledger, at=NOON))
    assert rolled.verdict == VERDICT_ROLLED_BACK

    record = asyncio.run(
        track_record(ledger, tenant=TENANT, binding=BINDING, capability=CAPABILITY)
    )
    assert record.attempts == 3
    assert record.failures == 3
