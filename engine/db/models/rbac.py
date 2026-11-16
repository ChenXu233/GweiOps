# engine/db/models/rbac.py
"""人、成员关系、角色、会话、审计。

两件事分开:一个人(**person**)有且只有一份凭据,他属于哪个工作区、在那里
是什么角色由**成员关系**(membership)说。同一个人被拉进第二个工作区时,多出来
的是一条成员关系,不是第二条密码。

角色是数据不是枚举:租户自己建角色、自己勾权限。owner/operator/viewer 只是
初始化时塞进去的三个预设(is_system),权限可以改,但删不掉——删掉之后
"谁是所有者"就没有答案了。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    """一个租户里的一套权限。key 在租户内唯一,用来在代码里指代预设角色。"""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class Person(Base):
    """一个人。凭据跨工作区只有一份:改一次密码,他在每个工作区里都是新密码。

    `email` 是这个人对外的身份名,在整个部署里唯一 —— 不是"某个工作区里的邮箱"。
    两个租户里出现同一个邮箱,那是**同一个人**,只是有两条成员关系;迁移 018 之前
    留下过这种行,它们被并成一条 person。
    """

    __tablename__ = "persons"
    __table_args__ = (UniqueConstraint("email", name="uq_persons_email"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 登录成功不等于能看账:没有任何成员关系的人照样是空权限
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def active(self) -> bool:
        return self.status == "active"


class Membership(Base):
    """一个人在**一个工作区**里的身份:角色、个人追加权限、从属关系。

    `user_id` 列名保留,值是成员关系的 id —— 它出现在会话、审计、"谁点的头"这些
    地方,问的一直是"这个工作区里的哪个人",不是"这台机器上的哪个人"。同一个人
    在两个工作区里有两行,两个不同的 id。
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "person_id", name="uq_memberships_tenant_person"),
        Index("ix_memberships_tenant", "tenant_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
    )
    # 非空就是子成员:权限只能是父成员的子集,且按范围逐个取交集
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.user_id", ondelete="CASCADE"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    @property
    def is_sub_user(self) -> bool:
        return self.parent_id is not None

    @property
    def active(self) -> bool:
        return self.status == "active"


class UserRole(Base):
    """多对多:一个成员可以同时是运维和只读。`user_id` 是成员关系的 id。

    表名与列名没改:角色是租户级的,成员关系也是,两者本来就该在同一层。
    """

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.user_id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class UserSession(Base):
    """登录会话。只存令牌哈希——库被看到,也换不出可用的 cookie。

    会话属于**人**不属于成员关系:一次登录之后能进几个工作区,是这个人有几条
    成员关系的事。URL 里换了工作区不该要求重新登录。
    """

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_person", "person_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class AuditLog(Base):
    """谁在什么时候对什么做了什么。追加日志,永不改写。

    `actor_id` 记的是成员关系的 id:审计问的是"这个工作区里的谁",同一个人在
    两个工作区里做的事不该被读成同一件。
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_tenant_time", "tenant_id", "created_at"),
        Index("ix_audit_actor", "actor_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
