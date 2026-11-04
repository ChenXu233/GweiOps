import uuid  # noqa: F401  (保持与其它模型的导入风格一致)
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


class ChangeEvent(Base):
    """账本的一行:一次判定、一次执行、一次放行或一次撤销。

    只追加,不改写。同一单元的多行用 unit_id 串起来,当前状态取 id 最大的那行——
    顺序由自增主键保证,不依赖时间戳(机器时钟会回拨)。
    """

    __tablename__ = "change_events"
    __table_args__ = (
        Index("ix_change_events_unit", "tenant", "unit_id", "id"),
        Index("ix_change_events_key", "idempotency_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    binding: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    verdict: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


__all__ = ["ChangeEvent"]
