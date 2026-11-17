"""邀请 —— 管理员发一条,被邀请人自己接。

`memberships` 只有人已经在里面时才有那一行;"把一个人拉进来"原来只有一条路:
管理员替他设一个初始密码。那条路有两个毛病:管理员得替别人想一个密码(还得
用带外通道告诉他),以及同一个人被拉进第二个工作区时又多一份密码。

邀请把这两件事都拿掉:

- 邀请里只存**工作区**与**被邀请的邮箱**,不存密码。密码是这个人自己的事。
- 令牌只存哈希,和会话令牌一样:库被看到也换不出能用的邀请链接。
- 只能用一次、会过期。用过之后 `accepted_at` 留着,再点这条链接得到的是
  "这条邀请已经用过了",而不是一个看不懂的 404。

接邀请的人是谁,靠邮箱认:

| 这个邮箱 | 接下来发生什么 |
| --- | --- |
| 部署里已经有这个人 | 认领他:只加一条成员关系,他自己的密码不动 |
| 还没有 | 他自己设一次密码,那一刻才建这个人 |
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Invitation(Base):
    """一条邀请。角色与权限在发的时候定死,接的人没有改动余地。

    `role_ids` / `permissions` 是 JSON:`user_roles` 要一条成员关系才能挂,
    而这条邀请还没有成员关系。接的那一刻才展开成真正的角色行。
    """

    __tablename__ = "invitations"
    __table_args__ = (
        Index("ix_invitations_token", "token_hash", unique=True),
        Index("ix_invitations_tenant_email", "tenant_id", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # 发邀请的是一条成员关系:接了之后,新成员挂在这条下面(发的人是所有者时留空)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.user_id", ondelete="SET NULL"), nullable=True
    )
    # 挂到谁的下面。所有者发的邀请留空 = 新成员是同级
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.user_id", ondelete="SET NULL"), nullable=True
    )
    role_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    def live(self, now: datetime | None = None) -> bool:
        """还能不能用。过期、用过、撤销过,三种都不行,理由各说各的。"""
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and expires > now
        )

    @property
    def state(self) -> str:
        """pending | accepted | revoked | expired。界面按它给下一步。"""
        if self.accepted_at is not None:
            return "accepted"
        if self.revoked_at is not None:
            return "revoked"
        return "pending" if self.live() else "expired"


__all__ = ["Invitation"]
