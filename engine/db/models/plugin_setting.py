from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


class PluginSetting(Base):
    """按 (租户, scope, 键) 存下来的一份配置值。

    环境变量只能给部署那一刻的答案;这里给的是运行期还能改的答案。
    租户为空串表示这个部署的公共值——先读公共,再读租户,租户覆盖公共。
    值不加密(库本身就是信任边界),但接口按字段的 expose 规则决定给不给。
    """

    __tablename__ = "plugin_settings"
    __table_args__ = (Index("ix_plugin_settings_scope", "tenant", "scope"),)

    tenant: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")


__all__ = ["PluginSetting"]
