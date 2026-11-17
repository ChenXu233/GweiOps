"""自助注册即建工作区(共享部署的准入条件)。

判据四条:

1. 注册的人落进**他自己建的那一个工作区**,不是配置指定、也不是默认那一个;
2. 他在那个工作区里是 owner —— 一个"有成员关系但没有角色"的人登录进去什么都
   看不见,而且不会报错;
3. 配了 `registration_tenant` 时仍按老路走(单租户自部署靠它);
4. 开通状态说得出下一步,而且**不改任何东西**。
"""

from __future__ import annotations

import asyncio
import os

import pytest
import sqlalchemy as sa

from engine.auth import registration as policy_mod
from engine.auth import registration_store as reg
from engine.shared.config import config as app_config

pytestmark = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@pytest.fixture(autouse=True)
def clean():
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
    yield


@pytest.fixture
def open_signup(monkeypatch):
    monkeypatch.setattr(app_config.settings, "registration_enabled", True)
    monkeypatch.setattr(app_config.settings, "registration_tenant", "")
    monkeypatch.setattr(app_config.settings, "registration_signup_role", "owner")
    return policy_mod.policy_for("")


def test_a_newcomer_gets_their_own_workspace_as_owner(open_signup):
    async def run():
        person, identity = await reg.create_user(
            email="newbie@example.com", password="pass-123456", policy=open_signup
        )
        assert person.email == "newbie@example.com"
        # slug 从邮箱来:可读、能进 URL
        assert identity.tenant == "newbie"
        # owner 的全部权限,不是空集
        assert "users.manage" in identity.permissions
        assert "changes.approve" in identity.permissions

        from sqlalchemy import select

        from engine.db import async_session_factory
        from engine.db.models import Membership, Role, Tenant, UserRole

        async with async_session_factory() as session:
            slugs = set((await session.execute(select(Tenant.slug))).scalars())
            # 没有"默认租户"这一行:他自己那个就是唯一的工作区
            assert slugs == {"newbie"}
            roles = (
                await session.execute(
                    select(Role.key).join(Tenant, Tenant.id == Role.tenant_id).where(Tenant.slug == "newbie")
                )
            ).scalars()
            # 三个预设角色都在新工作区里建出来了
            assert set(roles) == {"owner", "operator", "viewer"}
            granted = (
                await session.execute(
                    select(Role.key)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .join(Membership, Membership.user_id == UserRole.user_id)
                )
            ).scalars()
            assert set(granted) == {"owner"}

    asyncio.run(run())


def test_the_slug_never_collides_with_an_existing_workspace(open_signup):
    """有人手工建了同名工作区时,注册照样走得通,slug 加一段后缀。"""

    async def run():
        from engine.db import async_session_factory
        from engine.db.models import Tenant

        async with async_session_factory() as session:
            session.add(Tenant(slug="newbie", name="别人先建的"))
            await session.commit()

        _person, identity = await reg.create_user(
            email="newbie@example.com", password="pass-123456", policy=open_signup
        )
        assert identity.tenant.startswith("newbie-")
        assert identity.tenant != "newbie"

    asyncio.run(run())


def test_a_fixed_registration_tenant_still_wins(open_signup, monkeypatch):
    """单租户自部署:配了 `registration_tenant` 就落进那一个,角色用 default_role。"""

    async def run():
        from engine.auth import store as auth_store
        from engine.db import async_session_factory
        from engine.db.models import Tenant

        async with async_session_factory() as session:
            tenant = Tenant(slug="this-machine", name="这台机器")
            session.add(tenant)
            await session.flush()
            await auth_store.ensure_default_roles(session, tenant.id)
            await session.commit()

        monkeypatch.setattr(app_config.settings, "registration_tenant", "this-machine")
        monkeypatch.setattr(app_config.settings, "registration_default_role", "viewer")
        policy = policy_mod.policy_for("")

        _person, identity = await reg.create_user(
            email="second@example.com", password="pass-123456", policy=policy
        )
        assert identity.tenant == "this-machine"
        assert "users.manage" not in identity.permissions

        async with async_session_factory() as session:
            from sqlalchemy import select

            assert set((await session.execute(select(Tenant.slug))).scalars()) == {"this-machine"}

    asyncio.run(run())


def test_onboarding_says_what_the_next_step_is(open_signup):
    """开通状态:四步、每步带下一步、而且读它不改任何东西。"""

    async def run():
        from sqlalchemy import select

        from engine.db import async_session_factory
        from engine.db.models import Tenant
        from engine.projects.onboarding import onboarding_status

        _person, identity = await reg.create_user(
            email="newbie@example.com", password="pass-123456", policy=open_signup
        )

        async with async_session_factory() as session:
            tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == identity.tenant))
            before = (
                await session.execute(select(sa.func.count()).select_from(Tenant))
            ).scalar()

        async with async_session_factory() as session:
            status = await onboarding_status(session, tenant_id, settings=app_config.settings)

        assert [step["key"] for step in status["steps"]] == [
            "workspace",
            "source",
            "repo",
            "first-workflow",
        ]
        assert status["steps"][0]["done"] is True
        # 还没接来源、没有仓库、没有账:三步都未完成,每一步都说得出下一步
        for step in status["steps"][1:]:
            assert step["done"] is False
            assert step["next"]
        assert status["complete"] is False

        async with async_session_factory() as session:
            after = (
                await session.execute(select(sa.func.count()).select_from(Tenant))
            ).scalar()
        assert after == before

    asyncio.run(run())
