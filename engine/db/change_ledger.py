# engine/db/change_ledger.py
"""账本的业务库实现。

文件账本适合演示和离线调试,但生产上不能这么用:
DBOS 的队列按租户分区、并发度 4,四个 worker 同时往同一个文件追加,
既没有跨租户隔离,也没有并发保证。业务库把这两件事一起解决。

表的建立方式与其它模型一致(仓库里没有迁移工具):启动时 checkfirst 建一次。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from engine.change_unit.model import ChangeUnit
from engine.db.engine import async_session_factory, engine
from engine.db.models.change_event import ChangeEvent


class DbLedger:
    def __init__(self, session_factory=async_session_factory) -> None:
        self._session_factory = session_factory

    async def append(self, unit: ChangeUnit) -> None:
        async with self._session_factory() as session:
            session.add(
                ChangeEvent(
                    unit_id=unit.id,
                    tenant=unit.tenant,
                    binding=unit.binding,
                    verdict=unit.verdict,
                    idempotency_key=unit.idempotency_key,
                    created_at=unit.created_at,
                    payload=unit.to_dict(),
                )
            )
            await session.commit()

    async def find(self, idempotency_key: str, tenant: str | None = None) -> dict | None:
        if not idempotency_key:
            return None
        stmt = (
            select(ChangeEvent.payload)
            .where(ChangeEvent.idempotency_key == idempotency_key)
            .order_by(ChangeEvent.id.desc())
            .limit(1)
        )
        if tenant is not None:
            stmt = stmt.where(ChangeEvent.tenant == tenant)
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).first()
        return row[0] if row else None

    async def read(self, tenant: str | None = None) -> list[dict[str, Any]]:
        stmt = select(ChangeEvent.payload).order_by(ChangeEvent.id)
        if tenant is not None:
            stmt = stmt.where(ChangeEvent.tenant == tenant)
        async with self._session_factory() as session:
            return [row[0] for row in (await session.execute(stmt)).all()]

    async def latest(
        self, tenant: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """每个单元只出最新一行。用 max(id) 分组,不让调用方先把整张表拉下来。"""
        newest = select(func.max(ChangeEvent.id)).group_by(ChangeEvent.unit_id)
        stmt = (
            select(ChangeEvent.payload)
            .where(ChangeEvent.id.in_(newest))
            .order_by(ChangeEvent.id.desc())
        )
        if tenant is not None:
            stmt = stmt.where(ChangeEvent.tenant == tenant)
        if limit is not None:
            stmt = stmt.limit(max(0, limit))
        async with self._session_factory() as session:
            return [row[0] for row in (await session.execute(stmt)).all()]

    async def history(self, unit_id: str, tenant: str | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(ChangeEvent.payload)
            .where(ChangeEvent.unit_id == unit_id)
            .order_by(ChangeEvent.id)
        )
        if tenant is not None:
            stmt = stmt.where(ChangeEvent.tenant == tenant)
        async with self._session_factory() as session:
            return [row[0] for row in (await session.execute(stmt)).all()]


async def ensure_schema() -> None:
    """建表(已存在就跳过)。仓库里没有迁移工具,与其它模型保持同一种做法。"""
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ChangeEvent.__table__.create(c, checkfirst=True))
