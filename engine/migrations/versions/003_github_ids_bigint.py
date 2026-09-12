"""github_id columns to bigint

GitHub 的 issue/repository ID 已超过 int32 上限（2026 年 issue ID > 26 亿），
INTEGER 列无法存储真实数据，统一改为 BIGINT。

Revision ID: 003
Revises: 002
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("projects", "github_id"),
    ("issues", "github_id"),
    ("pull_requests", "github_id"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, type_=sa.BigInteger())


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, type_=sa.Integer())
