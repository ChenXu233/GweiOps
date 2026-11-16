import uuid
from datetime import datetime, timezone
from sqlalchemy import String, BigInteger, DateTime, JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from engine.db.base import Base


class Project(Base):
    """一个仓库,以及它所属的项目。

    这棵树是三层:`tenants` → `projects`(项目)→ `projects`(仓库,`parent_id` 指向项目)。
    自己不带 `parent_id` 的那一行就是项目:`slug` 是它在这棵树上唯一的名字,
    `name` 是它显示给人看的名字。

    仓库的身份由 (租户, 来源, 仓库全名) 决定,不由平台侧的 id 决定:`github_id` 是
    GitHub 那套身份证里的号,CNB 与 GitLab 各有各的号,同一个数字在两边不是
    同一份代码。没有 id 的来源传 None 照样能建。

    项目是资源,不是装饰:`acme/api` 与 `acme/web` 是同一家的两个仓库,而
    `acme/api` 与 `other/api` 不是同一份代码。少了这一级,仓库全名就是唯一身份,
    项目级的可见性、默认动作、凭据也没有地方摆。
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # 指向项目的那一行。空 = 这一行自己就是项目。
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    # 在这棵树上唯一、且稳定的名字:仓库是 `来源-仓库全名`(/ 也压成 -,见
    # repo_slug),项目取人给的那一段。分隔符一律 `-`,URL 里不必转义;
    # 反过来 slug 不可逆,要"来源 + 仓库全名"就读 source / name 两栏。
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    # 哪个平台的仓库:github / cnb / gitlab …。项目行的这一栏是空串:项目不属于任何平台。
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

    @property
    def is_project(self) -> bool:
        return self.parent_id is None
