# engine/api/routes/auth.py
"""登录、首启初始化、登出、我是谁。

人用会话 cookie,机器用 X-Gwei-Token:两套凭据井水不犯河水。会话令牌只存在
cookie 里(HttpOnly),库里留的是哈希。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from engine.auth import SESSION_COOKIE, SESSION_DAYS, Identity
from engine.auth import store as auth_store

logger = logging.getLogger(__name__)
router = APIRouter()


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
    return {
        "user_id": identity.user_id,
        "name": identity.name,
        "tenant": identity.tenant,
        "permissions": sorted(identity.permissions),
        "is_sub_user": bool(identity.parent_id),
    }


@router.get("/api/auth/status")
async def auth_status(request: Request) -> dict:
    """前端用它决定显示登录页还是首启初始化页。不要求鉴权。"""
    needs_setup = not await auth_store.users_exist()
    identity: Identity | None = getattr(request.state, "identity", None)
    return {
        "needs_setup": needs_setup,
        "authenticated": identity is not None,
        "user": _identity_dto(identity) if identity else None,
    }


@router.post("/api/auth/setup")
async def setup(payload: SetupDTO, request: Request, response: Response) -> dict:
    """第一次跑起来时创建所有者。库里已经有用户就直接 409,不留后门。"""
    if await auth_store.users_exist():
        raise HTTPException(status_code=409, detail="已经有管理员了,请直接登录")

    try:
        identity = await auth_store.bootstrap_first_admin(
            payload.email, payload.password, payload.display_name
        )
    except auth_store.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    token = await auth_store.start_session(
        uuid.UUID(identity.user_id),
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)

    from engine.api.auth import set_auth_required

    set_auth_required(True)
    logger.info("bootstrap: first admin created (%s)", payload.email)
    return {"user": _identity_dto(identity)}


@router.post("/api/auth/login")
async def login(payload: LoginDTO, request: Request, response: Response) -> dict:
    found = await auth_store.authenticate(payload.email, payload.password)
    if found is None:
        # 不区分"没这个人"和"密码错"——那种区分是给攻击者的礼物
        raise HTTPException(status_code=401, detail="邮箱或密码不对")
    user, identity = found
    token = await auth_store.start_session(
        user.id,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)
    return {"user": _identity_dto(identity)}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    await auth_store.end_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


class PasswordDTO(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=8, max_length=1024)


@router.post("/api/auth/password")
async def change_password(
    payload: PasswordDTO, request: Request, response: Response
) -> dict:
    """改自己的密码。要验旧密码;改完把旧会话全踢掉,再发一个新的给当前浏览器。"""
    from engine.auth import store as auth_store

    identity: Identity | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    ok = await auth_store.change_own_password(
        uuid.UUID(identity.user_id), payload.current_password, payload.new_password
    )
    if not ok:
        raise HTTPException(status_code=400, detail="当前密码不对")
    token = await auth_store.start_session(
        uuid.UUID(identity.user_id),
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)
    return {"ok": True, "note": "其他设备上的登录已失效"}


@router.get("/api/auth/me")
async def me(request: Request) -> dict:
    identity: Identity | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="未登录")
    return {"user": _identity_dto(identity)}
