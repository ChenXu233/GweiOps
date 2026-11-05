# engine/change_unit/undo.py
"""撤销承诺的到期时间。

窗口是执行后读到的"还能撤多久"。它一旦过去,平台就不该再声称"可撤"——
下游保留的旧状态已经不在保证范围内。这个模块只回答一个问题:
此刻,这次改变还撤得回来吗。

判定只看三件事:有没有句柄、窗口还剩多久、以及从执行到现在过了多久。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class UndoState:
    undoable: bool
    reason: str
    expires_at: str = ""  # 空字符串 = 不会过期(对称撤销)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def undo_state(row: dict[str, Any], now: datetime | None = None) -> UndoState:
    """row 是账本里的一行(或 unit.to_dict())。"""
    if not row.get("handle"):
        return UndoState(False, "没有句柄")
    if row.get("verdict") == "rolled_back":
        return UndoState(False, "已经撤销过了")

    window = row.get("window")
    if not isinstance(window, dict):
        return UndoState(False, "没有记录窗口")
    if window.get("unbounded"):
        return UndoState(True, "对称撤销:目标还在就能撤")

    seconds = window.get("seconds")
    if not isinstance(seconds, int):
        return UndoState(False, "窗口不是一个时长")

    created = _parse(row.get("created_at"))
    if created is None:
        return UndoState(False, "没有记录执行时间")

    expires = created + timedelta(seconds=seconds)
    if (now or datetime.now(timezone.utc)) >= expires:
        return UndoState(False, f"窗口已过({expires:%Y-%m-%d %H:%M} UTC)")
    return UndoState(True, "仍在窗口内", expires.isoformat(timespec="seconds"))
