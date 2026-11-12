# tests/test_integration/test_rbac_admin.py
"""角色与用户管理:授出去的不能超过自己,最后一个所有者删不掉。

每个用例一整段协程跑完:async 引擎绑定在事件循环上,分几次 asyncio.run
会把连接留在已关闭的循环里。
"""

import asyncio
import os
import uuid

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
    """每个用例从"库里没有用户"开始,并丢掉上一轮留下的连接。"""
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


def _owner_identity() -> Identity:
    async def run():
        return await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")

    return asyncio.run(run())


def test_bootstrap_creates_an_owner_with_everything():
    identity = _owner_identity()
    assert identity.tenant == TENANT
    assert set(identity.permissions) == set(ALL_PERMISSIONS)


def test_roles_are_data_and_start_with_three_presets():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        roles = await admin_store.list_roles(owner)
        keys = {r["key"] for r in roles}
        assert {"owner", "operator", "viewer"} <= keys
        assert all(r["is_system"] for r in roles if r["key"] in {"owner", "operator", "viewer"})
        return roles

    asyncio.run(scenario())


def test_a_custom_role_cannot_grant_more_than_the_creator_has():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        limited = Identity(
            user_id=owner.user_id,
            name="ops",
            tenant=TENANT,
            permissions=frozenset({"changes.read"}),
        )
        with pytest.raises(admin_store.AdminError):
            await admin_store.create_role(
                limited,
                key="super",
                name="超级",
                description="",
                permissions=["settings.write"],
            )

    asyncio.run(scenario())


def test_a_sub_user_cannot_exceed_its_parent():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        role = await admin_store.create_role(
            owner, key="reader", name="只读", description="", permissions=["changes.read"]
        )
        ops = await admin_store.create_user(
            owner,
            email="ops@example.com",
            password="ops-pass-123",
            display_name="ops",
            role_ids=[role["id"]],
        )
        # owner 建的是同级用户,不是子账号
        assert ops["is_sub_user"] is False

        ops_identity = Identity(
            user_id=ops["id"], name="ops", tenant=TENANT, permissions=frozenset({"changes.read"})
        )
        sub = await admin_store.create_user(
            ops_identity,
            email="sub@example.com",
            password="sub-pass-123",
            display_name="sub",
        )
        assert sub["is_sub_user"] is True

        # 子账号不能拿到父亲没有的权限
        with pytest.raises(admin_store.AdminError):
            await admin_store.create_user(
                ops_identity,
                email="sub2@example.com",
                password="sub-pass-123",
                permissions=["settings.write"],
            )

    asyncio.run(scenario())


def test_the_last_owner_cannot_be_deleted():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        other = Identity(
            user_id=str(uuid.uuid4()), name="x", tenant=TENANT, permissions=ALL_PERMISSIONS
        )
        with pytest.raises(admin_store.AdminError):
            await admin_store.delete_user(other, owner.user_id)

    asyncio.run(scenario())


def test_a_system_role_cannot_be_deleted():
    async def scenario():
        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        roles = await admin_store.list_roles(owner)
        owner_role = next(r for r in roles if r["key"] == "owner")
        with pytest.raises(admin_store.AdminError):
            await admin_store.delete_role(owner, owner_role["id"])

    asyncio.run(scenario())
