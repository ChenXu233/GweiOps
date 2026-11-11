# engine/auth/store.py
"""用户与角色的读写 —— 鉴权要用的那部分,不掺业务。

分两层:上面是"怎么算出一个人的权限",下面是对库的增删改。
中间件每个请求都要解析一次会话,所以这里只做必要的事,不做 N+1。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import (
    DEFAULT_ROLES,
    Identity,
    effective_permissions,
    hash_password,
    hash_session_token,
    new_session_token,
    session_expiry,
    verify_password,
)
from engine.db import async_session_factory
from engine.db.models import Role, Tenant, User, UserRole, UserSession

DEFAULT_TENANT_SLUG = "default"


class AuthError(ValueError):
    """鉴权失败。message 是给人看的,不要带内部细节。"""


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------


async def _tenant_slug(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    slug = await session.scalar(select(Tenant.slug).where(Tenant.id == tenant_id))
    return slug or ""


async def _role_permissions(session: AsyncSession, user_id: uuid.UUID) -> list[list[str]]:
    rows = await session.execute(
        select(Role.permissions).join(UserRole, UserRole.role_id == Role.id).where(
            UserRole.user_id == user_id
        )
    )
    return [list(r or []) for (r,) in rows.all()]


async def identity_of(session: AsyncSession, user: User) -> Identity:
    """算出一个人的有效权限。子用户与父用户取交集,父被停用则清零。"""
    own_roles = await _role_permissions(session, user.id)
    permissions = effective_permissions(user.permissions, own_roles)

    if user.parent_id:
        parent = await session.get(User, user.parent_id)
        if parent is None or not parent.active:
            # 父没了或者被停了,子用户不该继续拿着权限
            permissions = frozenset()
        else:
            parent_roles = await _role_permissions(session, parent.id)
            parent_perms = effective_permissions(parent.permissions, parent_roles)
            permissions = effective_permissions(user.permissions, own_roles, parent=parent_perms)

    return Identity(
        user_id=str(user.id),
        name=user.display_name or user.email,
        tenant=await _tenant_slug(session, user.tenant_id),
        permissions=permissions,
        parent_id=str(user.parent_id or ""),
    )


async def users_exist() -> bool:
    async with async_session_factory() as session:
        return bool(await session.scalar(select(func.count()).select_from(User)))


# ---------------------------------------------------------------------------
# 初始化:第一个管理员
# ---------------------------------------------------------------------------


async def ensure_default_roles(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Role]:
    """给租户补上三个预设角色。已经有了就不动它们——权限可能被人改过。"""
    existing = {
        role.key: role
        for role in (
            await session.execute(select(Role).where(Role.tenant_id == tenant_id))
        ).scalars()
    }
    for spec in DEFAULT_ROLES:
        if spec["key"] in existing:
            continue
        role = Role(
            tenant_id=tenant_id,
            key=spec["key"],
            name=spec["name"],
            description=spec["description"],
            permissions=list(spec["permissions"]),
            is_system=spec["is_system"],
        )
        session.add(role)
        existing[spec["key"]] = role
    await session.flush()
    return existing


async def bootstrap_first_admin(
    email: str, password: str, display_name: str = ""
) -> Identity:
    """建租户、预设角色、第一个所有者。库里已经有用户时拒绝。"""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AuthError("邮箱格式不对")
    if len(password or "") < 8:
        raise AuthError("密码至少 8 位")

    async with async_session_factory() as session:
        if await session.scalar(select(func.count()).select_from(User)):
            raise AuthError("已经有用户了,不能再初始化")

        tenant = await session.scalar(select(Tenant).where(Tenant.slug == DEFAULT_TENANT_SLUG))
        if tenant is None:
            tenant = Tenant(slug=DEFAULT_TENANT_SLUG, name="默认租户", settings={})
            session.add(tenant)
            await session.flush()

        roles = await ensure_default_roles(session, tenant.id)
        user = User(
            tenant_id=tenant.id,
            email=email,
            display_name=display_name or email.split("@")[0],
            password_hash=hash_password(password),
            permissions=[],
            status="active",
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role_id=roles["owner"].id))
        await session.commit()
        await session.refresh(user)
        return await identity_of(session, user)


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------


async def authenticate(email: str, password: str) -> tuple[User, Identity] | None:
    """邮箱 + 密码。错了就是错了,不区分"没这个人"和"密码不对"。"""
    email = (email or "").strip().lower()
    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None or not user.active:
            return None
        if not verify_password(password or "", user.password_hash):
            return None
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        identity = await identity_of(session, user)
        return user, identity


async def start_session(
    user_id: uuid.UUID, *, ip: str = "", user_agent: str = ""
) -> str:
    """发一个新会话令牌。返回明文,调用方塞进 cookie,库里只有哈希。"""
    token, token_hash = new_session_token()
    async with async_session_factory() as session:
        session.add(
            UserSession(
                token_hash=token_hash,
                user_id=user_id,
                expires_at=session_expiry(),
                ip=ip[:64],
                user_agent=user_agent[:255],
            )
        )
        await session.commit()
    return token


async def resolve_session(token: str) -> Identity | None:
    """cookie → 身份。过期、停用、用户没了都返回 None。"""
    if not token:
        return None
    token_hash = hash_session_token(token)
    async with async_session_factory() as session:
        row = await session.get(UserSession, token_hash)
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            await session.delete(row)
            await session.commit()
            return None
        user = await session.get(User, row.user_id)
        if user is None or not user.active:
            await session.delete(row)
            await session.commit()
            return None
        # 每五分钟记一次活跃时间:每个请求都写库没必要,但"最后活动"要准到分钟
        last = row.last_seen_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() > 300:
            row.last_seen_at = now
            await session.commit()
        return await identity_of(session, user)


async def end_session(token: str) -> None:
    """登出。删不掉也没关系——cookie 已经由调用方清掉。"""
    if not token:
        return
    async with async_session_factory() as session:
        row = await session.get(UserSession, hash_session_token(token))
        if row is not None:
            await session.delete(row)
            await session.commit()


async def change_own_password(
    user_id: uuid.UUID, current_password: str, new_password: str
) -> bool:
    """改自己的密码。改完把这个人其他会话全删掉——密码变了,旧 cookie 不该还能用。"""
    if len(new_password or "") < 8:
        raise AuthError("新密码至少 8 位")
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None or not user.active:
            return False
        if not verify_password(current_password or "", user.password_hash):
            return False
        user.password_hash = hash_password(new_password)
        await session.execute(
            delete(UserSession).where(UserSession.user_id == user_id)
        )
        await session.commit()
        return True
