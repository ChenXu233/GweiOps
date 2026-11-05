# tests/test_integration/test_undo_window.py
"""撤销承诺会到期:过了窗口,平台不该再声称"可撤"。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from engine.change_unit import (
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    ChangeUnit,
    Effect,
    Window,
    undo_state,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def _row(**overrides):
    row = {
        "id": "u1",
        "verdict": VERDICT_KEPT,
        "handle": "h-1",
        "created_at": (NOW - timedelta(minutes=10)).isoformat(timespec="seconds"),
        "window": {"seconds": 3600, "unbounded": False, "source": "revision"},
    }
    row.update(overrides)
    return row


def test_inside_the_window_is_still_undoable():
    state = undo_state(_row(), NOW)
    assert state.undoable is True
    assert state.expires_at.startswith("2026-11-05T12:50")


def test_past_the_window_is_not_undoable():
    state = undo_state(_row(window={"seconds": 60, "unbounded": False, "source": "rev"}), NOW)
    assert state.undoable is False
    assert "窗口已过" in state.reason


def test_symmetric_undo_never_expires():
    state = undo_state(_row(window={"seconds": None, "unbounded": True, "source": "project"}), NOW)
    assert state.undoable is True
    assert state.expires_at == ""


def test_without_a_handle_nothing_can_be_undone():
    assert undo_state(_row(handle=None), NOW).undoable is False


def test_rolled_back_units_are_done():
    assert undo_state(_row(verdict=VERDICT_ROLLED_BACK), NOW).undoable is False


def test_a_unit_without_a_recorded_window_cannot_promise_anything():
    """读不到窗口就是不承诺可撤——宁可说不,不可说错。"""
    state = undo_state(_row(window=None), NOW)
    assert state.undoable is False
    assert "窗口" in state.reason


def test_naive_timestamps_are_treated_as_utc():
    naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None).isoformat(timespec="seconds")
    assert undo_state(_row(created_at=naive), NOW).undoable is True


# ---------------------------------------------------------------------------
# 推进器真的会拦
# ---------------------------------------------------------------------------


class _Provider:
    binding = "local"
    tenant = ""

    def __init__(self):
        self.undone = 0

    async def undo(self, task, args, handle):
        self.undone += 1
        return {}


def _unit(window: Window | None, created_at: str) -> ChangeUnit:
    return ChangeUnit(
        intent={},
        effect=Effect(task="scale", args={}, undo_task="undo_scale"),
        binding="local",
        handle="h-1",
        window=window,
        verdict=VERDICT_KEPT,
        created_at=created_at,
    )


def test_rollback_refuses_an_expired_window():
    from engine.change_unit import rollback

    provider = _Provider()
    # 这里走的是推进器自己的时钟,不能用固定的 NOW
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    unit = _unit(Window(seconds=60, source="revision"), two_hours_ago.isoformat())
    with pytest.raises(ValueError, match="不能撤"):
        asyncio.run(rollback(unit, provider))
    assert provider.undone == 0


def test_rollback_still_works_inside_the_window():
    from engine.change_unit import rollback

    provider = _Provider()
    unit = _unit(
        Window(unbounded=True, source="project"), datetime.now(timezone.utc).isoformat()
    )
    asyncio.run(rollback(unit, provider))
    assert provider.undone == 1
