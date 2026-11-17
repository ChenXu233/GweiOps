# engine/auth/store.py
"""人与成员关系的读写 —— 鉴权要用的那部分,不掺业务。

分两层:上面是"怎么算出一个人的权限",下面是对库的增删改。
中间件每个请求都要解析一次会话,所以这里只做必要的事,不做 N+1。

两件事在这里分开:**人**(`persons`)有凭据,**成员关系**(`memberships`)有角色。
一次登录回答"我是谁";一次请求回答"我这次在哪个工作区里、在那里能做什么"。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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
from engine.db.models import Membership, Person, Role, Tenant, UserRole, UserSession

DEFAULT_TENANT_SLUG = "default"


class AuthError(ValueError):
    """鉴权失败。message 是给人看的,不要带内部细节。"""


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------


async def tenant_slug_of(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    slug = await session.scalar(select(Tenant.slug).where(Tenant.id == tenant_id))
    return slug or ""


async def _role_permissions(session: AsyncSession, user_id: uuid.UUID) -> list[list[str]]:
    # 注意取的是**标量**列:`rows.all()` 给的是 Row 对象,`list(Row)` 得到的是
    # [权限列表] 而不是权限字符串,权限会被静默吃空。这条判据在
    # `tests/test_integration/test_rbac_admin.py` 里有用例盯着。
    rows = (
        await session.execute(
            select(Role.permissions).join(UserRole, UserRole.role_id == Role.id).where(
                UserRole.user_id == user_id
            )
        )
    ).scalars()
    return [list(r or []) for r in rows]


async def membership_permissions(
    session: AsyncSession, membership: Membership
) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """一条成员关系的有效权限:个人追加 + 角色,有父成员时再与父取交集。

    父被停用或缺席时子成员清零 —— "父没了,子成员不该继续拿着权限"这条只在
    判定时成立才叫判据。
    """
    own_roles = await _role_permissions(session, membership.user_id)
    permissions, scoped = effective_permissions(membership.permissions, own_roles)

    if membership.parent_id:
        parent = await session.get(Membership, membership.parent_id)
        if parent is None or not parent.active:
            return frozenset(), {}
        parent_roles = await _role_permissions(session, parent.user_id)
        parent_perms, parent_scoped = effective_permissions(parent.permissions, parent_roles)
        permissions, scoped = effective_permissions(
            membership.permissions,
            own_roles,
            parent=parent_perms,
            parent_scoped=parent_scoped,
        )
    return permissions, scoped


async def identity_of(
    session: AsyncSession, membership: Membership, person: Person | None = None
) -> Identity:
    """一条成员关系 + 那个人 → 一次请求的身份。

    返回里有两份权限:工作区级的那份处处算数;带范围的那份只对点名的仓库算数
    (写法 `changes.approve@github-acme-api`,见 engine/auth/__init__.py)。
    """
    if person is None:
        person = await session.get(Person, membership.person_id)
    permissions, scoped = await membership_permissions(session, membership)
    name = (
        membership.display_name
        or (person.display_name if person else "")
        or (person.email if person else "")
    )
    return Identity(
        user_id=str(membership.user_id),
        name=name,
        tenant=await tenant_slug_of(session, membership.tenant_id),
        permissions=permissions,
        scoped_permissions=scoped,
        parent_id=str(membership.parent_id or ""),
        person_id=str(membership.person_id),
        person_email=person.email if person else "",
        membership_id=str(membership.user_id),
    )


@dataclass(frozen=True)
class Persona:
    """"这个人是谁",还没定他这次落在哪个工作区。"""

    person: Person
    memberships: tuple[Membership, ...]
    identity: Identity | None

    @property
    def person_id(self) -> uuid.UUID:
        return self.person.id


def empty_identity(person: Person) -> Identity:
    """能登录但一条成员关系都没有:空权限,403 且说得出原因。"""
    return Identity(
        user_id="",
        name=person.display_name or person.email,
        tenant="",
        permissions=frozenset(),
        person_id=str(person.id),
        person_email=person.email,
    )


async def persona_of(
    session: AsyncSession, person: Person, workspace: str | None = None
) -> Persona:
    """人在这个部署里的全部家当,以及这次请求落在哪一个工作区。

    `workspace` 是工作区 slug(路径里的那一段)。为空时取最早的那条成员关系 ——
    只属于一个工作区的人因此不用每条链接都带工作区段。
    """
    rows = (
        await session.execute(
            select(Membership)
            .where(Membership.person_id == person.id, Membership.status != "disabled")
            .order_by(Membership.created_at)
        )
    ).scalars()
    memberships = tuple(rows)
    picked: Membership | None = None
    if workspace:
        wanted = await session.scalar(select(Tenant.id).where(Tenant.slug == workspace))
        if wanted is not None:
            picked = next((m for m in memberships if m.tenant_id == wanted), None)
    elif memberships:
        picked = memberships[0]
    identity = await identity_of(session, picked, person) if picked is not None else None
    return Persona(person=person, memberships=memberships, identity=identity)


async def identity_for_person(
    person_id: uuid.UUID, workspace: str | None = None
) -> Identity | None:
    """会话 → 身份。找不到成员关系时返回 None(调用方给空身份)。"""
    async with async_session_factory() as session:
        person = await session.get(Person, person_id)
        if person is None or not person.active:
            return None
        persona = await persona_of(session, person, workspace)
        return persona.identity


async def persons_exist() -> bool:
    async with async_session_factory() as session:
        return bool(await session.scalar(select(func.count()).select_from(Person)))


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
    """建租户、预设角色、第一个所有者。库里已经有人时拒绝。"""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AuthError("邮箱格式不对")
    if len(password or "") < 8:
        raise AuthError("密码至少 8 位")

    async with async_session_factory() as session:
        if await session.scalar(select(func.count()).select_from(Person)):
            raise AuthError("已经有用户了,不能再初始化")

        tenant = await session.scalar(select(Tenant).where(Tenant.slug == DEFAULT_TENANT_SLUG))
        if tenant is None:
            tenant = Tenant(slug=DEFAULT_TENANT_SLUG, name="默认租户", settings={})
            session.add(tenant)
            await session.flush()

        roles = await ensure_default_roles(session, tenant.id)
        person = Person(
            email=email,
            display_name=display_name or email.split("@")[0],
            password_hash=hash_password(password),
            status="active",
        )
        session.add(person)
        await session.flush()
        membership = Membership(
            tenant_id=tenant.id,
            person_id=person.id,
            display_name=person.display_name,
            permissions=[],
            status="active",
        )
        session.add(membership)
        await session.flush()
        session.add(UserRole(user_id=membership.user_id, role_id=roles["owner"].id))
        await session.commit()
        await session.refresh(membership)
        return await identity_of(session, membership, person)


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------


async def authenticate(email: str, password: str) -> tuple[Person, tuple[Membership, ...]] | None:
    """邮箱 + 密码。错了就是错了,不区分"没这个人"和"密码不对"。

    登录之后还没定工作区:同一个邮箱可能属于好几个,那是下一条请求的事
    (`resolve_session` 按路径里的工作区段定)。
    """
    email = (email or "").strip().lower()
    async with async_session_factory() as session:
        person = await session.scalar(select(Person).where(Person.email == email))
        if person is None or not person.active:
            return None
        if not verify_password(password or "", person.password_hash):
            return None
        person.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        memberships = tuple(
            (
                await session.execute(
                    select(Membership)
                    .where(
                        Membership.person_id == person.id,
                        Membership.status != "disabled",
                    )
                    .order_by(Membership.created_at)
                )
            ).scalars()
        )
        return person, memberships


async def start_session(
    person_id: uuid.UUID, *, ip: str = "", user_agent: str = ""
) -> str:
    """发一个新会话令牌。返回明文,调用方塞进 cookie,库里只有哈希。

    会话挂在**人**上:一次登录之后能进几个工作区,是有几条成员关系的事。
    """
    token, token_hash = new_session_token()
    async with async_session_factory() as session:
        session.add(
            UserSession(
                token_hash=token_hash,
                person_id=person_id,
                expires_at=session_expiry(),
                ip=ip[:64],
                user_agent=user_agent[:255],
            )
        )
        await session.commit()
    return token


async def resolve_session(token: str, workspace: str | None = None) -> Identity | None:
    """cookie → 身份。过期、停用、人没了、没有成员关系都返回 None。

    `workspace` 是这次请求的工作区 slug。给一个他不属于的工作区,同样是 None:
    后端不替他"落回他有权限的那一个",那会把 403 变成一个静默的换位。
    """
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
        person = await session.get(Person, row.person_id)
        if person is None or not person.active:
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
        persona = await persona_of(session, person, workspace)
        if persona.identity is None:
            return empty_identity(person) if not workspace else None
        return persona.identity


async def resolve_persona(token: str, workspace: str | None = None) -> Persona | None:
    """cookie → 人 + 他的全部成员关系 + 这次落在哪一个。`/api/me` 用它。"""
    if not token:
        return None
    token_hash = hash_session_token(token)
    async with async_session_factory() as session:
        row = await session.get(UserSession, token_hash)
        if row is None:
            return None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return None
        person = await session.get(Person, row.person_id)
        if person is None or not person.active:
            return None
        return await persona_of(session, person, workspace)


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
    person_id: uuid.UUID, current_password: str, new_password: str
) -> bool:
    """改自己的密码。改完把这个人其他会话全删掉——密码变了,旧 cookie 不该还能用。

    人只有一份密码:改一次,他在每个工作区里都是新密码。这就是拆表要买到的东西。
    """
    if len(new_password or "") < 8:
        raise AuthError("新密码至少 8 位")
    async with async_session_factory() as session:
        person = await session.get(Person, person_id)
        if person is None or not person.active:
            return False
        if not verify_password(current_password or "", person.password_hash):
            return False
        person.password_hash = hash_password(new_password)
        await session.execute(
            delete(UserSession).where(UserSession.person_id == person_id)
        )
        await session.commit()
        return True
