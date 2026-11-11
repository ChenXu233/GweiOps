# engine/change_unit/__init__.py
"""变更单元 —— 平台唯一的状态对象。"""

from .errors import EffectNotApplied
from .model import (
    ChangeUnit,
    Effect,
    Window,
    UNDO_RETAINED,
    UNDO_SYMMETRIC,
    VERDICT_BLOCKED,
    VERDICT_FAILED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_PENDING,
    VERDICT_ROLLED_BACK,
    VERDICT_UNKNOWN,
    VERDICT_VETOED,
)
from .policy import (
    BLOCK,
    DEFAULT_HUMAN_RESPONSE_S,
    EXECUTE,
    AwayWindow,
    Decision,
    Policy,
    window_label,
)
from .record import DEFAULT_LOOKBACK, TrackRecord, summarize, track_record
from .runner import HUMAN_RESPONSE_S, apply, approve, rollback, veto
from .undo import UndoState, undo_state
from .ledger import JsonlLedger, Ledger, create_ledger

__all__ = [
    "ChangeUnit",
    "Effect",
    "Window",
    "JsonlLedger",
    "Ledger",
    "create_ledger",
    "Policy",
    "AwayWindow",
    "Decision",
    "window_label",
    "apply",
    "approve",
    "UndoState",
    "undo_state",
    "veto",
    "rollback",
    "TrackRecord",
    "summarize",
    "track_record",
    "DEFAULT_LOOKBACK",
    "HUMAN_RESPONSE_S",
    "DEFAULT_HUMAN_RESPONSE_S",
    "EXECUTE",
    "BLOCK",
    "UNDO_RETAINED",
    "UNDO_SYMMETRIC",
    "VERDICT_BLOCKED",
    "VERDICT_FAILED",
    "VERDICT_IRREVERSIBLE",
    "VERDICT_KEPT",
    "VERDICT_PENDING",
    "VERDICT_ROLLED_BACK",
    "VERDICT_UNKNOWN",
    "VERDICT_VETOED",
    "EffectNotApplied",
]