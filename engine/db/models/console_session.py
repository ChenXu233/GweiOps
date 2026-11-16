from datetime import datetime, timezone
from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConsoleSessionRow(Base):
    """控制台助手的一个会话,决定谁、能调什么,须可审计。

    进程内只做缓存;重启后从这里读回,权限依据不随进程丢失。
    """

    __tablename__ = "console_sessions"
    __table_args__ = (Index("ix_console_sessions_owner", "tenant", "actor", "last_used_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    binding: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    bindings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confirm: Mapped[bool] = mapped_column(nullable=False, default=True)
    actions: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)
    last_used_at: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)


class ConsoleMessageRow(Base):
    """对话里的一行:用户消息、助手消息、工具调用与结果。

    只追加;不设外键,会话回收后审计记录仍在。
    """

    __tablename__ = "console_messages"
    __table_args__ = (Index("ix_console_messages_session", "session_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # user / assistant / tool_call / tool_result / approved / denied / error
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False, default=_now)


__all__ = ["ConsoleMessageRow", "ConsoleSessionRow"]
