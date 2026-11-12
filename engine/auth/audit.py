# engine/auth/audit.py
"""审计:谁在什么时候对什么做了什么。

只记"改世界"的动作和登入登出。读操作不记——记全量读会把库撑爆,而且
真正的价值是"谁动了什么",不是"谁看了什么"。

写失败不抛:审计是旁路,不能因为记不下日志就把人的操作弄挂;记不下要喊一声。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from engine.auth import Identity
from engine.db import async_session_factory
from engine.db.models import AuditLog, Tenant

logger = logging.getLogger(__name__)


async def record(
    action: str,
    *,
    identity: Identity | None = None,
    target: str = "",
    detail: dict | None = None,
    ip: str = "",
) -> None:
    """记一条。action 形如 user.create / role.update / auth.login。"""
    tenant_id: uuid.UUID | None = None
    try:
        async with async_session_factory() as session:
            if identity is not None and identity.tenant:
                tenant_id = await session.scalar(
                    select(Tenant.id).where(Tenant.slug == identity.tenant)
                )
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_id=uuid.UUID(identity.user_id) if identity and identity.user_id else None,
                    actor_name=(identity.name if identity else "")[:255],
                    action=action[:64],
                    target=target[:255],
                    detail=detail,
                    ip=ip[:64],
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - 旁路,不能带崩主流程
        logger.warning("审计写入失败: %s %s", action, target, exc_info=True)


async def latest(*, tenant: str = "", limit: int = 100) -> list[dict]:
    """最近若干条。tenant 为空表示不限(运维视角)。"""
    async with async_session_factory() as session:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
        if tenant:
            tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == tenant))
            if tenant_id is None:
                return []
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        rows = list((await session.execute(stmt)).scalars().all())
        return [
            {
                "id": row.id,
                "actor_name": row.actor_name,
                "actor_id": str(row.actor_id) if row.actor_id else "",
                "action": row.action,
                "target": row.target,
                "detail": row.detail or {},
                "ip": row.ip,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]
