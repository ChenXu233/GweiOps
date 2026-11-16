# engine/api/routes/quota.py
"""配额:限量怎么声明的、现在用掉多少。

读的是一个租户的用量,不是某个人的。人的用量在 `usage_for("user", ...)` 里,
接口暂时不开 —— 现在没有哪个入口按人限额,开了只会是一串 0。

限量的写入走配置 scope(`/api/settings/scopes/quota`),这里只管算给你看。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from engine.api.auth import require, workspace_access
from engine.quota import QuotaError, limits_for, parse_limit
from engine.quota import store as quota_store

router = APIRouter()


class QuotaItemDTO(BaseModel):
    resource: str
    used: int
    limit: int
    window_hours: int
    remaining: int | None


class QuotaDTO(BaseModel):
    tenant: str
    items: list[QuotaItemDTO]


@router.get("/api/quota")
async def get_quota(request: Request, tenant: str | None = None) -> QuotaDTO:
    """这个租户每条限量的用量。没声明的资源不出现在里面。"""
    require(request, "settings.read")
    slug = workspace_access(request) or ""
    try:
        limits = limits_for(slug)
    except QuotaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    usages = []
    for name in limits:
        found = await quota_store.usage_for("tenant", slug, slug, name)
        usages.extend(item.to_dto() for item in found)
    return QuotaDTO(tenant=slug, items=[QuotaItemDTO(**item) for item in usages])


@router.get("/api/quota/parse")
async def parse(resource: str, spec: str) -> dict:
    """把 `2000/30d` 拆开看看 —— 页面在保存前先问一次,别让人猜格式。"""
    try:
        limit = parse_limit(resource, spec)
    except QuotaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"resource": limit.resource, "amount": limit.amount, "window_hours": limit.window_hours}
