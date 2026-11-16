import uuid
from datetime import datetime, timezone
from sqlalchemy import String, BigInteger, DateTime, JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from engine.db.base import Base


class Project(Base):
    """一个仓库。

    身份由 (租户, 来源, 仓库全名) 决定,不由平台侧的 id 决定:`github_id` 是
    GitHub 那套身份证里的号,CNB 与 GitLab 各有各的号,同一个数字在两边不是
    同一份代码。没有 id 的来源传 None 照样能建。
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "name", name="uq_projects_tenant_source_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # 哪个平台的仓库:github / cnb / gitlab …。与"哪个团队"(tenant)正交。
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="github", server_default="github")
    # 来源自己给的 id。可以没有——没有就不能拿它当身份。
    github_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    tenant = relationship("Tenant")
    issues: Mapped[list["Issue"]] = relationship(back_populates="project")
