# engine/migrations/versions/008_incident_diff.py
"""事故记下这一轮改了哪些文件

时间线要说得出"这一轮动了什么"。改了什么是工作区的事实,平台自己数,
不问 harness 自报——自报的东西没法核。

Revision ID: 008
Revises: 007
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("diff", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("incidents", "diff")
