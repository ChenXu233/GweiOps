"""注册留下的三类事实:谁能联系到你、发出去的码、待激活的人。

- `user_contacts`:一个人可以被几种方式联系到。手机号是核验过的才留下。
- `verification_codes`:一次性码,只存哈希。用完即删,过期不续。
- `user_activations`:先验证、后建号。行还活着说明这个人还没成为用户。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserContact(Base):
    """邮箱 / 手机号。confirmed 之前只是"填过",不是"是他的"。"""

    __tablename__ = "user_contacts"
    __table_args__ = (
        Index("ix_user_contacts_target", "kind", "target", unique=True),
        Index("ix_user_contacts_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # email | phone
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class VerificationCode(Base):
    """一个还在有效期内的码。哈希绑了收件人与用途,挪不了。"""

    __tablename__ = "verification_codes"
    __table_args__ = (
        Index("ix_verification_codes_target", "channel", "target", "purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # email | phone
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)  # register | reset
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class UserActivation(Base):
    """核验过了、还没建成账号的申请。密码在这里也是哈希。"""

    __tablename__ = "user_activations"
    __table_args__ = (
        Index("ix_user_activations_target", "channel", "target", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class PasswordResetToken(Base):
    """重置密码的一次性令牌。邮件链接里是明文,库里只有哈希。"""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_user", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    used: Mapped[bool] = mapped_column(default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class ExternalIdentity(Base):
    """OIDC 的 sub 与本地用户的绑定。同一 issuer + sub 只对应一个人。"""

    __tablename__ = "external_identities"
    __table_args__ = (
        Index("ix_external_identities_subject", "issuer", "subject", unique=True),
        Index("ix_external_identities_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


__all__ = [
    "ExternalIdentity",
    "PasswordResetToken",
    "UserActivation",
    "UserContact",
    "VerificationCode",
]
