# engine/migrations/versions/007_incident_topic.py
"""事故记住它对应的话题

一次讨论是话题(owner/repo#number),每次改动是话题上的一个变更单元。
没有这一列,平台就分不清"接着这个 PR 改"和"再开一个 PR"。

Revision ID: 007
Revises: 006
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("topic", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("incidents", "topic")
