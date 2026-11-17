# tests/test_integration/test_invitation_routes.py
"""邀请的两条口:发要登录,接不用。

接邀请的人那时还没有账号 —— 所以 `/api/invitations/{token}` 和 `/api/auth/*`
一样不走鉴权中间件。这条豁免只覆盖那一个 token 路径:列表与发邀请仍然要
`users.read` / `users.manage`。
"""

import asyncio
import os

import pytest
import sqlalchemy as sa

from engine.api.auth import INVITE_PATH

pytestmark = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@pytest.fixture(autouse=True)
def clean():
    import engine.db.models  # noqa: F401
    from engine.db import engine as async_engine
    from engine.db.base import Base

    try:
        asyncio.run(async_engine.dispose())
    except Exception:  # noqa: BLE001 - 没有连接要关
        pass
    sync_engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
    with sync_engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.drop_all(sync_engine)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    yield


def test_only_the_token_path_is_exempt_from_auth():
    """豁免的形状要窄到只有那一枚令牌。"""
    assert INVITE_PATH.match("/api/invitations/abc123")
    # 列表与发邀请仍然要登录
    assert not INVITE_PATH.match("/api/invitations")
    assert not INVITE_PATH.match("/api/invitations/")
    # 别的接口一个都不沾
    assert not INVITE_PATH.match("/api/users")


def test_an_invite_is_issued_used_and_then_refused():
    """发 → 接 → 再用:每一步的状态都说清。"""
    async def scenario():
        from engine.auth import Identity
        from engine.auth import invitations as invite_store
        from engine.auth import store as auth_store

        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        roles = await _roles(owner)
        operator = next(r for r in roles if r["key"] == "operator")

        invite, token = await invite_store.create_invitation(
            owner, email="new@example.com", role_ids=[operator["id"]]
        )
        assert invite["state"] == "pending"
        assert invite["note"] == ""

        seen = await invite_store.preview(token)
        assert seen["existing_account"] is False
        # 被邀请人看到的角色,就是管理员发邀请时选的那个
        assert [r["key"] for r in seen["roles"]] == ["operator"]

        person, identity = await invite_store.accept(
            token, password="new-pass-123", display_name="新人"
        )
        assert identity.tenant == owner.tenant
        assert set(identity.permissions) == set(operator_permissions(roles))

        again = await invite_store.preview(token)
        assert again["state"] == "accepted"
        assert again["note"]
        with pytest.raises(invite_store.InviteError) as caught:
            await invite_store.accept(token, password="another-pass-123")
        assert "用过" in str(caught.value)

    asyncio.run(scenario())


def test_the_list_only_shows_this_workspace():
    async def scenario():
        from engine.auth import invitations as invite_store
        from engine.auth import store as auth_store

        owner = await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")
        made = await invite_store.create_invitation(owner, email="later@example.com")
        revoked = await invite_store.revoke_invitation(owner, made[0]["id"])
        assert revoked["state"] == "revoked"

        rows = await invite_store.list_invitations(owner)
        row = next(r for r in rows if r["id"] == made[0]["id"])
        assert row["state"] == "revoked"
        assert row["workspace"] == owner.tenant

    asyncio.run(scenario())


async def _roles(identity) -> list[dict]:
    from engine.auth import admin as admin_store

    return await admin_store.list_roles(identity)


def operator_permissions(roles: list[dict]) -> list[str]:
    operator = next(r for r in roles if r["key"] == "operator")
    return operator["permissions"]
