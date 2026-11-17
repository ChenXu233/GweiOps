# tests/test_integration/test_repo_connect.py
"""仓库是接入进来的,不是投递自己长出来的。

这组分两层:

- **不依赖库**:slug 与默认归属的规则只有一处实现(`engine/projects/connect.py`),
  投递时判"接入了没有"、接入时建行,读的是同一条规则;能接哪些来源由装着的
  适配器答,不由核心写死。
- **需要库**:接入是幂等的;没接入的仓库投递不入队、也不建行。

第二层要 `GWEI_TEST_DATABASE_URL` 指向可写的 Postgres。
"""

import os

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


class TestSlugRules:
    def test_slug_is_source_plus_full_name(self):
        from engine.projects.connect import repo_slug

        assert repo_slug("github", "acme/api") == "github-acme-api"
        assert repo_slug("cnb", "acme/api") == "cnb-acme-api"
        # 来源不同的同名仓库是两个仓库,这是这条规则存在的理由
        assert repo_slug("github", "acme/api") != repo_slug("cnb", "acme/api")

    def test_webhook_side_reads_the_same_rule(self):
        """投递时判"接入了没有"用的是同一条规则,不是第二份实现。"""
        from engine.projects.connect import repo_slug as canonical
        from engine.workflows.pipeline import repo_slug as pipeline_side

        assert pipeline_side("github", "acme/api") == canonical("github", "acme/api")

    def test_default_project_is_the_first_segment(self):
        from engine.projects.connect import project_slug_of

        assert project_slug_of("acme/api") == "acme"
        # GitLab 的子组:项目问的是"这家是谁",不是路径层级
        assert project_slug_of("group/sub/repo") == "group"

    def test_bad_full_name_is_refused_here_not_later(self):
        from engine.projects.connect import ConnectError, normalize

        for bad in ("", "acme", "acme/", "/api", "acme//api"):
            with pytest.raises(ConnectError):
                normalize("github", bad)
        assert normalize("GitHub", "acme/api") == ("github", "acme/api")


class TestKnownSources:
    def test_sources_come_from_the_adapters(self):
        """能接的来源由适配器声明,不是核心写死的一张表。"""
        from engine.plugin_manager import registry
        from engine.projects.connect import known_sources

        if not registry.names():
            pytest.skip("注册表还没发现插件")

        declared = {
            str(getattr(instance, "source", "") or "")
            for instance in registry.webhook_adapters()
        }
        assert set(known_sources()) == {name for name in declared if name}


@requires_postgres
class TestConnectWritesOneRow:
    @pytest.fixture()
    def db(self):
        """一个空工作区,以及跑完就从库里清掉它的收尾。"""
        import uuid

        import sqlalchemy as sa
        from sqlalchemy.orm import Session

        import engine.db.models  # noqa: F401 — 注册全部模型
        from engine.db.base import Base
        from engine.db.models import Tenant

        sync_engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
        with sync_engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(sync_engine)

        slug = f"ws-{uuid.uuid4().hex[:8]}"
        with Session(sync_engine) as session:
            tenant = Tenant(slug=slug, name="接入")
            session.add(tenant)
            session.commit()
            tenant_id = tenant.id

        yield tenant_id, sync_engine

        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "DELETE FROM projects WHERE tenant_id IN "
                    "(SELECT id FROM tenants WHERE slug = :slug)"
                ),
                {"slug": slug},
            )
            conn.execute(sa.text("DELETE FROM tenants WHERE slug = :slug"), {"slug": slug})
        sync_engine.dispose()

    def test_connecting_twice_keeps_one_row(self, db):
        import asyncio

        import sqlalchemy as sa
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from engine.db.models import Project
        from engine.projects.connect import connect

        tenant_id, sync_engine = db
        url = os.environ["GWEI_TEST_DATABASE_URL"].replace(
            "postgresql+psycopg", "postgresql+asyncpg"
        )

        async def run() -> tuple[bool, int]:
            engine = create_async_engine(url, poolclass=NullPool)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                _, created = await connect(session, tenant_id, "github", "acme/api")
                await session.commit()
            async with factory() as session:
                again, created_again = await connect(session, tenant_id, "github", "acme/api")
                await session.commit()
            await engine.dispose()
            with sync_engine.connect() as conn:
                count = conn.execute(
                    sa.text("SELECT count(*) FROM projects WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                ).scalar_one()
            assert again.slug == "github-acme-api"
            return created, count if not created_again else count

        created, rows = asyncio.run(run())
        assert created is True
        # 一行仓库 + 一行项目,重复接入没有再长出一份
        assert rows == 2

    def test_disconnecting_leaves_the_ledger_alone(self, db):
        import asyncio

        import sqlalchemy as sa
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from engine.projects.connect import connect, disconnect, resolve

        tenant_id, sync_engine = db
        url = os.environ["GWEI_TEST_DATABASE_URL"].replace(
            "postgresql+psycopg", "postgresql+asyncpg"
        )

        async def run() -> bool:
            engine = create_async_engine(url, poolclass=NullPool)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                await connect(session, tenant_id, "cnb", "acme/web")
                await session.commit()
            async with factory() as session:
                removed = await disconnect(session, tenant_id, "cnb", "acme/web")
                await session.commit()
            async with factory() as session:
                gone = await resolve(session, tenant_id, "cnb", "acme/web")
            await engine.dispose()
            assert gone is None
            return removed

        assert asyncio.run(run()) is True


@requires_postgres
class TestUnconnectedDelivery:
    def test_delivery_to_an_unconnected_repo_starts_nothing(self, monkeypatch):
        """没接入的仓库:200 + unconnected,不入队。公网 webhook 不能替陌生人跑工作流。"""
        import json

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from engine.api.routes import webhook as webhook_mod
        from engine.ingest.events import event as normalized_event

        class Adapter:
            def webhook_configured(self):
                return True

            def verify_webhook(self, headers, body):
                return True

            def parse_webhook(self, headers, body):
                return normalized_event(
                    kind="issue",
                    source="github",
                    repo="stranger/repo",
                    repo_id=1,
                    change_id=2,
                    number=3,
                    title="陌生仓库里的一条议题",
                    body="",
                )

        captured: list = []

        async def dedup(*args, **kwargs):
            return True

        async def enqueue(prefix, workflow, delivery_id, payload):
            captured.append(prefix)
            return {"status": "queued"}

        async def unconnected(payload):
            return False

        monkeypatch.setattr(webhook_mod, "source_adapter", lambda name: Adapter())
        monkeypatch.setattr(webhook_mod, "dedup_once", dedup)
        monkeypatch.setattr(webhook_mod, "_enqueue_workflow", enqueue)
        monkeypatch.setattr(webhook_mod, "_connects_here", unconnected)

        app = FastAPI()
        app.include_router(webhook_mod.router)
        client = TestClient(app)
        resp = client.post("/webhook/github", content=json.dumps({}))

        assert resp.status_code == 200
        assert resp.json()["status"] == "unconnected"
        assert "还没接入" in resp.json()["message"]
        assert captured == []
