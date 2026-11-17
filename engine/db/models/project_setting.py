"""项目级的值 —— 可见性、默认发布参数、项目级凭据。

项目是资源,不是标签:它下面几个仓库共享一套发布策略与插件目标。这些东西
原来只能落在**工作区默认**上,于是"这个项目怎么发布"和"别个项目怎么发布"
只能配一处;或者落在每个仓库行上,于是同一个项目的三个仓库抄三遍,改一次
要改三处 —— 而那些副本迟早有一份没跟上。

所以项目这一级要有一层自己的值。它不进 `plugin_settings`(= 工作区的配置),
因为那层的键是 (租户, scope, key),它只能回答"整个工作区怎么配"。

三样东西,一个形状:

- `visibility`:这个项目对不对**外人**可见。工作区成员之间的可见性不靠它判;
  它挡的是"这个项目连同它的仓库要不要出现在别人眼前"那类判断,见
  `engine/api/routes/console.py` 的仓库与项目列表
- `defaults`:`release` 那层的默认发布参数,项目里每个仓库都先读这一层,
  再读自己那行
- `credentials`:这个项目自己的凭据。值只进密钥仓库(`settings_store`,
  带租户与 scope),库里这一行只记**有哪些键**和一句说明 —— 一个项目几条
  凭据,谁签的、什么时候换的,看得见;明文不在这张表里
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectSetting(Base):
    """一个项目的一行。没有这一行 = 全用工作区默认,不写空行占位。"""

    __tablename__ = "project_settings"
    __table_args__ = (
        Index("ix_project_settings_project", "project_id", unique=True),
        Index("ix_project_settings_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # workspace | restricted:restricted 的项目连它的仓库一起不列给不是成员的人
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="workspace")
    # 发布默认值:{"mode": "compose", "service": "api"} 这一层
    defaults: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 凭据的键清单:[{"key": "registry_token", "description": "镜像仓库口令", "updated_at": "..."}]
    # 值在密钥仓库里,键是 scope="project:<slug>"
    credentials: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )


__all__ = ["ProjectSetting"]
