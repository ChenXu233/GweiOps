# tests/test_integration/test_change_ledger_db.py
"""业务库账本:并发追加、按租户折叠、同键取最新。需要 GWEI_TEST_DATABASE_URL。

文件账本在这张单子上有两条硬伤:并发追加会互相踩,以及没法按租户取。
这两个用例就是盯着它们写的。

每个用例只开一个事件循环(async 引擎的池绑定在创建它的循环上)。
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable

import pytest
from sqlalchemy import delete

from engine.change_unit import (
    VERDICT_BLOCKED,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    ChangeUnit,
    Effect,
)
from engine.db.change_ledger import DbLedger, ensure_schema
from engine.db.engine import async_session_factory
from engine.db.models.change_event import ChangeEvent

pytestmark = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


def _unit(
    unit_id: str = "u1",
    tenant: str = "t1",
    verdict: str = VERDICT_KEPT,
    handle: str | None = "h-1",
    key: str = "",
) -> ChangeUnit:
    return ChangeUnit(
        id=unit_id,
        intent={"summary": "把 web 扩到 2 副本"},
        effect=Effect(
            task="scale", args={}, undo_task="undo_scale", capability="compose.scale"
        ),
        tenant=tenant,
        binding="local",
        handle=handle,
        verdict=verdict,
        idempotency_key=key,
    )


def _on_clean_ledger(scenario: Callable[[DbLedger], Awaitable]):
    """建表 → 清空 → 跑一个场景,全在同一个事件循环里。"""

    async def wrapped():
        await ensure_schema()
        async with async_session_factory() as session:
            await session.execute(delete(ChangeEvent))
            await session.commit()
        return await scenario(DbLedger())

    return asyncio.run(wrapped())


def test_latest_folds_events_by_unit():
    async def scenario(ledger):
        await ledger.append(_unit(verdict=VERDICT_KEPT))
        await ledger.append(_unit(verdict=VERDICT_ROLLED_BACK))
        return await ledger.latest()

    rows = _on_clean_ledger(scenario)
    assert len(rows) == 1
    assert rows[0]["verdict"] == VERDICT_ROLLED_BACK


def test_latest_filters_by_tenant():
    async def scenario(ledger):
        await ledger.append(_unit(unit_id="a", tenant="t1"))
        await ledger.append(_unit(unit_id="b", tenant="t2"))
        return await ledger.latest(tenant="t1")

    rows = _on_clean_ledger(scenario)
    assert [row["id"] for row in rows] == ["a"]


def test_history_keeps_write_order():
    async def scenario(ledger):
        await ledger.append(_unit(verdict=VERDICT_BLOCKED, handle=None))
        await ledger.append(_unit(verdict=VERDICT_KEPT))
        await ledger.append(_unit(verdict=VERDICT_ROLLED_BACK))
        return await ledger.history("u1")

    rows = _on_clean_ledger(scenario)
    assert [row["verdict"] for row in rows] == [
        VERDICT_BLOCKED,
        VERDICT_KEPT,
        VERDICT_ROLLED_BACK,
    ]


def test_find_returns_the_newest_event_for_a_key():
    """放行之后同一个幂等键有两行,重放必须看到最新的那次结论。"""

    async def scenario(ledger):
        await ledger.append(_unit(verdict=VERDICT_BLOCKED, handle=None, key="wf-1"))
        await ledger.append(_unit(verdict=VERDICT_KEPT, key="wf-1"))
        return await ledger.find("wf-1")

    row = _on_clean_ledger(scenario)
    assert row is not None
    assert row["verdict"] == VERDICT_KEPT


def test_limit_is_applied_after_folding():
    async def scenario(ledger):
        for index in range(3):
            await ledger.append(_unit(unit_id=f"u{index}"))
        return await ledger.latest(limit=2)

    assert len(_on_clean_ledger(scenario)) == 2


def test_concurrent_appends_do_not_lose_rows():
    """文件账本的硬伤:并发追加会互相踩。业务库不该丢行。"""

    async def scenario(ledger):
        await asyncio.gather(*[ledger.append(_unit(unit_id=f"u{i}")) for i in range(20)])
        return await ledger.read()

    rows = _on_clean_ledger(scenario)
    assert len(rows) == 20
    assert len({row["id"] for row in rows}) == 20

def test_factory_picks_the_configured_backend(monkeypatch):
    """配置说 db 就别写文件,说 file 就别碰库。"""
    from engine.change_unit import JsonlLedger, create_ledger
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    assert isinstance(create_ledger(), JsonlLedger)

    monkeypatch.setattr(config.settings, "change_ledger_backend", "db")
    assert isinstance(create_ledger(), DbLedger)


def test_api_reads_the_db_ledger(monkeypatch):
    """API 与推进器共用同一个账本实现:写进去的行,接口能按租户查出来。

    不能混用 TestClient:它自带一个事件循环,而 async 引擎的池绑在创建它的循环上。
    """
    import httpx
    from fastapi import FastAPI

    from engine.api.routes import changes as changes_mod
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "change_ledger_backend", "db")

    async def scenario():
        await ensure_schema()
        async with async_session_factory() as session:
            await session.execute(delete(ChangeEvent))
            await session.commit()
        await DbLedger().append(_unit(unit_id="u9", tenant="t1"))

        app = FastAPI()
        app.include_router(changes_mod.router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            mine = (await client.get("/api/changes?tenant=t1")).json()
            other = (await client.get("/api/changes?tenant=t2")).json()
        return mine, other

    mine, other = asyncio.run(scenario())
    assert mine["total"] == 1
    assert mine["items"][0]["id"] == "u9"
    assert other["total"] == 0

