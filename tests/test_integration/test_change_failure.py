# tests/test_integration/test_change_failure.py
"""下游报错时的结论 —— 每一个出口都必须留下两样东西:一行账,和一句实话。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from engine.change_unit import (
    ChangeUnit,
    Effect,
    EffectNotApplied,
    JsonlLedger,
    VERDICT_BLOCKED,
    VERDICT_FAILED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    VERDICT_UNKNOWN,
    Window,
    apply,
    rollback,
)

BINDING = "local"
NOON = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class FailingProvider:
    """按阶段抛错的提供者。抛不抛由用例决定,不抛时行为与正常提供者一致。"""

    binding = BINDING
    tenant = ""

    def __init__(
        self,
        *,
        window_pre: bool = False,
        execute: bool = False,
        window_post: bool = False,
        verify: bool = False,
        undo: bool = False,
        verify_ok: bool = True,
        result=None,
        not_applied: bool = False,
    ) -> None:
        self.raise_window_pre = window_pre
        self.raise_execute = execute
        self.not_applied = not_applied
        self.raise_window_post = window_post
        self.raise_verify = verify
        self.raise_undo = undo
        self.verify_ok = verify_ok
        self.result = result
        self.executed = 0
        self.undone = 0

    async def window(self, effect, handle):
        if handle is None and self.raise_window_pre:
            raise RuntimeError("连不上下游")
        if handle is not None and self.raise_window_post:
            raise RuntimeError("读不出执行后的状态")
        return Window(unbounded=True, source="fake")

    async def execute(self, task, args):
        self.executed += 1
        if self.not_applied:
            try:
                raise KeyError("repo")
            except KeyError as cause:
                raise EffectNotApplied("RequestFailed: 404 Not Found") from cause
        if self.raise_execute:
            raise RuntimeError("daemon 没响应")
        if self.result is not None:
            return self.result
        return {"handle": "h-1"}

    async def undo(self, task, args, handle):
        self.undone += 1
        if self.raise_undo:
            raise RuntimeError("缩不回去")
        return {}

    async def verify(self, effect, handle):
        if self.raise_verify:
            raise RuntimeError("查不到副本数")
        return self.verify_ok, {"running": 2}


def _unit(idempotency_key: str = "") -> ChangeUnit:
    return ChangeUnit(
        intent={"summary": "把 web 扩到 2 副本"},
        effect=Effect(task="scale", args={"service": "web"}, undo_task="undo_scale"),
        binding=BINDING,
        idempotency_key=idempotency_key,
    )


def _latest(ledger: JsonlLedger) -> list[dict]:
    return asyncio.run(ledger.latest())


# ---------------------------------------------------------------------------
# 读不到窗口:不判,不执行
# ---------------------------------------------------------------------------


def test_pre_window_error_blocks_without_touching_the_world(tmp_path):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    provider = FailingProvider(window_pre=True)
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))

    assert unit.verdict == VERDICT_BLOCKED
    assert "下游报错" in unit.reason
    assert provider.executed == 0
    assert _latest(ledger)[0]["verdict"] == VERDICT_BLOCKED


# ---------------------------------------------------------------------------
# 执行报错:分成「确定没动」与「不知道动没动」两种,不能混成一句不可逆
# ---------------------------------------------------------------------------


def test_execute_error_is_unknown_and_leaves_a_row(tmp_path):
    """说不清的报错一律 unknown:请求可能已经到了对面,得人去核。"""
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    provider = FailingProvider(execute=True)
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))

    assert unit.verdict == VERDICT_UNKNOWN
    assert "不知道动没动" in unit.reason
    assert unit.facts["error"]["stage"] == "execute"
    assert len(_latest(ledger)) == 1


def test_execute_error_is_not_retried_into_a_second_effect(tmp_path):
    """DBOS 只保证至少一次。账本里有了这一行,重跑就不能再把效果做一遍。"""
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    provider = FailingProvider(execute=True)
    asyncio.run(apply(_unit(idempotency_key="dup-1"), provider, ledger, at=NOON))
    again = asyncio.run(apply(_unit(idempotency_key="dup-1"), provider, ledger, at=NOON))

    assert provider.executed == 1
    assert again.verdict == VERDICT_UNKNOWN
    assert again.reason.startswith("重放")


def test_provider_saying_not_applied_is_failed(tmp_path):
    """提供者认得出没碰到下游:记 failed,可重试,不占待审清单。"""
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    provider = FailingProvider(not_applied=True)
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))

    assert unit.verdict == VERDICT_FAILED
    assert "确定没动" in unit.reason
    # 原始错因还在:换掉的只是结论,不是证据
    assert unit.facts["error"]["type"] == "KeyError"
    assert unit.facts["error"]["stage"] == "execute"
    assert _latest(ledger)[0]["verdict"] == VERDICT_FAILED


def test_non_object_result_cannot_yield_a_handle(tmp_path):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    unit = asyncio.run(
        apply(_unit(), FailingProvider(result="ok"), ledger, at=NOON)
    )
    assert unit.verdict == VERDICT_IRREVERSIBLE
    assert "不是对象" in unit.reason


def test_post_window_error_keeps_the_handle_on_record(tmp_path):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    unit = asyncio.run(
        apply(_unit(), FailingProvider(window_post=True), ledger, at=NOON)
    )
    assert unit.verdict == VERDICT_IRREVERSIBLE
    assert unit.handle == "h-1"
    assert "读窗口报错" in unit.reason


# ---------------------------------------------------------------------------
# 验不了就回滚;撤不回就说撤不回
# ---------------------------------------------------------------------------


def test_verify_error_rolls_back_instead_of_claiming_success(tmp_path):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    provider = FailingProvider(verify=True)
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))

    assert unit.verdict == VERDICT_ROLLED_BACK
    assert provider.undone == 1
    assert "验证时下游报错" in unit.reason


def test_undo_error_is_reported_not_swallowed(tmp_path):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    provider = FailingProvider(undo=True, verify_ok=False)
    unit = asyncio.run(apply(_unit(), provider, ledger, at=NOON))

    assert unit.verdict == VERDICT_IRREVERSIBLE
    assert "撤销也失败" in unit.reason
    assert unit.facts["error"]["stage"] == "undo"
    assert _latest(ledger)[0]["verdict"] == VERDICT_IRREVERSIBLE


def test_manual_rollback_failure_does_not_pretend_to_have_rolled_back(tmp_path):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    kept = asyncio.run(apply(_unit(), FailingProvider(), ledger, at=NOON))
    assert kept.verdict == VERDICT_KEPT

    broken = FailingProvider(undo=True)
    result = asyncio.run(rollback(kept, broken, ledger))
    assert result.verdict == VERDICT_IRREVERSIBLE
    assert broken.undone == 1


# ---------------------------------------------------------------------------
# 不变量:任何出口都有一行账
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fault",
    [
        {"window_pre": True},
        {"execute": True},
        {"window_post": True},
        {"verify": True},
        {"undo": True, "verify_ok": False},
        {},
    ],
)
def test_every_exit_writes_exactly_one_row(tmp_path, fault):
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    asyncio.run(apply(_unit(), FailingProvider(**fault), ledger, at=NOON))
    assert len(_latest(ledger)) == 1
