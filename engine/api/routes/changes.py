# engine/api/routes/changes.py
"""变更账本 API —— 夜里发生了什么、还能不能撤、阻断的那条要不要放。

账本是追加日志:同一个单元的判定、执行、放行、撤销各写一行,
当前状态看最后一行,历史行永不改写。所以"谁让它跑的"与"它跑成了什么"一样可审计。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from engine.change_unit import ChangeUnit, JsonlLedger, approve, rollback, veto
from engine.plugin_manager import registry
from engine.shared.config import config

router = APIRouter()
logger = logging.getLogger(__name__)

BLOCKED = "blocked"
ROLLED_BACK = "rolled_back"
NOT_APPLIED = ("blocked", "vetoed", "pending")


def _ledger() -> JsonlLedger:
    return JsonlLedger(config.settings.change_ledger_path)


def _latest_or_404(unit_id: str) -> tuple[JsonlLedger, dict]:
    ledger = _ledger()
    rows = ledger.history(unit_id)
    if not rows:
        raise HTTPException(status_code=404, detail="unknown change")
    return ledger, rows[-1]


def _provider_for(unit: ChangeUnit):
    try:
        provider, _decl = registry.effect_decl(
            unit.effect.capability, tenant=unit.tenant, binding=unit.binding
        )
    except LookupError as e:
        logger.warning("change %s: provider unavailable: %s", unit.id, e)
        raise HTTPException(status_code=503, detail=f"提供者不可用: {e}") from e
    return provider


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


@router.post("/api/changes/{unit_id}/approve")
async def approve_change(unit_id: str, by: str = "人工", reason: str = "人工放行") -> dict:
    """放行一个阻断的单元。

    放行只说明"此刻有人在场",不放宽判定口径:执行后照样读窗口、照样验证,
    验证不过照样回滚。真正不可逆的那类,执行后会被如实记成 irreversible。

    by 现在由调用方自报。认证接进来之前,它是一条备注,不是责任归属。
    """
    ledger, latest = _latest_or_404(unit_id)
    if latest.get("verdict") != BLOCKED:
        raise HTTPException(
            status_code=409,
            detail=f"只有阻断的单元需要放行(当前 {latest.get('verdict')})",
        )

    unit = ChangeUnit.from_dict(latest)
    provider = _provider_for(unit)
    try:
        await approve(unit, provider, ledger, by=by, reason=reason)
    except Exception as e:
        logger.error("approve %s failed: %s", unit_id, e)
        raise HTTPException(status_code=502, detail=f"放行后执行失败: {e}") from e

    return {"latest": unit.to_dict(), "history": ledger.history(unit_id)}


@router.post("/api/changes/{unit_id}/veto")
async def veto_change(unit_id: str, by: str = "人工", reason: str = "人工否决") -> dict:
    """不做这次变更。否决也写一行账——它和放行一样是一次决定。"""
    ledger, latest = _latest_or_404(unit_id)
    if latest.get("verdict") not in (BLOCKED, "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"该单元已经执行过({latest.get('verdict')}),只能撤销,不能否决",
        )

    unit = ChangeUnit.from_dict(latest)
    try:
        veto(unit, ledger, by=by, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {"latest": unit.to_dict(), "history": ledger.history(unit_id)}


@router.post("/api/changes/{unit_id}/rollback")
async def rollback_change(unit_id: str, reason: str = "人工回滚") -> dict:
    """撤销一个单元。已经撤过的、没执行过的、没有句柄的都拒绝。"""
    ledger, latest = _latest_or_404(unit_id)

    verdict = latest.get("verdict")
    if verdict == ROLLED_BACK:
        raise HTTPException(status_code=409, detail="已经撤销过了")
    if verdict in NOT_APPLIED:
        raise HTTPException(status_code=400, detail=f"该单元未执行({verdict}),无需撤销")
    if not latest.get("handle"):
        raise HTTPException(status_code=409, detail="没有句柄,无法撤销")

    unit = ChangeUnit.from_dict(latest)
    provider = _provider_for(unit)
    try:
        await rollback(unit, provider, ledger, reason=reason)
    except Exception as e:
        logger.error("rollback %s failed: %s", unit_id, e)
        raise HTTPException(status_code=502, detail=f"撤销失败: {e}") from e

    return {"latest": unit.to_dict(), "history": ledger.history(unit_id)}
