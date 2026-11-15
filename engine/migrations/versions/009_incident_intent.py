# engine/migrations/versions/009_incident_intent.py
"""事故记下这一轮本打算做什么

一个候选都没落成单元时,这一轮就没有别的证据可读:时间线上只剩信号与诊断。
意图(连同"哪个候选为什么没做")记在事故上,那一轮才说得出自己为什么什么都没做。

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("intent", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )


def downgrade() -> None:
    op.drop_column("incidents", "intent")
