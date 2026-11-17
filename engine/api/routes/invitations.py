"""邀请的接口 —— 管理员发,被邀请人接。

发、看、撤要走当前工作区(`/api/workspaces/{slug}/invitations`);接不用 ——
链接里那枚令牌就是凭据,被邀请的人那时还没有账号,不该为了接一条邀请先有权限。

于是接的两条口在 `/api/invitations/{token}` 上:它们和 `/api/auth/*` 一样
不走鉴权中间件。令牌只存哈希,一次有效,状态各自说清。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from engine.api.auth import by_of, identity_of, require, set_auth_required
from engine.auth import Identity, audit
from engine.auth import invitations as invite_store

router = APIRouter()
logger = logging.getLogger(__name__)


def _identity(request: Request) -> Identity:
    identity: Identity | None = identity_of(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    return identity


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


class InviteCreateDTO(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role_ids: list[str] = Field(default_factory=list)


class InviteAcceptDTO(BaseModel):
    """接邀请时他要设的密码。这个邮箱已经有人时不需要 —— 给了也不改他的。"""

    password: str = Field("", max_length=1024)
    display_name: str = Field("", max_length=128)


@router.get("/api/invitations")
async def list_invitations(request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.read")
    return {"items": await invite_store.list_invitations(identity)}


@router.post("/api/invitations")
async def create_invitation(payload: InviteCreateDTO, request: Request) -> dict:
    """发一条邀请。响应里的 `token` 只出现这一次 —— 拼成链接交给被邀请人。"""
    identity = _identity(request)
    require(request, "users.manage")
    try:
        invite, token = await invite_store.create_invitation(
            identity, email=payload.email, role_ids=payload.role_ids
        )
    except invite_store.InviteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record(
        "invite.create",
        identity=identity,
        target=payload.email,
        detail={"roles": invite["role_ids"], "expires_at": invite["expires_at"]},
        ip=_ip(request),
    )
    return {"invitation": invite, "token": token}


@router.delete("/api/invitations/{invite_id}")
async def revoke_invitation(invite_id: str, request: Request) -> dict:
    identity = _identity(request)
    require(request, "users.manage")
    try:
        invite = await invite_store.revoke_invitation(identity, invite_id)
    except invite_store.InviteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await audit.record(
        "invite.revoke", identity=identity, target=invite["email"], ip=_ip(request)
    )
    return {"invitation": invite}


@router.get("/api/invitations/{token}")
async def preview_invitation(token: str) -> dict:
    """这条链接现在什么情况。不要求登录:链接本身就是凭据。

    过期、用过、撤销过都正常返回状态,由页面给下一步 —— 404 只会让被邀请人
    以为链接坏了。
    """
    try:
        return await invite_store.preview(token)
    except invite_store.InviteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/api/invitations/{token}")
async def accept_invitation(
    token: str, payload: InviteAcceptDTO, request: Request, response: Response
) -> dict:
    """接邀请。成功之后这个人就已经登录了 —— 顺手发一个会话,少一步。"""
    try:
        person, identity = await invite_store.accept(
            token, password=payload.password, display_name=payload.display_name
        )
    except invite_store.InviteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    from engine.api.routes.auth import _set_session_cookie, me_dto
    from engine.auth import store as auth_store

    value = await auth_store.start_session(
        person.id,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    # 首启之后才翻这个开关;接邀请建出的是第一个人时也要翻,
    # 否则这个部署在自助注册看来仍然"不鉴权"。
    set_auth_required(True)
    _set_session_cookie(response, request, value)
    await audit.record("invite.accept", identity=identity, target=person.email, ip=_ip(request))
    return {"user": await me_dto(str(person.id), identity.tenant)}


__all__ = ["router"]
