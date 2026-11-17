# tests/test_integration/test_invitations.py
"""邀请与认领 —— 邀请链接只能用一次,过期与用过各说各的下一步。

三条判据,写成能跑的东西:

- 同一邮箱在 Acme 与 Beta 各有一条成员关系,只有一份密码(被邀请人在第二个
  工作区里**认领**,不是再建一个人)
- 邀请链接只能用一次;过期 / 已用 / 撤销各给一句能照着办的下一步
- 被邀请人拿到的角色与管理员发邀请时选的一致
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select

from engine.auth import Identity
from engine.auth import invitations as invite_store
from engine.auth import store as auth_store

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


async def _owner() -> Identity:
    return await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")


async def _expire(token: str) -> None:
    """把这条邀请的到期时间挪到过去。过期是时间的事,不该靠 sleep 去演。"""
    from engine.auth import hash_session_token
    from engine.db import async_session_factory
    from engine.db.models import Invitation
    from sqlalchemy import select

    async with async_session_factory() as session:
        row = await session.scalar(
            select(Invitation).where(Invitation.token_hash == hash_session_token(token))
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()


def test_a_new_email_gets_an_invite_it_must_use_once():
    async def scenario():
        owner = await _owner()
        role = None
        from engine.auth import admin as admin_store

        roles = await admin_store.list_roles(owner)
        role = next(r for r in roles if r["key"] == "operator")

        invite, token = await invite_store.create_invitation(
            owner, email="new@example.com", role_ids=[role["id"]]
        )
        assert invite["state"] == "pending"

        seen = await invite_store.preview(token)
        assert seen["state"] == "pending"
        assert seen["workspace"] == owner.tenant
        assert seen["existing_account"] is False
        # 被邀请人看到的角色,就是管理员发邀请时选的那个
        assert [r["key"] for r in seen["roles"]] == ["operator"]

        person, identity = await invite_store.accept(
            token, password="new-pass-123", display_name="新人"
        )
        assert identity.tenant == owner.tenant
        assert "changes.read" in identity.permissions
        assert "users.manage" not in identity.permissions

        # 用过的链接:再点得到"已经用过了",不是一个 404
        again = await invite_store.preview(token)
        assert again["state"] == "accepted"
        assert again["note"]
        with pytest.raises(invite_store.InviteError) as caught:
            await invite_store.accept(token, password="another-pass-123")
        assert "用过" in str(caught.value)

    asyncio.run(scenario())


def test_an_expired_invite_says_what_to_do_next():
    async def scenario():
        owner = await _owner()
        _invite, token = await invite_store.create_invitation(owner, email="late@example.com")
        await _expire(token)
        seen = await invite_store.preview(token)
        assert seen["state"] == "expired"
        assert "重新发" in seen["note"]
        with pytest.raises(invite_store.InviteError) as caught:
            await invite_store.accept(token, password="late-pass-123")
        assert "过期" in str(caught.value)

    asyncio.run(scenario())


def test_a_revoked_invite_cannot_be_used():
    async def scenario():
        owner = await _owner()
        invite, token = await invite_store.create_invitation(owner, email="gone@example.com")
        await invite_store.revoke_invitation(owner, invite["id"])
        seen = await invite_store.preview(token)
        assert seen["state"] == "revoked"
        with pytest.raises(invite_store.InviteError):
            await invite_store.accept(token, password="gone-pass-123")

    asyncio.run(scenario())


def test_the_second_workspace_claims_the_person_instead_of_making_a_new_one():
    """一个人两份凭据的毛病,在这一条上不许再出现。

    Acme 里的人被邀进 Beta:认领已有的 person,加一条成员关系,密码一个字不动。
    """
    async def scenario():
        owner = await _owner()
        from engine.db import async_session_factory
        from engine.db.models import Person, Tenant

        _invite, token = await invite_store.create_invitation(owner, email="dual@example.com")
        person, acme = await invite_store.accept(token, password="dual-pass-123")

        # 第二个工作区
        async with async_session_factory() as session:
            beta = Tenant(slug="beta", name="Beta", settings={})
            session.add(beta)
            await session.commit()

        # 认领,不是再建一个人:两次接完,库里还是两条 person(所有者 + 他)。
        async with async_session_factory() as session:
            people = (await session.scalars(select(Person))).all()
            assert len(people) == 2
            assert sum(1 for p in people if p.email == "dual@example.com") == 1

        beta_owner = Identity(
            user_id=str(uuid.uuid4()),
            name="beta 所有者",
            tenant="beta",
            permissions=owner.permissions,
        )
        _invite2, token2 = await invite_store.create_invitation(
            beta_owner, email="dual@example.com"
        )
        seen = await invite_store.preview(token2)
        # 这个邮箱已经有账号了:他不用再设密码,登录一次就能接
        assert seen["existing_account"] is True

        claimed, in_beta = await invite_store.accept(token2)
        assert claimed.id == person.id
        assert in_beta.tenant == "beta"
        assert in_beta.person_id == str(person.id)
        assert in_beta.user_id != acme.user_id

        # 一份密码,两处都能登录
        assert await auth_store.authenticate("dual@example.com", "dual-pass-123") is not None

    asyncio.run(scenario())


def test_a_second_invite_to_the_same_email_kills_the_first():
    """同时有效的邀请越多,撞上来的机会越多 —— 和验证码是同一个道理。"""
    async def scenario():
        owner = await _owner()
        _first, first_token = await invite_store.create_invitation(
            owner, email="twice@example.com"
        )
        _second, second_token = await invite_store.create_invitation(
            owner, email="twice@example.com"
        )
        assert (await invite_store.preview(first_token))["state"] == "revoked"
        assert (await invite_store.preview(second_token))["state"] == "pending"

    asyncio.run(scenario())


def test_an_existing_member_is_not_invited_again():
    async def scenario():
        owner = await _owner()
        _invite, token = await invite_store.create_invitation(
            owner, email="member@example.com"
        )
        await invite_store.accept(token, password="member-pass-123")
        with pytest.raises(invite_store.InviteError) as caught:
            await invite_store.create_invitation(owner, email="member@example.com")
        assert "已经" in str(caught.value)

    asyncio.run(scenario())
