# engine/agent/console_store.py
"""控制台助手的会话表与对话表。

表随启动 checkfirst 建一次,与账本、事故同一种做法(仓库里没有迁移工具)。
"""

from __future__ import annotations


async def ensure_schema() -> None:
    from engine.db.engine import engine
    from engine.db.models.console_session import ConsoleMessageRow, ConsoleSessionRow

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: ConsoleSessionRow.__table__.create(c, checkfirst=True)
        )
        await conn.run_sync(
            lambda c: ConsoleMessageRow.__table__.create(c, checkfirst=True)
        )


__all__ = ["ensure_schema"]
