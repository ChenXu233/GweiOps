# engine/auth/admin.py
"""角色与成员的增删改 —— RBAC 里"谁来定义权限"的那一半。

两条红线写在这里,不靠界面提示:

1. **授出去的权限不能超过自己**。owner 建人时可以给全量,其他人只能给
   "自己有效权限"的子集——子账号尤其如此。
2. **不能把自己删掉,也不能把最后一个所有者删掉**:删完之后"谁能管这个租户"
   就没有答案了。

这里改的是**成员关系**:同一句"把人拉进来",在 Acme 里是给这个人加一条成员
关系,不是再建一条密码。人在别的部署里已经存在时,新成员关系直接挂到那一个人身上,
display_name 从人那里借,只有角色是这个工作区单独给的。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import (
    ALL_PERMISSIONS,
    SCOPED_PERMISSIONS,
    Identity,
    hash_password,
    split_scoped,
)
from engine.auth import store as auth_store
from engine.db import async_session_factory
from engine.db.models import Membership, Person, Role, Tenant, UserRole


class AdminError(ValueError):
    """管理操作被规则拒绝。message 直接给人看。"""


async def _tenant_id(session: AsyncSession, slug: str) -> uuid.UUID:
    tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise AdminError(f"租户不存在:{slug}")
    return tenant_id


def _clean_permissions(raw: list[str] | None) -> list[str]:
    """只留看得懂的权限,顺序固定,方便前端比对。

    带范围的写法(`changes.approve@github-acme-api`,或 `changes.approve@acme`)
    也在这里过一遍:权限名得在目录里,收窄必须落在 `SCOPED_PERMISSIONS` 里,范围
    名不能是空串。写错的条目丢掉而不是猜 —— 猜成工作区级会多给。

    范围名是 `projects` 里的 slug,项目与仓库共用一个名字空间,所以这里不区分
    两者:范围指着一个项目时,它下面每一个仓库都算数(含以后新增的)。**这里不查
    库**——slug 是否存在是数据问题,不是权限问题;写个不存在的名字,后果只是
    判定永远不命中,不会多给。
    """
    picked: set[str] = set()
    for entry in raw or []:
        text = str(entry or "").strip()
        permission, sep, scope = text.partition("@")
        if permission not in ALL_PERMISSIONS:
            continue
        if not sep:
            picked.add(permission)
            continue
        if not scope.strip() or permission not in SCOPED_PERMISSIONS:
            continue
        picked.add(f"{permission}@{scope.strip()}")
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
                    .join(Membership, Membership.user_id == UserRole.user_id)
                    .where(Membership.tenant_id == tenant_id)
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
    """这个工作区的成员。一行是一条成员关系,`person_id` 是它挂在哪个人身上。

    同一个人在两个工作区里就是两行、两个 id —— 页面只认得当前工作区,所以
    `id` 是成员关系那个,不是人那个。
    """
    async with async_session_factory() as session:
        tenant_id = await _tenant_id(session, identity.tenant)
        users = (
            await session.execute(
                select(Membership, Person)
                .join(Person, Person.id == Membership.person_id)
                .where(Membership.tenant_id == tenant_id)
                .order_by(Membership.created_at)
            )
        ).all()
        rows = (
            await session.execute(
                select(UserRole.user_id, Role.id, Role.key, Role.name, Role.permissions)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.tenant_id == tenant_id)
            )
        ).all()
        by_user: dict[uuid.UUID, list[dict]] = {}
        extra: dict[uuid.UUID, dict[str, set[str]]] = {}
        for user_id, role_id, key, name, perms in rows:
            by_user.setdefault(user_id, []).append(
                {"id": str(role_id), "key": key, "name": name}
            )
            # 角色里可能带范围的授权(`changes.approve@github-acme-api`),
            # 界面要能把"他在这个仓库上能放行"显示出来,所以按仓库归一次。
            for permission, scopes in split_scoped(perms or [])[1].items():
                extra.setdefault(user_id, {}).setdefault(permission, set()).update(scopes)

        out = []
        for user, person in users:
            out.append(
                {
                    "id": str(user.user_id),
                    "person_id": str(person.id),
                    "email": person.email,
                    "display_name": user.display_name or person.display_name,
                    "status": user.status,
                    "is_sub_user": user.is_sub_user,
                    "permissions": sorted(set(user.permissions or [])),
                    # 这个人额外能管哪几个仓库:{权限: [仓库 slug…]}
                    "scoped_permissions": {
                        permission: sorted(scopes)
                        for permission, scopes in (extra.get(user.user_id) or {}).items()
                    },
                    "roles": by_user.get(user.user_id, []),
                    "created_at": user.created_at.isoformat() if user.created_at else "",
                    "last_login_at": person.last_login_at.isoformat() if person.last_login_at else "",
                }
            )
        return out


async def create_user(
    identity: Identity,
    *,
    email: str,
    password: str = "",
    display_name: str = "",
    role_ids: list[str] | None = None,
    permissions: list[str] | None = None,
) -> dict:
    """把一个人拉进这个工作区。

    三种情况,三种做法,判据只有一条:**这个邮箱在这个部署里是不是已经有一个人**。

    | 邮箱 | 密码 | 做法 |
    | --- | --- | --- |
    | 没有 | 给了 | 建 person + 建成员关系(这就是"新建一个人") |
    | 有,但他不在这里 | 不给 | 只建成员关系 —— 他自己的密码属于他,不归这个工作区改写 |
    | 有,而且已经在这里 | — | 拒绝:同一个工作区里一个人只该有一条成员关系 |

    第二种是最要紧的那条:以前同一句"把人拉进来"会再建一行,连带第二份密码。
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise AdminError("邮箱格式不对")
    if password and len(password) < 8:
        raise AdminError("密码至少 8 位")

    granted = _clean_permissions(permissions)
    if not set(granted) <= set(identity.permissions):
        raise AdminError("不能授出自己没有的权限")

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
                raise AdminError("这个人已经在这个工作区里了")
            if password:
                raise AdminError(
                    "这个邮箱已经有账号了;邀请他进来不用再设密码,密码属于他自己"
                )
        elif not password:
            raise AdminError("新的人要有初始密码")
        elif not person:
            person = Person(
                email=email,
                display_name=(display_name or email.split("@")[0])[:128],
                password_hash=hash_password(password),
                status="active",
            )
            session.add(person)
            await session.flush()

        roles: list[Role] = []
        for rid in role_ids or []:
            role = await session.get(Role, uuid.UUID(rid))
            if role is None or role.tenant_id != tenant_id:
                raise AdminError("角色不存在")
            roles.append(role)
        role_perms = {p for role in roles for p in (role.permissions or [])}
        if not (role_perms | set(granted)) <= set(identity.permissions):
            raise AdminError("不能授出自己没有的权限")

        # 建人的人是租户所有者(权限等于全集)时,新建的是同级成员;
        # 否则就是自己的子成员——子成员的权限上限仍然是父成员。
        is_owner = set(identity.permissions) == set(ALL_PERMISSIONS)
        membership = Membership(
            tenant_id=tenant_id,
            person_id=person.id,
            parent_id=None if is_owner else uuid.UUID(identity.user_id),
            display_name=(display_name or person.display_name or email.split("@")[0])[:128],
            permissions=granted,
            status="active",
        )
        session.add(membership)
        await session.flush()
        for role in roles:
            session.add(UserRole(user_id=membership.user_id, role_id=role.id))
        await session.commit()
        return {
            "id": str(membership.user_id),
            "person_id": str(person.id),
            "email": person.email,
            "display_name": membership.display_name,
            "status": membership.status,
            "is_sub_user": membership.is_sub_user,
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
    """改的是**这条成员关系**:角色、个人追加权限、从属、停用。

    唯一的例外是密码:它属于人,不属于工作区。在这里改密码等于替这个人改了他
    在所有工作区里的登录凭据 —— 所以只允许他自己改(`POST /api/auth/password`),
    这条接口给了密码就直接拒绝,不静默替他改。
    """
    target = uuid.UUID(user_id)
    if password:
        raise AdminError("密码属于这个人,不在工作区里改;让他自己走「改密码」")
    if permissions is not None:
        granted = _clean_permissions(permissions)
        if not set(granted) <= set(identity.permissions):
            raise AdminError("不能授出自己没有的权限")
    else:
        granted = None

    async with async_session_factory() as session:
        user = await session.get(Membership, target)
        tenant_id = await _tenant_id(session, identity.tenant)
        if user is None or user.tenant_id != tenant_id:
            raise AdminError("用户不存在")

        if display_name is not None:
            user.display_name = display_name
        if status is not None:
            if status not in ("active", "disabled"):
                raise AdminError("状态只能是 active 或 disabled")
            if status == "disabled" and str(user.user_id) == identity.user_id:
                raise AdminError("不能停用自己")
            user.status = status
        if granted is not None:
            user.permissions = granted
        if role_ids is not None:
            roles = []
            for rid in role_ids:
                role = await session.get(Role, uuid.UUID(rid))
                if role is None or role.tenant_id != tenant_id:
                    raise AdminError("角色不存在")
                roles.append(role)
            await session.execute(
                UserRole.__table__.delete().where(UserRole.user_id == user.user_id)
            )
            for role in roles:
                session.add(UserRole(user_id=user.user_id, role_id=role.id))
        await session.commit()
        person = await session.get(Person, user.person_id)
        return {
            "id": str(user.user_id),
            "person_id": str(user.person_id),
            "email": person.email if person else "",
            "status": user.status,
        }


async def delete_user(identity: Identity, user_id: str) -> None:
    """把这个人从这个工作区移出去。

    删的是成员关系,不是那个人:他在别的工作区里照样能登录。删完一条成员关系也
    不剩时,人还在(他的密码、联系方式都在),只是没有任何一道门 — 再次被邀请时
    直接认领,不用重新建号。
    """
    target = uuid.UUID(user_id)
    if str(target) == identity.user_id:
        raise AdminError("不能删掉自己")
    async with async_session_factory() as session:
        user = await session.get(Membership, target)
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
                .where(
                    UserRole.user_id == user.user_id, UserRole.role_id == owner_role.id
                )
            )
            if is_owner:
                owners = await session.scalar(
                    select(func.count())
                    .select_from(UserRole)
                    .join(Membership, Membership.user_id == UserRole.user_id)
                    .where(
                        UserRole.role_id == owner_role.id,
                        Membership.tenant_id == tenant_id,
                        Membership.status == "active",
                    )
                )
                if (owners or 0) <= 1:
                    raise AdminError("这是最后一个所有者,删了没人能管这个租户")
        await session.delete(user)
        await session.commit()
