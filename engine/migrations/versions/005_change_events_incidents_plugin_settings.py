"""change_events, incidents, plugin_settings tables

这三张表只有 ORM 模型,一直没有迁移:走 create_all 的测试能建出来,
走 alembic upgrade head 的真实部署建不出来。补齐部署路径。

Revision ID: 005
Revises: 004
Create Date: 2026-11-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("unit_id", sa.String(64), nullable=False),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("binding", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_change_events"),
    )
    op.create_index("ix_change_events_unit", "change_events", ["tenant", "unit_id", "id"])
    op.create_index("ix_change_events_key", "change_events", ["idempotency_key"])

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("signal_source", sa.String(64), nullable=False),
        sa.Column("signal_title", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("exhausted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index("ix_incidents_tenant", "incidents", ["tenant", "started_at"])

    op.create_table(
        "plugin_settings",
        sa.Column("tenant", sa.String(64), primary_key=True),
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
    )
    op.create_index("ix_plugin_settings_scope", "plugin_settings", ["tenant", "scope"])


def downgrade() -> None:
    op.drop_index("ix_plugin_settings_scope", table_name="plugin_settings")
    op.drop_table("plugin_settings")
    op.drop_index("ix_incidents_tenant", table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("ix_change_events_key", table_name="change_events")
    op.drop_index("ix_change_events_unit", table_name="change_events")
    op.drop_table("change_events")
