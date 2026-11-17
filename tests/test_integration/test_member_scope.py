# tests/test_integration/test_member_scope.py
"""成员这一栏也能带范围 —— 两栏不是一栏。

`changes.approve@acme` 原来只能挂在角色上。一个工作区里"张三能放行项目 acme、
李四能放行仓库 acme/api"这种分工,靠角色表达只能建一堆只差一格的角��。
成员行自己的 `permissions` 里本来就允许写带范围的条目(判定走 `split_scoped`),
这次把**写得进去**和**授不出去超过自己**这两件事补上。
"""

import asyncio
import os

import pytest
import sqlalchemy as sa

from engine.auth import ALL_PERMISSIONS, Identity
from engine.auth import admin as admin_store
from engine.auth import store as auth_store

pytestmark = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)

TENANT = "default"


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
    yield


def test_a_member_can_be_granted_a_scoped_permission():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        role = await admin_store.create_role(
            owner, key="viewer2", name="只读", description="", permissions=["changes.read"]
        )
        member = await admin_store.create_user(
            owner,
            email="scoped@example.com",
            password="scoped-pass-123",
            role_ids=[role["id"]],
        )
        updated = await admin_store.update_user(
            owner,
            member["id"],
            permissions=["changes.approve@acme", "changes.rollback@github-acme-api"],
        )
        assert updated["status"] == "active"

        listed = await admin_store.list_users(owner)
        row = next(u for u in listed if u["id"] == member["id"])
        # 带范围的授权落在**成员这一行**上,和角色里那份是两栏
        assert row["permissions"] == [
            "changes.approve@acme",
            "changes.rollback@github-acme-api",
        ]

        # 判定时它算在哪:项目 acme 与仓库 acme/api 都算,别的仓库不算
        identity = Identity(
            user_id=member["id"],
            name="scoped",
            tenant=TENANT,
            permissions=frozenset(),
            scoped_permissions={
                "changes.approve": frozenset({"acme"}),
                "changes.rollback": frozenset({"github-acme-api"}),
            },
        )
        assert identity.allows("changes.approve", "acme/api", "acme")
        assert not identity.allows("changes.approve", "acme/web", "other")
        assert identity.allows("changes.rollback", "github-acme-api", "acme")

    asyncio.run(scenario())


def test_a_scoped_grant_is_dropped_when_the_permission_cannot_be_narrowed():
    """收窄了的读权限没有意义:它会让那个人一条账都看不到。丢掉,不猜。"""
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        member = await admin_store.create_user(
            owner, email="narrow@example.com", password="narrow-pass-123"
        )
        await admin_store.update_user(
            owner, member["id"], permissions=["users.manage@acme", "changes.read@acme"]
        )
        listed = await admin_store.list_users(owner)
        row = next(u for u in listed if u["id"] == member["id"])
        # users.manage 收不了范围;changes.read 可以
        assert row["permissions"] == ["changes.read@acme"]

    asyncio.run(scenario())


def test_a_sub_user_cannot_hand_out_scope_it_does_not_have():
    """我只有 acme/api 的放行权,就不能给别人整个工作区的放行权。"""
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        manager = await admin_store.create_user(
            owner,
            email="manager@example.com",
            password="manager-pass-123",
            permissions=["users.manage", "changes.approve@github-acme-api"],
        )
        # 这个人手上实际有什么:建人时给的那两样。`users.manage` 是工作区级,
        # `changes.approve` 只对 acme/api 那一个仓库。
        parent = Identity(
            user_id=manager["id"],
            name="manager",
            tenant=TENANT,
            permissions=frozenset({"users.manage"}),
            scoped_permissions={"changes.approve": frozenset({"github-acme-api"})},
        )
        sub = await admin_store.create_user(
            parent,
            email="sub@example.com",
            password="sub-pass-123",
            permissions=["changes.approve@github-acme-api"],
        )
        # 同一个范围可以给
        assert sub["is_sub_user"] is True

        # 别的范围不能给
        with pytest.raises(admin_store.AdminError):
            await admin_store.update_user(
                parent, sub["id"], permissions=["changes.approve@acme"]
            )
        # 整个工作区的放行更不能给
        with pytest.raises(admin_store.AdminError):
            await admin_store.update_user(
                parent, sub["id"], permissions=["changes.approve"]
            )

    asyncio.run(scenario())


def test_an_owner_keeps_the_whole_catalogue():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        assert set(owner.permissions) == set(ALL_PERMISSIONS)

    asyncio.run(scenario())
