# engine/quota/store.py
"""用量的落账与判定。

判定的口径只有一条:**窗口内用掉多少**。不做预留、不做缓存计数——
计数器迟早会和事实对不上,而配额是最不该"差一点"的地方。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from engine.db import async_session_factory
from engine.db.models import QuotaUsage, Tenant, User
from engine.quota import Limit, limits_for


class QuotaExceeded(RuntimeError):
    """超了。message 里带资源、窗口、已用与上限 —— 别让人去猜是哪一条。"""

    def __init__(self, limit: Limit, used: int) -> None:
        self.limit = limit
        self.used = used
        super().__init__(
            f"{limit.resource} 已用 {used},上限 {limit.amount}/{limit.window_hours}h"
        )


@dataclass(frozen=True)
class Usage:
    resource: str
    used: int
    limit: int
    window_hours: int

    @property
    def unlimited(self) -> bool:
        return self.window_hours == 0

    @property
    def remaining(self) -> int | None:
        return None if self.unlimited else max(0, self.limit - self.used)

    def to_dto(self) -> dict:
        return {
            "resource": self.resource,
            "used": self.used,
            "limit": self.limit,
            "window_hours": self.window_hours,
            "remaining": self.remaining,
        }


async def _subject_id(subject_kind: str, subject: str) -> uuid.UUID | None:
    if not subject:
        return None
    async with async_session_factory() as session:
        if subject_kind == "tenant":
            return await session.scalar(select(Tenant.id).where(Tenant.slug == subject))
        try:
            return uuid.UUID(subject)
        except (ValueError, AttributeError):
            return None


async def record_usage(
    subject_kind: str, subject_id: uuid.UUID, resource: str, amount: int = 1
) -> None:
    """落一笔用量。amount=0 也落:它表示"这件事发生过",判定时求和照样算。"""
    if amount < 0:
        raise ValueError("用量不能是负数")
    async with async_session_factory() as session:
        session.add(
            QuotaUsage(
                subject_kind=subject_kind,
                subject_id=subject_id,
                resource=resource,
                amount=amount,
            )
        )
        await session.commit()


async def used_since(
    subject_kind: str, subject_id: uuid.UUID, resource: str, since: datetime | None
) -> int:
    async with async_session_factory() as session:
        stmt = select(func.coalesce(func.sum(QuotaUsage.amount), 0)).where(
            QuotaUsage.subject_kind == subject_kind,
            QuotaUsage.subject_id == subject_id,
            QuotaUsage.resource == resource,
        )
        if since is not None:
            stmt = stmt.where(QuotaUsage.used_at >= since)
        return int(await session.scalar(stmt) or 0)


async def usage_for(
    subject_kind: str, subject: str, tenant: str = "", resource: str | None = None
) -> list[Usage]:
    """一个主体现在的用量。resource 给了就只算那一个。"""
    subject_id = await _subject_id(subject_kind, subject)
    limits = limits_for(tenant or subject)
    names = [resource] if resource else list(limits)
    out: list[Usage] = []
    for name in names:
        limit = limits.get(name) or Limit(resource=name, amount=0, window_hours=0)
        if subject_id is None:
            out.append(Usage(name, 0, limit.amount, limit.window_hours))
            continue
        used = await used_since(subject_kind, subject_id, name, limit.window())
        out.append(Usage(name, used, limit.amount, limit.window_hours))
    return out


async def check(
    subject_kind: str, subject: str, resource: str, tenant: str = "", amount: int = 1
) -> Usage:
    """准入判定。超了抛 QuotaExceeded —— 调用方决定是 429 还是别的什么。"""
    found = (await usage_for(subject_kind, subject, tenant, resource))[0]
    # window_hours=0 才是"没声明 = 不限"。limit=0 是"声明了但不给用",是两件事。
    if found.unlimited:
        return found
    if found.used + max(0, amount) > found.limit:
        raise QuotaExceeded(Limit(resource, found.limit, found.window_hours), found.used)
    return found


async def record_for_user(user_id: uuid.UUID, resource: str, amount: int = 1) -> None:
    await record_usage("user", user_id, resource, amount)


async def record_for_tenant(slug: str, resource: str, amount: int = 1) -> None:
    tenant_id = await _subject_id("tenant", slug)
    if tenant_id is None:
        return
    await record_usage("tenant", tenant_id, resource, amount)


__all__ = [
    "QuotaExceeded",
    "Usage",
    "check",
    "record_for_tenant",
    "record_for_user",
    "record_usage",
    "usage_for",
    "used_since",
]
