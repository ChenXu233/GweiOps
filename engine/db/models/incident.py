import uuid  # noqa: F401  (保持与其它模型的导入风格一致)
from sqlalchemy import JSON, Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


class Incident(Base):
    """一次事故:开始写一行,收尾改写同一行。

    账本回答"哪几处被改了",事故回答"这一次到底发生了什么、结论是什么"。
    两者共用 incident_id,但不是一个东西:报告没有句柄、没有窗口、撤不了。

    status 留着 open 是有用的:事故开了没收口,说明那一场卡住了——
    早上该看到的是"卡住",不是"什么都没发生"。
    """

    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_tenant", "tenant", "started_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    signal_source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    signal_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    started_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    finished_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exhausted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


__all__ = ["Incident"]
