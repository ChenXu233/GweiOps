# engine/change_unit/__init__.py
"""变更单元 —— 平台唯一的状态对象。"""

from .model import (
    ChangeUnit,
    Effect,
    Window,
    UNDO_RETAINED,
    UNDO_SYMMETRIC,
    VERDICT_BLOCKED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_PENDING,
    VERDICT_ROLLED_BACK,
)
from .runner import HUMAN_RESPONSE_S, apply, rollback
from .ledger import JsonlLedger

__all__ = [
    "ChangeUnit",
    "Effect",
    "Window",
    "JsonlLedger",
    "apply",
    "rollback",
    "HUMAN_RESPONSE_S",
    "UNDO_RETAINED",
    "UNDO_SYMMETRIC",
    "VERDICT_BLOCKED",
    "VERDICT_IRREVERSIBLE",
    "VERDICT_KEPT",
    "VERDICT_PENDING",
    "VERDICT_ROLLED_BACK",
]
