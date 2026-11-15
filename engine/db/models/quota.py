# engine/db/models/quota.py
"""配额与用量 —— 先把账本形状定下来,执行点是后面的事。

限量按"主体 × 资源 × 窗口"记账:`subject` 可以是租户(tenant)或人(user),
`resource` 是资源的名字(注册接口不预设清单),`window` 是 `5h` / `7d` / `30d`
这样的滚动窗口。窗口是滚动的,所以这里不存"当前周期",只存每一笔的落账时间。

不改 `Tenant` 的列:配额是计费插件要读要写的东西,往核心表上加列等于把
策略钉进核心。一张独立的表,谁读谁写都说得出自己读的是哪一份。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


class QuotaUsage(Base):
    """一笔用量。读的时候按窗口求和,不维护计数器 —— 计数器会与事实对不上。"""

    __tablename__ = "quota_usage"
    __table_args__ = (
        Index("ix_quota_usage_subject", "subject_kind", "subject_id", "resource", "used_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # tenant | user
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )


__all__ = ["QuotaUsage"]
