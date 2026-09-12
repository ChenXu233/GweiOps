"""timestamp columns to timestamptz

模型的 UTC aware 默认值（datetime.now(timezone.utc)）写入 naive
TIMESTAMP 列时 asyncpg 报 "can't subtract offset-naive and
offset-aware datetimes"，统一改为 TIMESTAMPTZ。

Revision ID: 002
Revises: 001
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column)
_COLUMNS = [
    ("projects", "created_at"),
    ("issues", "created_at"),
    ("agent_sessions", "started_at"),
    ("agent_sessions", "ended_at"),
    ("patches", "created_at"),
    ("pull_requests", "created_at"),
    ("approval_votes", "created_at"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
