# engine/api/routes/changes.py
"""变更账本 API —— 夜里发生了什么、还能不能撤、阻断的那条要不要放。

账本是追加日志:同一个单元的判定、执行、放行、撤销各写一行,
当前状态看最后一行,历史行永不改写。所以"谁让它跑的"与"它跑成了什么"一样可审计。

tenant 是查询范围,不是鉴权:调用方声明自己要看谁。认证接进来之前,
它只是让多租户能各看各的,不构成越权保护。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from engine.api.schemas import ChangeDetailDTO, ChangeListDTO
from engine.change_unit import ChangeUnit, approve, create_ledger, rollback, veto
from engine.plugin_manager import registry

router = APIRouter()
logger = logging.getLogger(__name__)

BLOCKED = "blocked"
ROLLED_BACK = "rolled_back"
NOT_APPLIED = ("blocked", "vetoed", "pending")


def _ledger():
    return create_ledger()


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
    verdict: str | None = None,
    binding: str | None = None,
    tenant: str | None = None,
    limit: int = 100,
) -> ChangeListDTO:
    """当前状态一栏:每个单元只出现一次,最新的在前。

    过滤在截断之前:先按 verdict / binding 收窄,再取前 limit 条,
    total 报的是过滤后的总数。没加过滤时把 limit 下推给账本,省得全表取回。
    """
    filtering = bool(verdict or binding)
    rows = await _ledger().latest(
        tenant=tenant, limit=None if filtering else max(0, limit)
    )
    if verdict:
        rows = [row for row in rows if row.get("verdict") == verdict]
    if binding:
        rows = [row for row in rows if row.get("binding") == binding]
    return ChangeListDTO(items=rows[: max(0, limit)], total=len(rows))


@router.get("/api/changes/{unit_id}")
async def get_change(unit_id: str, tenant: str | None = None) -> ChangeDetailDTO:
    rows = await _ledger().history(unit_id, tenant=tenant)
    if not rows:
        raise HTTPException(status_code=404, detail="unknown change")
    return ChangeDetailDTO(latest=rows[-1], history=rows)


@router.post("/api/changes/{unit_id}/approve")
async def approve_change(
    unit_id: str,
    by: str = "人工",
    reason: str = "人工放行",
    tenant: str | None = None,
) -> ChangeDetailDTO:
    """放行一个阻断的单元。

    放行只说明"此刻有人在场",不放宽判定口径:执行后照样读窗口、照样验证,
    验证不过照样回滚。真正不可逆的那类,执行后会被如实记成 irreversible。

    by 现在由调用方自报。认证接进来之前,它是一条备注,不是责任归属。
    """
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
        latest=unit.to_dict(),
        history=await ledger.history(unit_id, tenant=tenant),
    )


@router.post("/api/changes/{unit_id}/veto")
async def veto_change(
    unit_id: str,
    by: str = "人工",
    reason: str = "人工否决",
    tenant: str | None = None,
) -> ChangeDetailDTO:
    """不做这次变更。否决也写一行账——它和放行一样是一次决定。"""
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
        latest=unit.to_dict(),
        history=await ledger.history(unit_id, tenant=tenant),
    )


@router.post("/api/changes/{unit_id}/rollback")
async def rollback_change(
    unit_id: str,
    reason: str = "人工回滚",
    tenant: str | None = None,
) -> ChangeDetailDTO:
    """撤销一个单元。已经撤过的、没执行过的、没有句柄的都拒绝。"""
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
        await rollback(unit, provider, ledger, reason=reason)
    except Exception as e:
        logger.error("rollback %s failed: %s", unit_id, e)
        raise HTTPException(status_code=502, detail=f"撤销失败: {e}") from e

    return ChangeDetailDTO(
        latest=unit.to_dict(),
        history=await ledger.history(unit_id, tenant=tenant),
    )