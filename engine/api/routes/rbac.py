# engine/api/routes/rbac.py
"""角色与用户 —— 谁能做什么,以及谁把人拉进来。

权限目录从这里读,前端据此画勾选框;角色是数据,租户自己建。
所有写操作都记审计。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from engine.api.auth import actor_of, require, set_auth_required
from engine.auth import PERMISSIONS, Identity
from engine.auth import admin as admin_store
from engine.auth import audit

router = APIRouter()
logger = logging.getLogger(__name__)


def _identity(request: Request) -> Identity:
    identity: Identity | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    return identity


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


class RoleCreateDTO(BaseModel):
    key: str = Field(..., min_length=2, max_length=63)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=255)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdateDTO(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=255)
    permissions: list[str] | None = None


class UserCreateDTO(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=1024)
    display_name: str = Field("", max_length=128)
    role_ids: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class UserUpdateDTO(BaseModel):
    display_name: str | None = Field(None, max_length=128)
    status: str | None = None
    role_ids: list[str] | None = None
    permissions: list[str] | None = None
    password: str | None = Field(None, min_length=8, max_length=1024)


@router.get("/api/permissions")
async def list_permissions(request: Request) -> dict:
    """权限目录。前端用它画勾选框,一眼看完整个平台的写权限有哪些。"""
    _identity(request)
    return {
        "permissions": [{"key": key, "description": text} for key, text in PERMISSIONS.items()]
    }


@router.get("/api/roles")
async def list_roles(request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.read")
    return {"roles": await admin_store.list_roles(identity)}


@router.post("/api/roles")
async def create_role(payload: RoleCreateDTO, request: Request) -> dict:
    identity = _identity(request)
    require(request, "roles.manage")
    try:
        role = await admin_store.create_role(
            identity,
            key=payload.key,
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
        )
    except admin_store.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record(
        "role.create", identity=identity, target=role["key"], detail={"permissions": role["permissions"]}, ip=_ip(request)
    )
    return {"role": role}


@router.put("/api/roles/{role_id}")
async def update_role(role_id: str, payload: RoleUpdateDTO, request: Request) -> dict:
    identity = _identity(request)
    require(request, "roles.manage")
    try:
        role = await admin_store.update_role(
            identity,
            role_id,
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
        )
    except admin_store.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record(
        "role.update", identity=identity, target=role["key"], detail={"permissions": role.get("permissions")}, ip=_ip(request)
    )
    return {"role": role}


@router.delete("/api/roles/{role_id}")
async def delete_role(role_id: str, request: Request) -> dict:
    identity = _identity(request)
    require(request, "roles.manage")
    try:
        await admin_store.delete_role(identity, role_id)
    except admin_store.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record("role.delete", identity=identity, target=role_id, ip=_ip(request))
    return {"ok": True}


@router.get("/api/users")
async def list_users(request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.read")
    return {"users": await admin_store.list_users(identity)}


@router.post("/api/users")
async def create_user(payload: UserCreateDTO, request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.manage")
    try:
        user = await admin_store.create_user(
            identity,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            role_ids=payload.role_ids,
            permissions=payload.permissions,
        )
    except admin_store.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record(
        "user.create",
        identity=identity,
        target=user["email"],
        detail={"roles": [r["key"] for r in user.get("roles", [])], "sub_user": user["is_sub_user"]},
        ip=_ip(request),
    )
    return {"user": user}


@router.put("/api/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdateDTO, request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.manage")
    try:
        user = await admin_store.update_user(
            identity,
            user_id,
            display_name=payload.display_name,
            status=payload.status,
            role_ids=payload.role_ids,
            permissions=payload.permissions,
            password=payload.password,
        )
    except admin_store.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record("user.update", identity=identity, target=user["email"], ip=_ip(request))
    return {"user": user}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.manage")
    try:
        await admin_store.delete_user(identity, user_id)
    except admin_store.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record("user.delete", identity=identity, target=user_id, ip=_ip(request))
    return {"ok": True}


@router.get("/api/audit")
async def list_audit(request: Request, limit: int = 100) -> dict:
    identity = _identity(request)
    require(request, "audit.read")
    return {"entries": await audit.latest(tenant=identity.tenant, limit=limit)}
