"""邀请 —— 发一条、接一条、撤一条。

这条路和 `admin.create_user` 的分工只有一句话:**谁定密码**。

| 谁定密码 | 走哪条 |
| --- | --- |
| 管理员替他想一个,带外告诉他 | `POST /api/users`(临时密码,进来就该改) |
| 他自己定 | 邀请:发链接,他点开、设密码、成为这个工作区的人 |

接的时候认的是**被邀请的邮箱**,不是链接发给谁:

- 这个邮箱在部署里已经有这个人 —— 认领他。只加一条成员关系,他自己的密码
  一个字都不动。这就是"同一份凭据,多道门"落地的地方
- 还没有 —— 他现场设一次密码,那一刻才建这个人

几条不做会出事的事:

- **令牌只存哈希**。库被看到也换不出能用的链接。
- **只能用一次**。用过之后 `accepted_at` 留着,再点得到"已经用过了"。
- **过期说清楚**。过期与用过是两条不同的下一步,不能都回一个 404。
- 已经在这个工作区里的人不发邀请:发了他也接不了,那是给两边都添一件事。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import ALL_PERMISSIONS, Identity, hash_password
from engine.auth import admin as admin_store
from engine.auth.registration import new_link_token
from engine.db import async_session_factory
from engine.db.models import Invitation, Membership, Person, Role, Tenant, UserRole

logger = logging.getLogger(__name__)

INVITE_SCOPE = "invitation"
INVITE_TTL_DAYS = 7

STATE_TEXT = {
    "accepted": "这条邀请已经用过了",
    "revoked": "这条邀请已被撤销",
    "expired": "这条邀请过期了,让管理员重新发一条",
}


class InviteError(ValueError):
    """邀请走不下去。message 直接给人看。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _state(invite: Invitation, now: datetime | None = None) -> str:
    now = now or _now()
    if invite.accepted_at is not None:
        return "accepted"
    if invite.revoked_at is not None:
        return "revoked"
    expires = _aware(invite.expires_at) or now
    return "pending" if expires > now else "expired"


def _dto(invite: Invitation, *, workspace: str = "") -> dict:
    state = _state(invite)
    return {
        "id": str(invite.id),
        "email": invite.email,
        "workspace": workspace,
        "state": state,
        "role_ids": [str(r) for r in (invite.role_ids or [])],
        "permissions": sorted(invite.permissions or []),
        "expires_at": (_aware(invite.expires_at) or _now()).isoformat(),
        "created_at": (_aware(invite.created_at) or _now()).isoformat(),
        "accepted_at": (_aware(invite.accepted_at) or "").isoformat() if invite.accepted_at else "",
        "note": STATE_TEXT.get(state, ""),
    }


async def _tenant_id(session: AsyncSession, slug: str) -> uuid.UUID:
    tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise InviteError(f"租户不存在:{slug}")
    return tenant_id


async def _tenant_slug(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    return await session.scalar(select(Tenant.slug).where(Tenant.id == tenant_id)) or ""


# ---------------------------------------------------------------------------
# 发
# ---------------------------------------------------------------------------


async def create_invitation(
    identity: Identity,
    *,
    email: str,
    role_ids: list[str] | None = None,
) -> tuple[dict, str]:
    """发一条邀请。返回 (邀请, 明文令牌) —— 明文只出现这一次。

    能授出去的仍然不能超过自己:这条红线和建用户时是同一条,判据在
    `admin_store` 里,这里只把结果拿来用。
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise InviteError("邮箱格式不对")

    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        person = await session.scalar(select(Person).where(Person.email == email))
        if person is not None:
            already = await session.scalar(
                select(Membership.user_id).where(
                    Membership.tenant_id == tenant_id, Membership.person_id == person.id
                )
            )
            if already:
                raise InviteError("这个人已经在这个工作区里了,不用再邀请")

        roles: list[Role] = []
        for rid in role_ids or []:
            role = await session.get(Role, uuid.UUID(rid))
            if role is None or role.tenant_id != tenant_id:
                raise InviteError("角色不存在")
            roles.append(role)
        role_perms = {p for role in roles for p in (role.permissions or [])}
        if not role_perms <= set(identity.permissions):
            raise InviteError("不能授出自己没有的权限")

        # 同一个邮箱在这个工作区里只留一条还没接的:再发一条,前一条就该失效,
        # 不然同时有效的邀请越多,撞上来的机会越多(和验证码是同一个道理)。
        for stale in (
            await session.execute(
                select(Invitation).where(
                    Invitation.tenant_id == tenant_id,
                    Invitation.email == email,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                )
            )
        ).scalars():
            stale.revoked_at = _now()

        token, token_hash = new_link_token()
        # 所有者发的人是同级;别人发的挂在自己下面 —— 与 `admin.create_user` 同一条规
        is_owner = set(identity.permissions) == set(ALL_PERMISSIONS)
        # 发邀请的是这个工作区里的一条成员关系。构造出来的身份(测试、迁移)可能
        # 没有那一行:那就不记"谁发的",但新成员仍然按权限挂在正确的位置上。
        inviter = uuid.UUID(identity.user_id) if identity.user_id else None
        if inviter is not None and await session.get(Membership, inviter) is None:
            inviter = None
        invite = Invitation(
            tenant_id=tenant_id,
            email=email,
            invited_by=inviter,
            parent_id=None if (is_owner or inviter is None) else inviter,
            role_ids=[str(role.id) for role in roles],
            permissions=[],
            token_hash=token_hash,
            expires_at=_now() + timedelta(days=INVITE_TTL_DAYS),
        )
        session.add(invite)
        await session.commit()
        return _dto(invite, workspace=identity.tenant), token


async def list_invitations(identity: Identity) -> list[dict]:
    """这个工作区发出去的邀请。用过的、撤销的、过期的一起列,状态各自说清。"""
    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        rows = (
            await session.execute(
                select(Invitation)
                .where(Invitation.tenant_id == tenant_id)
                .order_by(Invitation.created_at.desc())
            )
        ).scalars()
        return [_dto(row, workspace=identity.tenant) for row in rows]


async def revoke_invitation(identity: Identity, invite_id: str) -> dict:
    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        invite = await session.get(Invitation, uuid.UUID(invite_id))
        if invite is None or invite.tenant_id != tenant_id:
            raise InviteError("没有这条邀请")
        state = _state(invite)
        if state != "pending":
            raise InviteError(STATE_TEXT[state])
        invite.revoked_at = _now()
        await session.commit()
        return _dto(invite, workspace=identity.tenant)


# ---------------------------------------------------------------------------
# 看(不需要登录:链接里那枚令牌就是凭据)
# ---------------------------------------------------------------------------


async def preview(token: str) -> dict:
    """链接里那枚令牌 → 这条邀请现在什么情况。不要求登录。

    过期、用过、撤销过都**正常返回**一个状态,由界面给出下一步 —— 回 404 的话,
    被邀请人只会看到"没了",不知道是该让人重发还是自己点错了链接。
    """
    async with async_session_factory() as session:
        invite = await _by_token(session, token)
        if invite is None:
            raise InviteError("这条邀请链接认不出来")
        slug = await _tenant_slug(session, invite.tenant_id)
        tenant_name = await session.scalar(
            select(Tenant.name).where(Tenant.id == invite.tenant_id)
        ) or slug
        state = _state(invite)
        person = await session.scalar(select(Person).where(Person.email == invite.email))
        roles: list[dict] = []
        for rid in invite.role_ids or []:
            role = await session.get(Role, uuid.UUID(str(rid)))
            if role is not None:
                roles.append({"id": str(role.id), "key": role.key, "name": role.name})
        return {
            "email": invite.email,
            "workspace": slug,
            "workspace_name": tenant_name,
            "state": state,
            "note": STATE_TEXT.get(state, ""),
            "roles": roles,
            "expires_at": (_aware(invite.expires_at) or _now()).isoformat(),
            # 这个邮箱已经有账号了:他不用再设密码,登录一次就能接。
            # 这一点要在页面上说出来,不然他会在"设密码"那里卡住。
            "existing_account": person is not None and bool(person.password_hash),
        }


async def _by_token(session: AsyncSession, token: str) -> Invitation | None:
    from engine.auth import hash_session_token

    if not token:
        return None
    return await session.scalar(
        select(Invitation).where(Invitation.token_hash == hash_session_token(token))
    )


# ---------------------------------------------------------------------------
# 接
# ---------------------------------------------------------------------------


async def accept(token: str, *, password: str = "", display_name: str = "") -> tuple[Person, Identity]:
    """接一条邀请。返回 (人, 他在这个工作区里的身份)。

    三条路,判据只有一条:**这个邮箱在部署里是不是已经有人**。

    | 情形 | 做法 |
    | --- | --- |
    | 认识这个人 | 认领:只加成员关系,他的密码不动。给了密码也按"不改"处理,不静默改别人的登录凭据 |
    | 不认识 | 用他设的密码建这个人,同一刻加成员关系 |
    | 已经在这个工作区里 | 拒绝,并说清他直接登录就行 |
    """
    async with async_session_factory() as session:
        invite = await _by_token(session, token)
        if invite is None:
            raise InviteError("这条邀请链接认不出来")
        state = _state(invite)
        if state != "pending":
            raise InviteError(STATE_TEXT[state])

        tenant_id = invite.tenant_id
        person = await session.scalar(select(Person).where(Person.email == invite.email))
        claimed = person is not None
        if person is not None:
            already = await session.scalar(
                select(Membership.user_id).where(
                    Membership.tenant_id == tenant_id, Membership.person_id == person.id
                )
            )
            if already:
                raise InviteError("你已经是这个工作区的成员了,直接登录就行")
            if not person.active:
                raise InviteError("这个账号已经停用,让管理员处理一下")
        else:
            if len(password or "") < 8:
                raise InviteError("密码至少 8 位")
            person = Person(
                email=invite.email,
                display_name=(display_name or invite.email.split("@")[0])[:128],
                password_hash=hash_password(password),
                status="active",
            )
            session.add(person)
            await session.flush()

        roles: list[Role] = []
        for rid in invite.role_ids or []:
            role = await session.get(Role, uuid.UUID(str(rid)))
            if role is not None and role.tenant_id == tenant_id:
                roles.append(role)

        # 权限在发邀请那一刻定死:接的人没有改动余地。个人追加那一栏留空 ——
        # 要额外给什么,是由管理员在成员页上再改一次的事。
        membership = Membership(
            tenant_id=tenant_id,
            person_id=person.id,
            parent_id=invite.parent_id,
            display_name=(display_name or person.display_name or invite.email.split("@")[0])[:128],
            permissions=[],
            status="active",
        )
        session.add(membership)
        await session.flush()
        for role in roles:
            session.add(UserRole(user_id=membership.user_id, role_id=role.id))
        invite.accepted_at = _now()
        await session.commit()

        from engine.auth import store as auth_store

        identity = await auth_store.identity_of(session, membership, person)
        logger.info(
            "invite accepted: %s → %s（%s）",
            invite.email,
            identity.tenant,
            "认领已有的人" if claimed else "新建的人",
        )
        return person, identity


__all__ = [
    "INVITE_TTL_DAYS",
    "InviteError",
    "accept",
    "create_invitation",
    "list_invitations",
    "preview",
    "revoke_invitation",
]
