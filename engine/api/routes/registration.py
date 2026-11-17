# engine/api/routes/registration.py
"""注册、核验、找回密码、OIDC 登录 —— 陌生人能走的那几个入口。

和 [auth.py](auth.py) 分开:那边是"已经有账号的人怎么进来",这边是"怎么成为账号"。
两件事的失败口径不一样 —— 登录失败不能透露账号存不存在,注册失败必须说清
是邮箱被占了还是码不对,否则人没法继续。

所有写操作都记审计。开关与能用的方式由 `GET /api/auth/registration/policy` 说清,
前端照它画按钮,不靠猜。
"""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from engine.api.auth import workspace_access
from engine.api.routes.auth import _cookie_secure, _set_session_cookie, me_dto
from engine.auth import SESSION_COOKIE
from engine.auth import audit
from engine.auth import oidc as oidc_client
from engine.auth import registration as policy_mod
from engine.auth import registration_store as reg
from engine.auth import store as auth_store
from engine.auth.channels import ChannelError, deliver_email, deliver_sms
from engine.shared.config import config

router = APIRouter()
logger = logging.getLogger(__name__)

# OIDC 的一次性状态。state → (verifier, nonce, 过期时间)。
# 放进程内存:一次登录几十秒,重启丢掉重来一次即可。
_OIDC_STATE: dict[str, tuple[str, str, float]] = {}
_OIDC_TTL = 600


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _delivery_problem(channel: str) -> str | None:
    """这个通道现在能不能发。能发返回 None,不能发返回一句"该配什么"。"""
    s = config.settings
    if channel == "email":
        provider = (s.email_provider or "console").strip().lower()
        if provider == "smtp" and not s.smtp_host:
            return "邮箱核验要配 SMTP_HOST(以及 SMTP_USER / SMTP_PASSWORD / EMAIL_FROM)"
        if provider == "resend" and not (s.resend_api_key and s.email_from):
            return "Resend 要配 RESEND_API_KEY 与 EMAIL_FROM"
        if provider not in ("console", "smtp", "resend", "webhook"):
            return f"EMAIL_PROVIDER 只能是 console/smtp/resend/webhook,收到 {provider!r}"
        if provider == "webhook" and not s.sms_webhook_url:
            return "EMAIL_PROVIDER=webhook 要配 SMS_WEBHOOK_URL"
        return None
    provider = (s.sms_provider or "webhook").strip().lower()
    if provider not in ("console", "webhook"):
        return f"SMS_PROVIDER 只能是 console/webhook,收到 {provider!r}"
    if provider == "webhook" and not s.sms_webhook_url:
        return "短信核验要配 SMS_WEBHOOK_URL(接你自己的短信服务)"
    return None


def _channel_of(method: str) -> str:
    """接口说的 method 与库里的 channel 是同一件事,只在这里对上一次。"""
    if method in ("email", "phone"):
        return method
    raise HTTPException(status_code=400, detail=f"不支持的注册方式:{method}")


def _public_policy() -> dict:
    p = policy_mod.policy_for("")
    return {
        "enabled": p.enabled,
        "methods": list(p.methods),
        "requires_verification": p.requires_verification,
        "code_ttl_minutes": p.code_ttl_minutes,
        "oidc": {
            "available": bool(p.oidc.get("configured")) and p.allows("oidc"),
            "label": p.oidc.get("label", ""),
        },
    }


class StartDTO(BaseModel):
    """发码。contact 是邮箱或手机号,由 method 决定怎么归一。"""

    method: str = Field("email", max_length=16)
    contact: str = Field(..., min_length=3, max_length=255)
    purpose: str = Field("register", max_length=16)


class VerifyDTO(BaseModel):
    method: str = Field("email", max_length=16)
    contact: str = Field(..., min_length=3, max_length=255)
    code: str = Field(..., min_length=4, max_length=12)
    display_name: str = Field("", max_length=128)
    # 核验之后建号要用的密码。OIDC 进来的人可以不给。
    password: str = Field("", max_length=1024)


class ResetRequestDTO(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class ResetCompleteDTO(BaseModel):
    token: str = Field("", max_length=128)
    method: str = Field("email", max_length=16)
    contact: str = Field("", max_length=255)
    code: str = Field("", max_length=12)
    new_password: str = Field(..., min_length=8, max_length=1024)


@router.get("/api/auth/registration/policy")
async def registration_policy() -> dict:
    """现在能不能注册、能用什么方式。不要求鉴权 —— 登录页要照它画按钮。"""
    return _public_policy()


@router.post("/api/auth/register/start")
async def register_start(payload: StartDTO) -> dict:
    """发验证码。这一步**要**说出"这个联系方式已经注册过":

    注册不是登录,同一个邮箱第二次注册本来就走不下去。含糊其辞只会让人反复试。
    """
    p = policy_mod.policy_for("")
    channel = _channel_of(payload.method)
    if not p.allows(channel):
        raise HTTPException(status_code=403, detail="这台实例没有开启这种注册方式")
    if payload.purpose not in ("register", "reset"):
        raise HTTPException(status_code=400, detail="purpose 只能是 register / reset")

    target = reg.contact_of(channel, payload.contact)
    if payload.purpose == "register" and await reg.contact_taken(channel, target):
        raise HTTPException(status_code=409, detail="这个联系方式已经注册过了,直接登录")
    if not policy_mod.rate_allows(target, p):
        raise HTTPException(status_code=429, detail="验证码发得太频繁,过一会儿再试")

    ttl = p.code_ttl_minutes
    problem = _delivery_problem(channel)
    if problem is not None:
        # 通道没配时先问再发:发不出去的码留在库里,只会让人对着一个"发送成功"发呆
        raise HTTPException(status_code=503, detail=problem)
    code = await reg.issue_code(channel, target, payload.purpose, p)
    try:
        if channel == "email":
            await deliver_email(target, code, payload.purpose, ttl)
        else:
            await deliver_sms(target, code, payload.purpose, ttl)
    except ChannelError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    policy_mod.rate_record(target)

    out: dict = {"ok": True, "ttl_minutes": ttl, "method": channel}
    # 只有明着配了固定码才回显。默认不回 —— 回显等于没有核验。
    if p.test_code:
        out["test_code"] = p.test_code
    return out


@router.post("/api/auth/register/verify")
async def register_verify(payload: VerifyDTO, request: Request, response: Response) -> dict:
    """核验并建号。要核验时先落 pending 再建号;不要核验就直接建。"""
    p = policy_mod.policy_for("")
    channel = _channel_of(payload.method)
    if not p.allows(channel):
        raise HTTPException(status_code=403, detail="这台实例没有开启这种注册方式")
    target = reg.contact_of(channel, payload.contact)
    if await reg.contact_taken(channel, target):
        raise HTTPException(status_code=409, detail="这个联系方式已经注册过了,直接登录")

    display_name = payload.display_name
    password_hash = ""
    try:
        if p.requires_verification:
            # 先验码,再取申请:取申请会把它删掉,码填错一次不该让人重填一遍密码。
            # 申请不存在说明人跳了步 —— 不能凭空建一个没有密码的账号。
            await reg.consume_code(channel, target, "register", payload.code, p)
            pending = await reg.take_activation(channel, target)
            if pending is None:
                raise reg.RegistrationError("先填密码并获取验证码,再来核验")
            display_name = pending.display_name or display_name
            password_hash = pending.password_hash
        user, identity = await reg.create_user(
            email=target if channel == "email" else "",
            phone=target if channel == "phone" else "",
            display_name=display_name,
            password=payload.password,
            password_hash=password_hash,
            role_key=p.default_role,
            policy=p,
        )
        await reg.drop_activation(channel, target)
    except reg.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    token = await auth_store.start_session(
        user.id,
        ip=_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, token)
    from engine.api.auth import set_auth_required

    set_auth_required(True)
    await audit.record(
        "auth.register", identity=identity, target=user.email, detail={"channel": channel}, ip=_ip(request)
    )
    return {"user": await me_dto(str(user.id), identity.tenant)}


@router.post("/api/auth/password/reset")
async def request_reset(payload: ResetRequestDTO, request: Request) -> dict:
    """申请一封重置邮件。

    正文里给两样东西:**一次性链接**(已经设过密码的人走它)与**验证码**
    (还没设过密码的账号走它)。两条都发,是因为接口不能按"这个账号有没有密码"
    改口吻 —— 那种区分是给攻击者的礼物。
    """
    p = policy_mod.policy_for("")
    if not p.enabled:
        raise HTTPException(status_code=403, detail="这台实例没有开启自助找回")
    try:
        email = reg.normalize_email(payload.email)
    except reg.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not policy_mod.rate_allows(email, p):
        raise HTTPException(status_code=429, detail="发得太频繁,过一会儿再试")

    token = await reg.issue_reset_token(email, p)
    if token is not None:
        link = f"{_frontend_base(request)}/login?reset={quote(token)}"
        try:
            await deliver_email(
                email,
                link,
                "reset",
                p.reset_ttl_minutes,
                link_name="重置密码链接",
                lead="点开下面这个链接就能设新密码",
            )
        except ChannelError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        # 重置验证码:提交时带 code 的那条路要用它
        await reg.issue_code("email", email, "reset", p)
        policy_mod.rate_record(email)
    return {
        "ok": True,
        "note": "如果这个邮箱有账号,重置邮件已经发出去了",
        "ttl_minutes": p.reset_ttl_minutes,
    }


def _frontend_base(request: Request) -> str:
    """邮件链接与 OIDC 回跳都要落到**前端**上,不是引擎。

    配了 registration scope 的 registration_public_base_url 就用它(生产必然
    如此:外网地址与容器内地址不是一回事);没配时按这一次请求的 Host 推,
    推不出来就明说该配什么。
    """
    scope = config.get_scope_config("registration", workspace_access(request) or "")
    base = str(scope.get("registration_public_base_url") or "").rstrip("/")
    if base:
        return base
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    host = forwarded or request.headers.get("host", "")
    if host:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0]
        return f"{proto}://{host}"
    logger.warning("没有 REGISTRATION_PUBLIC_BASE_URL,回跳地址只能猜:127.0.0.1:3000")
    return "http://127.0.0.1:3000"


@router.post("/api/auth/password/reset/complete")
async def complete_reset(payload: ResetCompleteDTO, request: Request, response: Response) -> dict:
    """两种走法:邮件里的令牌,或者还没设过密码的账号凭验证码。"""
    p = policy_mod.policy_for("")
    try:
        if payload.token:
            user = await reg.complete_reset(payload.token, payload.new_password)
            channel = "link"
        else:
            channel = _channel_of(payload.method)
            target = reg.contact_of(channel, payload.contact)
            await reg.consume_code(channel, target, "reset", payload.code, p)
            user = await reg.change_with_code(channel, target, payload.new_password)
    except reg.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    token = await auth_store.start_session(
        user.id, ip=_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    _set_session_cookie(response, request, token)
    await audit.record("auth.password.reset", target=user.email, detail={"via": channel}, ip=_ip(request))
    return {"ok": True}


# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------


def _oidc_redirect(request: Request) -> str:
    return f"{_frontend_base(request)}/api/auth/oidc/callback"


@router.get("/api/auth/oidc/authorize")
async def oidc_authorize(request: Request) -> Response:
    """把人送去身份提供方。state 与 nonce 存在进程里,回来对一次就删。"""
    p = policy_mod.policy_for("")
    if not p.allows("oidc"):
        raise HTTPException(status_code=403, detail="这台实例没有开启统一身份登录")
    try:
        cfg = oidc_client.OidcConfig.from_settings(_oidc_redirect(request))
        verifier, challenge = oidc_client.pkce_pair()
        state = uuid.uuid4().hex
        nonce = uuid.uuid4().hex
        url = oidc_client.authorize_url(
            cfg, state=state, nonce=nonce, code_challenge=challenge
        )
    except oidc_client.OidcError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    _OIDC_STATE[state] = (verifier, nonce, time.time() + _OIDC_TTL)
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url)


@router.get("/api/auth/oidc/callback")
async def oidc_callback(
    request: Request, response: Response, code: str = "", state: str = "", error: str = ""
) -> Response:
    """回来:换 token、认人、发会话 cookie,然后回前台。"""
    from fastapi.responses import RedirectResponse

    back = f"{_frontend_base(request)}/login"
    if error:
        return RedirectResponse(f"{back}?oauth_error={quote(error)}")
    entry = _OIDC_STATE.pop(state, None)
    if entry is None or entry[2] <= time.time():
        return RedirectResponse(f"{back}?oauth_error={quote('状态过期,重试一次')}")
    verifier, nonce, _ = entry

    p = policy_mod.policy_for("")
    try:
        cfg = oidc_client.OidcConfig.from_settings(_oidc_redirect(request))
        claims = oidc_client.exchange_code(cfg, code=code or "", code_verifier=verifier)
        if claims.get("nonce") and claims["nonce"] != nonce:
            raise reg.RegistrationError("id_token 的 nonce 对不上")
        profile = reg.OidcProfile(
            subject=str(claims["sub"]),
            email=str(claims.get("email") or ""),
            name=str(claims.get("name") or claims.get("preferred_username") or ""),
        )
        user, created = await reg.resolve_oidc_user(profile, cfg.issuer, p)
    except (oidc_client.OidcError, reg.RegistrationError) as exc:
        logger.warning("OIDC 登录失败", exc_info=True)
        return RedirectResponse(f"{back}?oauth_error={quote(str(exc))}")

    token = await auth_store.start_session(
        user.id, ip=_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    redirect = RedirectResponse(f"{_frontend_base(request)}/issues")
    redirect.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=14 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )
    await audit.record(
        "auth.oidc",
        target=user.email,
        detail={"issuer": cfg.issuer, "created": created},
        ip=_ip(request),
    )
    return redirect
