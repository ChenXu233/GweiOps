# engine/api/routes/incidents.py
"""事故报告 API —— 这一场到底怎么了。

它与账本是两件事:账本说哪几处被改了,事故说整场的结论。一次事故的变更
用 `GET /api/changes?incident=` 捞;整场的经过与结论从这里看。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from engine.api.auth import tenant_scope
from engine.api.schemas import IncidentDTO, IncidentListDTO
from engine.incidents import create_incident_store

router = APIRouter()


@router.get("/api/incidents")
async def list_incidents(
    request: Request, tenant: str | None = None, limit: int = 50
) -> IncidentListDTO:
    """最近的在前。status 停在 open 的那几行,就是开了没收口的事故。"""
    tenant = tenant_scope(request, tenant)
    rows = await create_incident_store().list(tenant=tenant, limit=limit)
    return IncidentListDTO(items=rows, total=len(rows))


@router.get("/api/incidents/{incident_id}")
async def get_incident(
    incident_id: str, request: Request, tenant: str | None = None
) -> IncidentDTO:
    tenant = tenant_scope(request, tenant)
    row = await create_incident_store().get(incident_id, tenant=tenant)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown incident")
    return IncidentDTO(**row)
