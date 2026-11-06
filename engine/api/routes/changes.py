# engine/api/routes/changes.py
"""变更账本 API —— 夜里发生了什么、还能不能撤、阻断的那条要不要放。

账本是追加日志:同一个单元的判定、执行、放行、撤销各写一行,
当前状态看最后一行,历史行永不改写。所以"谁让它跑的"与"它跑成了什么"一样可审计。

tenant 是查询范围。配置了控制台令牌时它由令牌决定(见 engine/api/auth.py),
未配置时才是调用方自报——那种部署只适合单机自用。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from engine.api.auth import by_of, tenant_scope
from engine.api.schemas import ChangeDetailDTO, ChangeListDTO
from engine.change_unit import (
    ChangeUnit,
    approve,
    create_ledger,
    rollback,
    undo_state,
    veto,
)
from engine.plugin_manager import registry

router = APIRouter()
logger = logging.getLogger(__name__)

BLOCKED = "blocked"
ROLLED_BACK = "rolled_back"
NOT_APPLIED = ("blocked", "vetoed", "pending")


def _ledger():
    return create_ledger()


def _with_undo(row: dict) -> dict:
    """给一行账补上"此刻还撤不撤得回来"。

    撤销承诺会到期,所以这件事只能在读的时候算,不能落库:写下的那一刻可信,
    第二天早上未必。历史行按它自己那一刻算——它就是那一刻的当前状态。
    """
    state = undo_state(row)
    return {
        **row,
        "undoable": state.undoable,
        "undo_reason": state.reason,
        "undo_expires_at": state.expires_at,
    }


def _rows_with_undo(rows: list[dict]) -> list[dict]:
    return [_with_undo(row) for row in rows]


async def _latest_or_404(unit_id: str, tenant: str | None = None) -> tuple[object, dict]:
    ledger = _ledger()
    rows = await ledger.history(unit_id, tenant=tenant)
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
    request: Request,
    verdict: str | None = None,
    binding: str | None = None,
    incident: str | None = None,
    tenant: str | None = None,
    limit: int = 100,
) -> ChangeListDTO:
    """当前状态一栏:每个单元只出现一次,最新的在前。

    过滤在截断之前:先按 verdict / binding 收窄,再取前 limit 条,
    total 报的是过滤后的总数。没加过滤时把 limit 下推给账本,省得全表取回。
    """
    tenant = tenant_scope(request, tenant)
    filtering = bool(verdict or binding or incident)
    rows = await _ledger().latest(
        tenant=tenant, limit=None if filtering else max(0, limit)
    )
    if verdict:
        rows = [row for row in rows if row.get("verdict") == verdict]
    if binding:
        rows = [row for row in rows if row.get("binding") == binding]
    if incident:
        rows = [row for row in rows if row.get("incident_id") == incident]
    return ChangeListDTO(items=_rows_with_undo(rows[: max(0, limit)]), total=len(rows))


@router.get("/api/changes/{unit_id}")
async def get_change(
    unit_id: str, request: Request, tenant: str | None = None
) -> ChangeDetailDTO:
    tenant = tenant_scope(request, tenant)
    rows = await _ledger().history(unit_id, tenant=tenant)
    if not rows:
        raise HTTPException(status_code=404, detail="unknown change")
    return ChangeDetailDTO(
        latest=_with_undo(rows[-1]), history=_rows_with_undo(rows)
    )


@router.post("/api/changes/{unit_id}/approve")
async def approve_change(
    unit_id: str,
    request: Request,
    by: str = "人工",
    reason: str = "人工放行",
    tenant: str | None = None,
) -> ChangeDetailDTO:
    """放行一个阻断的单元。

    放行只说明"此刻有人在场",不放宽判定口径:执行后照样读窗口、照样验证,
    验证不过照样回滚。真正不可逆的那类,执行后会被如实记成 irreversible。

    by 以控制台令牌为准;没有配置令牌时才采信调用方写的那一个。
    """
    tenant = tenant_scope(request, tenant)
    by = by_of(request, by)
    ledger, latest = await _latest_or_404(unit_id, tenant)
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

    return ChangeDetailDTO(
        latest=_with_undo(unit.to_dict()),
        history=_rows_with_undo(await ledger.history(unit_id, tenant=tenant)),
    )


@router.post("/api/changes/{unit_id}/veto")
async def veto_change(
    unit_id: str,
    request: Request,
    by: str = "人工",
    reason: str = "人工否决",
    tenant: str | None = None,
) -> ChangeDetailDTO:
    """不做这次变更。否决也写一行账——它和放行一样是一次决定。"""
    tenant = tenant_scope(request, tenant)
    by = by_of(request, by)
    ledger, latest = await _latest_or_404(unit_id, tenant)
    if latest.get("verdict") not in (BLOCKED, "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"该单元已经执行过({latest.get('verdict')}),只能撤销,不能否决",
        )

    unit = ChangeUnit.from_dict(latest)
    try:
        await veto(unit, ledger, by=by, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return ChangeDetailDTO(
        latest=_with_undo(unit.to_dict()),
        history=_rows_with_undo(await ledger.history(unit_id, tenant=tenant)),
    )


@router.post("/api/changes/{unit_id}/rollback")
async def rollback_change(
    unit_id: str,
    request: Request,
    reason: str = "人工回滚",
    tenant: str | None = None,
) -> ChangeDetailDTO:
    """撤销一个单元。已经撤过的、没执行过的、没有句柄的都拒绝。"""
    tenant = tenant_scope(request, tenant)
    ledger, latest = await _latest_or_404(unit_id, tenant)

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
        await rollback(unit, provider, ledger, reason=reason, by=by_of(request, ""))
    except Exception as e:
        logger.error("rollback %s failed: %s", unit_id, e)
        raise HTTPException(status_code=502, detail=f"撤销失败: {e}") from e

    return ChangeDetailDTO(
        latest=_with_undo(unit.to_dict()),
        history=_rows_with_undo(await ledger.history(unit_id, tenant=tenant)),
    )