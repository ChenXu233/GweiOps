# engine/api/routes/changes.py
"""变更账本 API —— 夜里发生了什么、还能不能撤。

账本是追加日志:同一个单元的执行与撤销各写一行,当前状态看最后一行,
历史行永不改写。撤销本身也写一行,所以"谁在什么时候撤的"与执行一样可审计。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from engine.change_unit import ChangeUnit, JsonlLedger, rollback
from engine.plugin_manager import registry
from engine.shared.config import config

router = APIRouter()
logger = logging.getLogger(__name__)

ROLLED_BACK = "rolled_back"
NOT_APPLIED = ("blocked", "vetoed", "pending")


def _ledger() -> JsonlLedger:
    return JsonlLedger(config.settings.change_ledger_path)


@router.get("/api/changes")
async def list_changes(
    verdict: str | None = None,
    binding: str | None = None,
    limit: int = 100,
) -> dict:
    """当前状态一栏:每个单元只出现一次,最新的在前。"""
    rows = _ledger().latest()
    if verdict:
        rows = [row for row in rows if row.get("verdict") == verdict]
    if binding:
        rows = [row for row in rows if row.get("binding") == binding]
    return {"items": rows[: max(0, limit)], "total": len(rows)}


@router.get("/api/changes/{unit_id}")
async def get_change(unit_id: str) -> dict:
    rows = _ledger().history(unit_id)
    if not rows:
        raise HTTPException(status_code=404, detail="unknown change")
    return {"latest": rows[-1], "history": rows}


@router.post("/api/changes/{unit_id}/rollback")
async def rollback_change(unit_id: str, reason: str = "人工回滚") -> dict:
    """撤销一个单元。已经撤过的、没执行过的、没有句柄的都拒绝。"""
    ledger = _ledger()
    rows = ledger.history(unit_id)
    if not rows:
        raise HTTPException(status_code=404, detail="unknown change")

    latest = rows[-1]
    verdict = latest.get("verdict")
    if verdict == ROLLED_BACK:
        raise HTTPException(status_code=409, detail="已经撤销过了")
    if verdict in NOT_APPLIED:
        raise HTTPException(status_code=400, detail=f"该单元未执行({verdict}),无需撤销")
    if not latest.get("handle"):
        raise HTTPException(status_code=409, detail="没有句柄,无法撤销")

    unit = ChangeUnit.from_dict(latest)
    try:
        provider, _decl = registry.effect_decl(
            unit.effect.capability, tenant=unit.tenant, binding=unit.binding
        )
    except LookupError as e:
        logger.warning("rollback %s: provider unavailable: %s", unit_id, e)
        raise HTTPException(status_code=503, detail=f"提供者不可用: {e}") from e

    try:
        await rollback(unit, provider, ledger, reason=reason)
    except Exception as e:
        logger.error("rollback %s failed: %s", unit_id, e)
        raise HTTPException(status_code=502, detail=f"撤销失败: {e}") from e

    return {"latest": unit.to_dict(), "history": ledger.history(unit_id)}
