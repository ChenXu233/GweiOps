from sqlalchemy import Boolean, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


class PluginTenancy(Base):
    """按 (租户, 插件) 存下来的一条授权决定。

    这不是配置:`plugin_settings` 那套是"公共值打底、租户覆盖"的继承语义,
    适合配置;授权要的是"默认跟随平台、租户自己选",并且要答得出是谁在什么时候
    做的这个决定——所以单独一张表,带 `updated_by` / `updated_at`。
    """

    __tablename__ = "plugin_tenancy"
    __table_args__ = (Index("ix_plugin_tenancy_tenant", "tenant"),)

    tenant: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    plugin: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 租户自己传的插件配置;形状由插件声明决定,这里只负责原样存住
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")


__all__ = ["PluginTenancy"]
