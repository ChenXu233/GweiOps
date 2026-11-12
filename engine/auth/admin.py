# engine/auth/admin.py
"""角色与用户的增删改 —— RBAC 里"谁来定义权限"的那一半。

两条红线写在这里,不靠界面提示:

1. **授出去的权限不能超过自己**。owner 建人时可以给全量,其他人只能给
   "自己有效权限"的子集——子账号尤其如此。
2. **不能把自己删掉,也不能把最后一个所有者删掉**:删完之后"谁能管这个租户"
   就没有答案了。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import ALL_PERMISSIONS, Identity, hash_password
from engine.auth import store as auth_store
from engine.db import async_session_factory
from engine.db.models import Role, Tenant, User, UserRole


class AdminError(ValueError):
    """管理操作被规则拒绝。message 直接给人看。"""


async def _tenant_id(session: AsyncSession, slug: str) -> uuid.UUID:
    tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise AdminError(f"租户不存在:{slug}")
    return tenant_id


def _clean_permissions(raw: list[str] | None) -> list[str]:
    """只留看得懂的权限,顺序固定,方便前端比对。"""
    picked = {p for p in (raw or []) if p in ALL_PERMISSIONS}
    return sorted(picked)


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------


async def list_roles(identity: Identity) -> list[dict]:
    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        roles = list(
            (
                await session.execute(
                    select(Role).where(Role.tenant_id == tenant_id).order_by(Role.created_at)
                )
            )
            .scalars()
            .all()
        )
        counts = dict(
            (
                await session.execute(
                    select(UserRole.role_id, func.count())
                    .join(User, User.id == UserRole.user_id)
                    .where(User.tenant_id == tenant_id)
                    .group_by(UserRole.role_id)
                )
            ).all()
        )
        return [
            {
                "id": str(role.id),
                "key": role.key,
                "name": role.name,
                "description": role.description,
                "permissions": list(role.permissions or []),
                "is_system": role.is_system,
                "user_count": int(counts.get(role.id, 0)),
            }
            for role in roles
        ]


async def create_role(
    identity: Identity, *, key: str, name: str, description: str, permissions: list[str]
) -> dict:
    key = (key or "").strip().lower()
    if not key or not key.replace("-", "").replace("_", "").isalnum():
        raise AdminError("角色 key 只能用小写字母、数字、- 和 _")
    if not (name or "").strip():
        raise AdminError("角色要有名字")

    granted = _clean_permissions(permissions)
    # 授出去的不能超过自己有的
    if not set(granted) <= set(identity.permissions):
        raise AdminError("不能授出自己没有的权限")

    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        exists = await session.scalar(
            select(Role.id).where(Role.tenant_id == tenant_id, Role.key == key)
        )
        if exists:
            raise AdminError(f"角色 key 已存在:{key}")
        role = Role(
            tenant_id=tenant_id,
            key=key,
            name=name.strip(),
            description=description or "",
            permissions=granted,
            is_system=False,
        )
        session.add(role)
        await session.commit()
        return {
            "id": str(role.id),
            "key": role.key,
            "name": role.name,
            "description": role.description,
            "permissions": list(role.permissions),
            "is_system": False,
            "user_count": 0,
        }


async def update_role(
    identity: Identity,
    role_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    permissions: list[str] | None = None,
) -> dict:
    if permissions is not None and not set(_clean_permissions(permissions)) <= set(
        identity.permissions
    ):
        raise AdminError("不能授出自己没有的权限")

    async with async_session_factory() as session:
        role = await session.get(Role, uuid.UUID(role_id))
        if role is None or await _tenant_id(session, identity.tenant) != role.tenant_id:
            raise AdminError("角色不存在")
        if name is not None:
            if not name.strip():
                raise AdminError("角色要有名字")
            role.name = name.strip()
        if description is not None:
            role.description = description
        if permissions is not None:
            role.permissions = _clean_permissions(permissions)
        await session.commit()
        return {
            "id": str(role.id),
            "key": role.key,
            "name": role.name,
            "description": role.description,
            "permissions": list(role.permissions),
            "is_system": role.is_system,
        }


async def delete_role(identity: Identity, role_id: str) -> None:
    async with async_session_factory() as session:
        role = await session.get(Role, uuid.UUID(role_id))
        if role is None or await _tenant_id(session, identity.tenant) != role.tenant_id:
            raise AdminError("角色不存在")
        if role.is_system:
            raise AdminError("预设角色不能删;不想用它就把权限清空")
        used = await session.scalar(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
        )
        if used:
            raise AdminError(f"还有 {used} 个人在用这个角色,先把他们换掉")
        await session.delete(role)
        await session.commit()


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------


async def list_users(identity: Identity) -> list[dict]:
    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        users = list(
            (
                await session.execute(
                    select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
                )
            )
            .scalars()
            .all()
        )
        rows = (
            await session.execute(
                select(UserRole.user_id, Role.id, Role.key, Role.name, Role.permissions)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.tenant_id == tenant_id)
            )
        ).all()
        by_user: dict[uuid.UUID, list[dict]] = {}
        extra: dict[uuid.UUID, set[str]] = {}
        for user_id, role_id, key, name, perms in rows:
            by_user.setdefault(user_id, []).append(
                {"id": str(role_id), "key": key, "name": name}
            )
            extra.setdefault(user_id, set()).update(perms or [])

        out = []
        for user in users:
            out.append(
                {
                    "id": str(user.id),
                    "email": user.email,
                    "display_name": user.display_name,
                    "status": user.status,
                    "is_sub_user": user.is_sub_user,
                    "permissions": sorted(set(user.permissions or [])),
                    "roles": by_user.get(user.id, []),
                    "created_at": user.created_at.isoformat() if user.created_at else "",
                    "last_login_at": user.last_login_at.isoformat() if user.last_login_at else "",
                }
            )
        return out


async def create_user(
    identity: Identity,
    *,
    email: str,
    password: str,
    display_name: str = "",
    role_ids: list[str] | None = None,
    permissions: list[str] | None = None,
) -> dict:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AdminError("邮箱格式不对")
    if len(password or "") < 8:
        raise AdminError("密码至少 8 位")

    granted = _clean_permissions(permissions)
    if not set(granted) <= set(identity.permissions):
        raise AdminError("不能授出自己没有的权限")

    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        if await session.scalar(
            select(User.id).where(User.tenant_id == tenant_id, User.email == email)
        ):
            raise AdminError("这个邮箱已经有人用了")

        roles: list[Role] = []
        for rid in role_ids or []:
            role = await session.get(Role, uuid.UUID(rid))
            if role is None or role.tenant_id != tenant_id:
                raise AdminError("角色不存在")
            roles.append(role)
        role_perms = {p for role in roles for p in (role.permissions or [])}
        if not (role_perms | set(granted)) <= set(identity.permissions):
            raise AdminError("不能授出自己没有的权限")

        # 建人的人是租户所有者(权限等于全集)时,新建的是同级用户;
        # 否则就是自己的子账号——子账号的权限上限仍然是父用户。
        is_owner = set(identity.permissions) == set(ALL_PERMISSIONS)
        user = User(
            tenant_id=tenant_id,
            parent_id=None if is_owner else uuid.UUID(identity.user_id),
            email=email,
            display_name=display_name or email.split("@")[0],
            password_hash=hash_password(password),
            permissions=granted,
            status="active",
        )
        session.add(user)
        await session.flush()
        for role in roles:
            session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.commit()
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
            "is_sub_user": user.is_sub_user,
            "roles": [{"id": str(r.id), "key": r.key, "name": r.name} for r in roles],
            "permissions": granted,
        }


async def update_user(
    identity: Identity,
    user_id: str,
    *,
    display_name: str | None = None,
    status: str | None = None,
    role_ids: list[str] | None = None,
    permissions: list[str] | None = None,
    password: str | None = None,
) -> dict:
    target = uuid.UUID(user_id)
    if permissions is not None:
        granted = _clean_permissions(permissions)
        if not set(granted) <= set(identity.permissions):
            raise AdminError("不能授出自己没有的权限")
    else:
        granted = None

    async with async_session_factory() as session:
        user = await session.get(User, target)
        tenant_id = await _tenant_id(session, identity.tenant)
        if user is None or user.tenant_id != tenant_id:
            raise AdminError("用户不存在")

        if display_name is not None:
            user.display_name = display_name
        if status is not None:
            if status not in ("active", "disabled"):
                raise AdminError("状态只能是 active 或 disabled")
            if status == "disabled" and str(user.id) == identity.user_id:
                raise AdminError("不能停用自己")
            user.status = status
        if granted is not None:
            user.permissions = granted
        if password:
            if len(password) < 8:
                raise AdminError("密码至少 8 位")
            user.password_hash = hash_password(password)
        if role_ids is not None:
            roles = []
            for rid in role_ids:
                role = await session.get(Role, uuid.UUID(rid))
                if role is None or role.tenant_id != tenant_id:
                    raise AdminError("角色不存在")
                roles.append(role)
            await session.execute(
                UserRole.__table__.delete().where(UserRole.user_id == user.id)
            )
            for role in roles:
                session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.commit()
        return {"id": str(user.id), "email": user.email, "status": user.status}


async def delete_user(identity: Identity, user_id: str) -> None:
    target = uuid.UUID(user_id)
    if str(target) == identity.user_id:
        raise AdminError("不能删掉自己")
    async with async_session_factory() as session:
        user = await session.get(User, target)
        tenant_id = await _tenant_id(session, identity.tenant)
        if user is None or user.tenant_id != tenant_id:
            raise AdminError("用户不存在")
        # 删掉的如果是最后一个所有者,这个租户就没人管了
        owner_role = await session.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.key == "owner")
        )
        if owner_role is not None:
            is_owner = await session.scalar(
                select(func.count())
                .select_from(UserRole)
                .where(UserRole.user_id == user.id, UserRole.role_id == owner_role.id)
            )
            if is_owner:
                owners = await session.scalar(
                    select(func.count())
                    .select_from(UserRole)
                    .join(User, User.id == UserRole.user_id)
                    .where(
                        UserRole.role_id == owner_role.id,
                        User.tenant_id == tenant_id,
                        User.status == "active",
                    )
                )
                if (owners or 0) <= 1:
                    raise AdminError("这是最后一个所有者,删了没人能管这个租户")
        await session.delete(user)
        await session.commit()
