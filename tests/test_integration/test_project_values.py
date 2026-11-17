# tests/test_integration/test_project_values.py
"""项目这一级的三个值 —— 可见性、默认发布参数、项目级凭据。

一条判据一句话:

- 给一个项目配一条默认发布参数,同租户别的项目与别的仓库不受影响
- 项目可见性挡得住列出它的仓库
- 项目级凭据的值不进业务库,只回答"设了没有"
"""

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from engine.auth import Identity
from engine.db.models import Project, ProjectSetting, Tenant
from engine.projects import project_settings, reload_project_snapshot
from engine.shared.config import config
from engine.workflows.release import resolve_release_config

pytestmark = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)

TENANT = "acme"


@pytest.fixture(autouse=True)
def clean():
    import engine.db.models  # noqa: F401
    from engine.db import engine as async_engine
    from engine.db.base import Base

    try:
        asyncio.run(async_engine.dispose())
    except Exception:
        pass
    sync_engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
    with sync_engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.drop_all(sync_engine)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    config.apply_projects(defaults={}, repo_project={})
    yield
    config.apply_projects(defaults={}, repo_project={})


async def _seed() -> None:
    """一个工作区,两个项目,每个项目下两个仓库。"""
    from engine.db import async_session_factory

    async with async_session_factory() as session:
        tenant = Tenant(slug=TENANT, name="Acme", settings={})
        session.add(tenant)
        await session.flush()
        acme = Project(tenant_id=tenant.id, slug="acme", name="Acme", source="")
        other = Project(tenant_id=tenant.id, slug="other", name="Other", source="")
        session.add_all([acme, other])
        await session.flush()
        session.add_all(
            [
                Project(
                    tenant_id=tenant.id,
                    parent_id=acme.id,
                    slug="github-acme-api",
                    source="github",
                    name="acme/api",
                ),
                Project(
                    tenant_id=tenant.id,
                    parent_id=acme.id,
                    slug="github-acme-web",
                    source="github",
                    name="acme/web",
                ),
                Project(
                    tenant_id=tenant.id,
                    parent_id=other.id,
                    slug="github-other-api",
                    source="github",
                    name="other/api",
                ),
            ]
        )
        await session.commit()


async def _set_defaults(slug: str, values: dict[str, str]) -> None:
    from engine.db import async_session_factory

    async with async_session_factory() as session:
        project = await session.scalar(select(Project).where(Project.slug == slug))
        row = await session.scalar(
            select(ProjectSetting).where(ProjectSetting.project_id == project.id)
        )
        if row is None:
            row = ProjectSetting(
                tenant_id=project.tenant_id, project_id=project.id, credentials=[]
            )
            session.add(row)
        row.defaults = values
        await session.commit()
    await reload_project_snapshot()


def test_a_project_default_only_touches_its_own_repos():
    async def scenario():
        await _seed()
        await _set_defaults("acme", {"service": "acme-api", "mode": "compose"})

        # acme 下的两个仓库都读到这一层
        for repo in ("acme/api", "acme/web"):
            values = resolve_release_config(TENANT, repo, "acme")
            assert values["service"] == "acme-api"
            assert values["mode"] == "compose"

        # 别的项目不受影响
        assert resolve_release_config(TENANT, "other/api", "other")["service"] == ""

        # 仓库自己那一行仍然压过项目默认
        config.apply_stored(
            {TENANT: {"release": {"acme/web": '{"service": "web-only"}'}}}
        )
        values = resolve_release_config(TENANT, "acme/web", "acme")
        assert values["service"] == "web-only"
        # 同一个项目里的另一个仓库还是项目默认
        assert resolve_release_config(TENANT, "acme/api", "acme")["service"] == "acme-api"

    asyncio.run(scenario())


def test_release_resolution_finds_the_project_from_the_repo_slug():
    """载荷里只有仓库全名时,项目这一层靠快照里的反查补上。"""
    async def scenario():
        await _seed()
        await _set_defaults("acme", {"service": "from-project"})
        from engine.workflows.release import release_config

        values = release_config(
            {
                "tenant_slug": TENANT,
                "repo_full_name": "acme/api",
                "repo_slug": "github-acme-api",
            }
        )
        assert values["service"] == "from-project"

    asyncio.run(scenario())


def test_project_settings_are_read_in_one_batch():
    async def scenario():
        await _seed()
        await _set_defaults("acme", {"service": "x"})
        from engine.db import async_session_factory

        async with async_session_factory() as session:
            tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == TENANT))
            rows = await project_settings(session, tenant_id, ["acme", "other", "nope"])
        assert set(rows) == {"acme", "other"}
        assert rows["acme"].defaults == {"service": "x"}
        # 没有那一行 = 全用工作区默认,不写空行占位
        assert rows["other"].defaults == {}
        assert rows["other"].visibility == "workspace"

    asyncio.run(scenario())


def test_a_restricted_project_hides_its_repos_from_the_list():
    """可见性只回答"列不列出来",不替代权限判定。

    这里不 request 整条 HTTP 栈:看得见 / 看不见是 `_restricted_projects` 那句
    判据的事,而它在两条列表接口里被调了同一份。
    """
    async def scenario():
        from engine.db import async_session_factory
        from engine.api.routes.console import _restricted_projects

        await _seed()

        async with async_session_factory() as session:
            project = await session.scalar(select(Project).where(Project.slug == "acme"))
            session.add(
                ProjectSetting(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    visibility="restricted",
                    credentials=[],
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            hidden = await _restricted_projects(session, TENANT)
            # 只列出来这一处:restricted 的项目连同它下面的仓库都按这个 slug 挡
            assert hidden == {"acme"}
            # 别的工作区里同样标 restricted 的项目不该串进来
            assert await _restricted_projects(session, "other-ws") == set()

    asyncio.run(scenario())
