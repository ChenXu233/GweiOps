# tests/test_integration/test_registration_flow.py
"""注册落库的那一半:码只存哈希、试错有上限、申请核验后才建号、找回密码的两条路。

门控用例:要真实 Postgres。每个用例从头建表,一整段协程跑完。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa

from engine.auth import hash_password
from engine.auth import registration as policy_mod
from engine.shared.config import config as app_config
from engine.auth import registration_store as reg
from engine.db.models import User, UserActivation, UserContact, VerificationCode
from engine.quota import store as quota_store

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


async def _bootstrap() -> None:
    from engine.auth import store as auth_store

    await auth_store.bootstrap_first_admin("owner@example.com", "owner-pass-123")


@pytest.fixture
def policy(monkeypatch):
    # 按对象打补丁:字符串形式会被当成模块路径去 import,而 config 是单例不是模块
    monkeypatch.setattr(app_config.settings, "registration_enabled", True)
    monkeypatch.setattr(app_config.settings, "registration_test_code", "")
    return policy_mod.policy_for("")


def test_the_code_is_only_stored_as_a_hash(policy):
    async def run():
        await _bootstrap()
        code = await reg.issue_code("email", "new@example.com", "register", policy)
        from engine.db import async_session_factory
        from sqlalchemy import select

        async with async_session_factory() as session:
            row = await session.scalar(select(VerificationCode))
            # 库被看到也换不出能用的码:存的不是码本身
            assert row.code_hash != code
            assert len(row.code_hash) == 64

    asyncio.run(run())


def test_a_wrong_code_burns_an_attempt(policy):
    async def run():
        await _bootstrap()
        code = await reg.issue_code("email", "new@example.com", "register", policy)
        with pytest.raises(reg.RegistrationError):
            await reg.consume_code("email", "new@example.com", "register", "000000", policy)
        # 再给对的码也还能用:错一次不至于重来
        await reg.consume_code("email", "new@example.com", "register", code, policy)

    asyncio.run(run())


def test_too_many_attempts_kills_the_code(policy, monkeypatch):
    monkeypatch.setattr(app_config.settings, "registration_max_attempts", 2)

    async def run():
        await _bootstrap()
        narrowed = policy_mod.policy_for("")
        code = await reg.issue_code("email", "new@example.com", "register", narrowed)
        for _ in range(2):
            with pytest.raises(reg.RegistrationError):
                await reg.consume_code("email", "new@example.com", "register", "000000", narrowed)
        # 试够次数之后,连对的码也不认 —— 否则"有上限"只是拖时间
        with pytest.raises(reg.RegistrationError):
            await reg.consume_code("email", "new@example.com", "register", code, narrowed)

    asyncio.run(run())


def test_a_code_cannot_be_reused_for_another_purpose(policy):
    async def run():
        await _bootstrap()
        code = await reg.issue_code("email", "new@example.com", "register", policy)
        with pytest.raises(reg.RegistrationError):
            await reg.consume_code("email", "new@example.com", "reset", code, policy)

    asyncio.run(run())


def test_registering_creates_a_user_with_the_default_role(policy):
    async def run():
        await _bootstrap()
        await reg.stage_activation("email", "new@example.com", "新来的", "pass-123456")
        user, identity = await reg.create_user(
            email="new@example.com",
            password_hash=hash_password("pass-123456"),
            role_key=policy.default_role,
            policy=policy,
        )
        assert user.email == "new@example.com"
        # 默认角色 viewer 给了只读那几项:注册进来的人不该一上来就能改世界
        assert "changes.read" in identity.permissions
        assert "settings.write" not in identity.permissions
        assert identity.can_write is False

    asyncio.run(run())


def test_a_phone_registration_lands_on_a_place_holder_email(policy):
    async def run():
        await _bootstrap()
        user, _ = await reg.create_user(
            phone="+8613800000000",
            password="pass-123456",
            role_key=policy.default_role,
            policy=policy,
        )
        # 手机号注册的人也得有一行唯一身份,否则"谁能登录"要查两处
        assert user.email == "+8613800000000@phone.local"
        from engine.db import async_session_factory
        from sqlalchemy import select

        async with async_session_factory() as session:
            contacts = list((await session.execute(select(UserContact))).scalars())
        assert [c.kind for c in contacts] == ["phone"]
        assert contacts[0].confirmed is True

    asyncio.run(run())


def test_the_same_email_cannot_register_twice(policy):
    async def run():
        await _bootstrap()
        await reg.create_user(email="new@example.com", password="pass-123456", policy=policy)
        with pytest.raises(reg.RegistrationError):
            await reg.create_user(email="new@example.com", password="pass-123456", policy=policy)

    asyncio.run(run())


def test_a_reset_link_works_once(policy):
    async def run():
        await _bootstrap()
        token = await reg.issue_reset_token("owner@example.com", policy)
        assert token
        user = await reg.verify_reset_token(token)
        assert user is not None
        await reg.complete_reset(token, "brand-new-pass")
        with pytest.raises(reg.RegistrationError):
            await reg.complete_reset(token, "again-123456")

    asyncio.run(run())


def test_reset_says_nothing_about_a_missing_account(policy):
    async def run():
        await _bootstrap()
        assert await reg.issue_reset_token("nobody@example.com", policy) is None

    asyncio.run(run())


def test_a_password_account_cannot_be_taken_over_by_a_code(policy):
    """拿到手机号不等于拿到账号:侧门在这里关掉。"""

    async def run():
        await _bootstrap()
        await reg.create_user(
            email="phone@example.com",
            phone="+8613800000001",
            password="pass-123456",
            policy=policy,
        )
        with pytest.raises(reg.RegistrationError):
            await reg.change_with_code("phone", "+8613800000001", "hijack-123456")

    asyncio.run(run())


def test_an_account_without_a_password_can_set_one_by_code(policy):
    async def run():
        await _bootstrap()
        await reg.create_user(email="oidc@example.com", role_key="viewer", policy=policy)
        await reg.complete_reset_by_user(
            await _user("oidc@example.com"), "set-by-code-123"
        )
        found = await _user("oidc@example.com")
        assert found.password_hash

    asyncio.run(run())


def test_a_pending_activation_is_not_a_user(policy):
    """核验之前人不进 users 表:没核验的"用户"会让租户的人数与权限算错。"""

    async def run():
        await _bootstrap()
        await reg.stage_activation("email", "pending@example.com", "", "pass-123456")
        from engine.db import async_session_factory
        from sqlalchemy import func, select

        async with async_session_factory() as session:
            users = await session.scalar(select(func.count()).select_from(User))
            pending = await session.scalar(select(func.count()).select_from(UserActivation))
        assert users == 1  # 只有那个 owner
        assert pending == 1

    asyncio.run(run())


async def _user(email: str) -> User:
    from engine.db import async_session_factory
    from sqlalchemy import select

    async with async_session_factory() as session:
        return await session.scalar(select(User).where(User.email == email))


def test_quota_counts_only_inside_the_window(policy):
    async def run():
        await _bootstrap()
        from engine.db import async_session_factory
        from engine.db.models import QuotaUsage, Tenant
        from sqlalchemy import select
        from datetime import datetime, timedelta, timezone

        async with async_session_factory() as session:
            tenant_id = await session.scalar(select(Tenant.id))
            now = datetime.now(timezone.utc)
            session.add_all(
                [
                    QuotaUsage(
                        subject_kind="tenant", subject_id=tenant_id, resource="issues", amount=3,
                        used_at=now,
                    ),
                    # 窗口外的那一笔不该被算进来
                    QuotaUsage(
                        subject_kind="tenant", subject_id=tenant_id, resource="issues", amount=99,
                        used_at=now - timedelta(days=60),
                    ),
                ]
            )
            await session.commit()
        used = await quota_store.used_since(
            "tenant", tenant_id, "issues", now - timedelta(days=30)
        )
        assert used == 3

    asyncio.run(run())


def test_a_zero_limit_refuses_everything(policy):
    """把某租户配额调到 0:新流入队被拒,别的东西不受影响。"""
    from engine.shared.config import config

    async def run():
        await _bootstrap()
        try:
            await quota_store.check("tenant", "default", "issues")
            pytest.fail("limit=0 应该拒")
        except quota_store.QuotaExceeded as exc:
            assert "issues" in str(exc)
        # 没声明的资源照旧 —— 配额是加购项,不是把整站关掉
        assert (await quota_store.check("tenant", "default", "unknown.resource")).unlimited

    config.apply_stored({"default": {"quota": {"issues": "0/30d"}}})
    try:
        asyncio.run(run())
    finally:
        config.apply_stored({})


def test_oidc_binds_once_and_survives_an_email_change(policy):
    async def run():
        await _bootstrap()
        profile = reg.OidcProfile(subject="sub-1", email="ss@example.com", name="单点")
        user, created = await reg.resolve_oidc_user(profile, "https://id.example.com", policy)
        assert created is True

        # 同一个人在提供方那边改了邮箱:认 sub,不该变成两个人
        again = reg.OidcProfile(subject="sub-1", email="changed@example.com", name="单点")
        same, created_again = await reg.resolve_oidc_user(again, "https://id.example.com", policy)
        assert created_again is False
        assert same.id == user.id

    asyncio.run(run())
