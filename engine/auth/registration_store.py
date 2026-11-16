# engine/auth/registration_store.py
"""注册这条路对库做的所有事 —— 发码、验码、建号、找回密码、绑 OIDC。

和 `store.py` 分开的理由很实际:那个文件是每个请求都要走一遍的鉴权路径,
这里的事一次注册才发生一次,而且要多几步校验。混在一起会让"每个请求都做
的必要工作"看不出来。

所有校验都先说清理由,**不区分"没这个人"与"填错了"**的地方只有一处:
找回密码与密码登录 —— 那种区分是给攻击者的礼物。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from engine.auth import Identity, hash_password
from engine.auth import store as auth_store
from engine.auth.registration import (
    Policy,
    hash_code,
    new_code,
    new_link_token,
    normalize_contact,
)
from engine.db import async_session_factory
from engine.db.models import (
    ExternalIdentity,
    PasswordResetToken,
    Role,
    Tenant,
    User,
    UserActivation,
    UserContact,
    UserRole,
    UserSession,
    VerificationCode,
)




class RegistrationError(ValueError):
    """注册走不下去。message 直接给人看。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def normalize_email(email: str) -> str:
    value = normalize_contact(email)
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise RegistrationError("邮箱格式不对")
    return value


def normalize_phone(phone: str) -> str:
    """只留数字与前导 +。手机号唯一性靠这个归一化,不靠格式花样。"""
    raw = (phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit() or (ch == "+" and not raw[:1].isdigit()))
    if len(digits.lstrip("+")) < 6:
        raise RegistrationError("手机号格式不对")
    return digits


def contact_of(channel: str, value: str) -> str:
    return normalize_email(value) if channel == "email" else normalize_phone(value)


# ---------------------------------------------------------------------------
# 租户与角色
# ---------------------------------------------------------------------------


async def _tenant_id_for(session, slug: str) -> uuid.UUID:
    tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise RegistrationError(f"租户不存在:{slug}")
    return tenant_id


async def _role_id(session, tenant_id: uuid.UUID, key: str) -> uuid.UUID | None:
    return await session.scalar(
        select(Role.id).where(Role.tenant_id == tenant_id, Role.key == key)
    )


async def _attach_default_role(session, user: User, tenant_id: uuid.UUID, key: str) -> None:
    if not key:
        return
    role_id = await _role_id(session, tenant_id, key)
    if role_id is None:
        # 角色不存在不算注册失败,但要留痕:人进来了却没有角色,等于看不见任何东西。
        import logging

        logging.getLogger(__name__).warning(
            "注册要接的角色 %s 在租户里不存在,新用户 %s 没有角色", key, user.email
        )
        return
    session.add(UserRole(user_id=user.id, role_id=role_id))


# ---------------------------------------------------------------------------
# 查重
# ---------------------------------------------------------------------------


async def find_user_by_contact(
    session, channel: str, target: str, tenant_id: uuid.UUID | None = None
) -> User | None:
    """这个人是不是已经有了。邮箱看 users.email,手机号看已验证的 contact。"""
    if channel == "email":
        stmt = select(User).where(User.email == target)
        if tenant_id is not None:
            stmt = stmt.where(User.tenant_id == tenant_id)
        return await session.scalar(stmt)
    contact = await session.scalar(
        select(UserContact).where(
            UserContact.kind == "phone", UserContact.target == target, UserContact.confirmed.is_(True)
        )
    )
    if contact is None:
        return None
    return await session.get(User, contact.user_id)


async def contact_taken(channel: str, target: str) -> bool:
    async with async_session_factory() as session:
        return await find_user_by_contact(session, channel, target) is not None


# ---------------------------------------------------------------------------
# 发码
# ---------------------------------------------------------------------------


async def issue_code(channel: str, target: str, purpose: str, policy: Policy) -> str:
    """发一个新码。旧码当场作废 —— 同时有效的码越多,撞开的机会越多。"""
    # 配了固定码就用它:自部署联调时不必去翻日志
    code = policy.test_code or new_code()
    expires = _now() + timedelta(minutes=policy.code_ttl_minutes)
    async with async_session_factory() as session:
        await session.execute(
            delete(VerificationCode).where(
                VerificationCode.channel == channel,
                VerificationCode.target == target,
                VerificationCode.purpose == purpose,
            )
        )
        session.add(
            VerificationCode(
                channel=channel,
                target=target,
                purpose=purpose,
                code_hash=hash_code(target, purpose, code),
                expires_at=expires,
            )
        )
        await session.commit()
    return code


async def _live_code(session, channel: str, target: str, purpose: str) -> VerificationCode | None:
    row = await session.scalar(
        select(VerificationCode)
        .where(
            VerificationCode.channel == channel,
            VerificationCode.target == target,
            VerificationCode.purpose == purpose,
        )
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    return row


async def consume_code(channel: str, target: str, purpose: str, code: str, policy: Policy) -> None:
    """验码。过期的、错太多次的、不对的都拒,而且**都不留活口**。"""
    async with async_session_factory() as session:
        row = await _live_code(session, channel, target, purpose)
        if row is None:
            raise RegistrationError("先获取验证码")
        if (_aware(row.expires_at) or _now()) <= _now():
            await session.delete(row)
            await session.commit()
            raise RegistrationError("验证码已过期,重新获取一个")
        if row.attempts >= policy.max_attempts:
            await session.delete(row)
            await session.commit()
            raise RegistrationError("尝试次数太多,重新获取一个验证码")
        if not code or hash_code(target, purpose, code.strip()) != row.code_hash:
            row.attempts += 1
            await session.commit()
            raise RegistrationError("验证码不对")
        await session.delete(row)
        await session.commit()


# ---------------------------------------------------------------------------
# 注册:两级 —— 要核验的先落 pending,不要核验的直接建号
# ---------------------------------------------------------------------------


async def stage_activation(
    channel: str, target: str, display_name: str, password: str
) -> None:
    """核验通过之前,人不进 users 表:没核验的"用户"会让租户的人数与权限算错。"""
    if len(password or "") < 8:
        raise RegistrationError("密码至少 8 位")
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(UserActivation).where(
                UserActivation.channel == channel, UserActivation.target == target
            )
        )
        if existing is not None:
            await session.delete(existing)
            await session.flush()
        session.add(
            UserActivation(
                channel=channel,
                target=target,
                display_name=(display_name or "")[:128],
                password_hash=hash_password(password),
                expires_at=_now() + timedelta(minutes=30),
            )
        )
        await session.commit()


async def take_activation(channel: str, target: str) -> UserActivation | None:
    async with async_session_factory() as session:
        row = await session.scalar(
            select(UserActivation).where(
                UserActivation.channel == channel, UserActivation.target == target
            )
        )
        if row is None:
            return None
        if (_aware(row.expires_at) or _now()) <= _now():
            await session.delete(row)
            await session.commit()
            return None
        return row


async def drop_activation(channel: str, target: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(UserActivation).where(
                UserActivation.channel == channel, UserActivation.target == target
            )
        )
        await session.commit()


async def create_user(
    *,
    email: str = "",
    phone: str = "",
    display_name: str = "",
    password: str = "",
    password_hash: str = "",
    role_key: str = "",
    policy: Policy,
    tenant_slug: str = "",
    confirmed: bool = True,
) -> tuple[User, Identity]:
    """建一个人。邮箱是必填的身份,手机号是可选的第二联系方式。"""
    email = normalize_email(email) if email else ""
    if not email:
        # 手机号注册的人也得有一行唯一身份:用手机号占住 email 列,
        # 这样"谁能登录"永远只有一个字段要查。
        if not phone:
            raise RegistrationError("至少要有邮箱或者手机号")
        email = f"{phone}@phone.local"
    slug = policy.target_tenant or tenant_slug or auth_store.DEFAULT_TENANT_SLUG

    async with async_session_factory() as session:
        tenant_id = await _tenant_id_for(session, slug)
        if await session.scalar(
            select(func.count()).select_from(User).where(
                User.tenant_id == tenant_id, User.email == email
            )
        ):
            raise RegistrationError("这个邮箱已经注册过了")
        user = User(
            tenant_id=tenant_id,
            email=email,
            display_name=(display_name or email.split("@")[0])[:128],
            password_hash=password_hash or (hash_password(password) if password else ""),
            permissions=[],
            status="active" if confirmed else "pending",
        )
        session.add(user)
        await session.flush()
        if email and "@phone.local" not in email:
            session.add(
                UserContact(user_id=user.id, kind="email", target=email, confirmed=True)
            )
        if phone:
            session.add(
                UserContact(user_id=user.id, kind="phone", target=phone, confirmed=True)
            )
        await _attach_default_role(session, user, tenant_id, role_key)
        await session.commit()
        await session.refresh(user)
        identity = await auth_store.identity_of(session, user)
        return user, identity


# ---------------------------------------------------------------------------
# 找回密码
# ---------------------------------------------------------------------------


async def issue_reset_token(email: str, policy: Policy) -> str | None:
    """有这个人就发一枚令牌。没这个人返回 None —— 接口两边回同一句话。"""
    target = normalize_email(email)
    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.email == target, User.status != "disabled"))
        if user is None or not user.active:
            return None
        token, token_hash = new_link_token()
        await session.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False)
            )
        )
        session.add(
            PasswordResetToken(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=_now() + timedelta(minutes=policy.reset_ttl_minutes),
            )
        )
        await session.commit()
        return token


async def verify_reset_token(token: str) -> User | None:
    from engine.auth import hash_session_token

    if not token:
        return None
    async with async_session_factory() as session:
        row = await session.get(PasswordResetToken, hash_session_token(token))
        if row is None or row.used:
            return None
        if (_aware(row.expires_at) or _now()) <= _now():
            return None
        return await session.get(User, row.user_id)


async def complete_reset(token: str, new_password: str) -> User:
    """用令牌改密码。改完踢掉所有会话 —— 密码变了,旧 cookie 不该还能开。"""
    from engine.auth import hash_session_token

    if len(new_password or "") < 8:
        raise RegistrationError("新密码至少 8 位")
    async with async_session_factory() as session:
        row = await session.get(PasswordResetToken, hash_session_token(token))
        if row is None or row.used:
            raise RegistrationError("链接无效或已用过")
        if (_aware(row.expires_at) or _now()) <= _now():
            raise RegistrationError("链接已过期,重新申请一封")
        user = await session.get(User, row.user_id)
        if user is None or not user.active:
            raise RegistrationError("账号已不可用")
        user.password_hash = hash_password(new_password)
        row.used = True
        await session.execute(
            delete(UserSession).where(UserSession.user_id == user.id)
        )
        await session.commit()
        await session.refresh(user)
        return user


async def change_with_code(channel: str, target: str, new_password: str) -> User:
    """凭验证码改密码。**只对还没设过密码的账号开放**:

    已经是密码账号的人,拿到手机号/邮箱不等于拿到账号,否则"验证码注册"
    就成了一条绕过密码的侧门。那种情况走邮件里的一次性链接。

    这里不再比一次码:调用方已经 `consume_code` 过了,码是一次性的。
    """
    async with async_session_factory() as session:
        user = await find_user_by_contact(session, channel, target)
    if user is None:
        raise RegistrationError("这个联系方式没有对应的账号")
    if user.password_hash:
        raise RegistrationError("这个账号已经设过密码,请用邮件里的链接重置")
    return await complete_reset_by_user(user, new_password)


async def complete_reset_by_user(user: User, new_password: str) -> User:
    if len(new_password or "") < 8:
        raise RegistrationError("新密码至少 8 位")
    async with async_session_factory() as session:
        found = await session.get(User, user.id)
        if found is None or not found.active:
            raise RegistrationError("账号已不可用")
        found.password_hash = hash_password(new_password)
        await session.execute(
            delete(UserSession).where(UserSession.user_id == found.id)
        )
        await session.commit()
        await session.refresh(found)
        return found


# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OidcProfile:
    subject: str
    email: str
    name: str


async def resolve_oidc_user(profile: OidcProfile, issuer: str, policy: Policy) -> tuple[User, bool]:
    """sub 绑过就登那个人;没绑过按邮箱对上;都没有就看开不开自动建号。

    返回 (user, created)。绑定是**先认 sub**:同一个人在提供方那边改了邮箱,
    也不该变成两个人。
    """
    email = normalize_email(profile.email) if profile.email else ""
    async with async_session_factory() as session:
        link = await session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.issuer == issuer, ExternalIdentity.subject == profile.subject
            )
        )
        if link is not None:
            user = await session.get(User, link.user_id)
            if user is None or not user.active:
                raise RegistrationError("绑定的账号已不可用")
            return user, False

        if email:
            user = await session.scalar(select(User).where(User.email == email))
            if user is not None and user.active:
                session.add(
                    ExternalIdentity(
                        user_id=user.id, issuer=issuer, subject=profile.subject, email=email
                    )
                )
                await session.commit()
                return user, False

        if not policy.oidc.get("auto_create", True):
            raise RegistrationError("这个统一身份还没有对应账号,先让管理员建一个")

    role = str(policy.oidc.get("default_role") or policy.default_role)
    user, _ = await create_user(
        email=email,
        display_name=profile.name or (email.split("@")[0] if email else profile.subject),
        role_key=role,
        policy=policy,
    )
    async with async_session_factory() as session:
        session.add(
            ExternalIdentity(
                user_id=user.id, issuer=issuer, subject=profile.subject, email=email
            )
        )
        await session.commit()
    return user, True


__all__ = [
    "OidcProfile",
    "RegistrationError",
    "change_with_code",
    "complete_reset",
    "complete_reset_by_user",
    "consume_code",
    "contact_of",
    "contact_taken",
    "create_user",
    "drop_activation",
    "find_user_by_contact",
    "issue_code",
    "issue_reset_token",
    "normalize_email",
    "normalize_phone",
    "resolve_oidc_user",
    "stage_activation",
    "take_activation",
    "verify_reset_token",
]
