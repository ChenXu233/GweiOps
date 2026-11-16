# engine/api/routes/auth.py
"""登录、首启初始化、登出、我是谁。

人用会话 cookie,机器用 X-Gwei-Token:两套凭据井水不犯河水。会话令牌只存在
cookie 里(HttpOnly),库里留的是哈希。

登录回答"我是谁",不回答"我在哪个工作区":一个邮箱可能属于好几个,那是路径里
那一段的事。`GET /api/me` 与 `/api/workspaces/{slug}/me` 把两件事一起答出来。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from engine.auth import SESSION_COOKIE, SESSION_DAYS, Identity
from engine.api.auth import identity_of
from engine.auth import store as auth_store
from engine.db import async_session_factory
from engine.db.models import Membership, Person, Role, Tenant, UserRole

logger = logging.getLogger(__name__)
router = APIRouter()


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


class LoginDTO(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)


class SetupDTO(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=1024)
    display_name: str = Field("", max_length=128)


def _cookie_secure(request: Request) -> bool:
    """走 https 才加 Secure。反代后面靠 X-Forwarded-Proto 判断。"""
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    return (forwarded or request.url.scheme) == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )


def _identity_dto(identity: Identity) -> dict:
    """一条成员关系的形状。`user_id` 是成员关系的 id —— 页面只认得当前工作区。"""
    return {
        "user_id": identity.user_id,
        "person_id": identity.person_id,
        "name": identity.name,
        "tenant": identity.tenant,
        "permissions": sorted(identity.permissions),
        "scoped_permissions": sorted(
            f"{permission}@{scope}"
            for permission, scopes in identity.scoped_permissions.items()
            for scope in scopes
        ),
        "is_sub_user": bool(identity.parent_id),
    }


async def me_dto(person_id: str, workspace: str = "") -> dict[str, Any]:
    """`/api/me` 的形状:我是谁、我在哪几个工作区、每个里面是什么角色。

    同一个人在每个工作区里是两条成员关系、两个 id、两套权限。这份响应把**每个**
    工作区的那份都列出来(界面要画选择器),但顶层那几个字段只对**这次请求落在的**
    那个工作区算数 —— 把几个工作区的权限并起来,是越权的起点。
    """
    async with async_session_factory() as session:
        person = await session.get(Person, uuid.UUID(person_id))
        if person is None:
            raise HTTPException(status_code=404, detail="人不存在")
        persona = await auth_store.persona_of(session, person, workspace or None)

        rows = (
            await session.execute(
                select(Membership)
                .add_columns(Tenant.slug, Tenant.name)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(Membership.person_id == person.id)
                .order_by(Membership.created_at)
            )
        ).all()
        role_rows = (
            await session.execute(
                select(UserRole.user_id, Role.id, Role.key, Role.name)
                .join(Role, Role.id == UserRole.role_id)
                .join(Membership, Membership.user_id == UserRole.user_id)
                .where(Membership.person_id == person.id)
            )
        ).all()

        roles_of: dict[uuid.UUID, list[dict]] = {}
        for membership_id, role_id, key, name in role_rows:
            roles_of.setdefault(membership_id, []).append(
                {"id": str(role_id), "key": key, "name": name}
            )

        items = []
        for membership, slug, tenant_name in rows:
            permissions, scoped = await auth_store.membership_permissions(session, membership)
            items.append(
                {
                    "workspace": slug,
                    "workspace_name": tenant_name,
                    "user_id": str(membership.user_id),
                    "is_sub_user": membership.is_sub_user,
                    "status": membership.status,
                    "roles": roles_of.get(membership.user_id, []),
                    "permissions": sorted(permissions),
                    "scoped_permissions": sorted(
                        f"{permission}@{scope}"
                        for permission, scopes in scoped.items()
                        for scope in scopes
                    ),
                }
            )

    current = persona.identity
    picked = next((item for item in items if current and item["workspace"] == current.tenant), None)
    return {
        "email": person.email,
        "display_name": person.display_name,
        "workspace": (picked or {}).get("workspace", ""),
        "workspace_name": (picked or {}).get("workspace_name", ""),
        "user_id": str(current.user_id) if current else "",
        "person_id": str(person.id),
        "permissions": (picked or {}).get("permissions", []),
        "scoped_permissions": (picked or {}).get("scoped_permissions", []),
        "roles": (picked or {}).get("roles", []),
        "workspaces": items,
        "is_sub_user": bool(current.parent_id) if current else False,
    }


@router.get("/api/auth/status")
async def auth_status(request: Request) -> dict:
    """前端用它决定显示登录页还是首启初始化页。不要求鉴权。"""
    needs_setup = not await auth_store.persons_exist()
    identity: Identity | None = identity_of(request)
    return {
        "needs_setup": needs_setup,
        "authenticated": identity is not None,
        "user": _identity_dto(identity) if identity else None,
    }


@router.post("/api/auth/setup")
async def setup(payload: SetupDTO, request: Request, response: Response) -> dict:
    """第一次跑起来时创建所有者。库里已经有人就直接 409,不留后门。"""
    if await auth_store.persons_exist():
        raise HTTPException(status_code=409, detail="已经有管理员了,请直接登录")

    try:
        identity = await auth_store.bootstrap_first_admin(
            payload.email, payload.password, payload.display_name
        )
    except auth_store.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    token = await auth_store.start_session(
        uuid.UUID(identity.person_id),
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)

    from engine.api.auth import set_auth_required

    set_auth_required(True)
    from engine.auth import audit

    await audit.record("auth.setup", identity=identity, target=payload.email, ip=_ip(request))
    logger.info("bootstrap: first admin created (%s)", payload.email)
    return {"user": _identity_dto(identity)}


@router.post("/api/auth/login")
async def login(payload: LoginDTO, request: Request, response: Response) -> dict:
    found = await auth_store.authenticate(payload.email, payload.password)
    if found is None:
        # 不区分"没这个人"和"密码错"——那种区分是给攻击者的礼物
        raise HTTPException(status_code=401, detail="邮箱或密码不对")
    person, _memberships = found
    token = await auth_store.start_session(
        person.id,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)
    from engine.auth import audit

    # 一封登录信要落到一个工作区上:登录那一刻还没定,落到最早的那条成员关系
    identity = await auth_store.identity_for_person(person.id)
    await audit.record(
        "auth.login", identity=identity, target=person.email, ip=_ip(request)
    )
    return {"user": await me_dto(str(person.id))}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    identity: Identity | None = identity_of(request)
    await auth_store.end_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    if identity is not None:
        from engine.auth import audit

        await audit.record("auth.logout", identity=identity, ip=_ip(request))
    return {"ok": True}


class PasswordDTO(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=8, max_length=1024)


@router.post("/api/auth/password")
async def change_password(
    payload: PasswordDTO, request: Request, response: Response
) -> dict:
    """改自己的密码。要验旧密码;改完把旧会话全踢掉,再发一个新的给当前浏览器。

    改的是**人**的密码:一次改完,他在每个工作区里都是新密码。
    """
    identity: Identity | None = identity_of(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    ok = await auth_store.change_own_password(
        uuid.UUID(identity.person_id), payload.current_password, payload.new_password
    )
    if not ok:
        raise HTTPException(status_code=400, detail="当前密码不对")
    token = await auth_store.start_session(
        uuid.UUID(identity.person_id),
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)
    from engine.auth import audit

    await audit.record("auth.password", identity=identity, ip=_ip(request))
    return {"ok": True, "note": "其他设备上的登录已失效"}


@router.get("/api/auth/me")
async def me(request: Request) -> dict:
    """我是谁。老路径,回答 `/api/me` 的同一个形状(没写工作区段时是最早的那一个)。"""
    identity: Identity | None = identity_of(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    return {"user": await me_dto(identity.person_id, identity.tenant)}


@router.get("/api/me")
async def me_root(request: Request) -> dict:
    """`/api/me`:一个人,以及他在每个工作区里的角色。

    路径不带工作区段时 `workspace` 取他最早的那条成员关系;带了就是那一个。
    """
    identity: Identity | None = identity_of(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    return await me_dto(identity.person_id, identity.tenant)
