"""租户级插件启停

`plugin_settings` 那套 scope 是配置语义(公共值打底、租户覆盖),存得下开关,
存不下"谁在什么时候决定让这个租户跑这个插件"。第三方插件进 SaaS 之后,
审计一定会问这一句,所以单起一张表:

    plugin_tenancy(tenant, plugin, enabled, config, updated_by, updated_at)

主键 `(tenant, plugin)`。没有行 = 这个租户没选过,跟随平台默认——"没选过"与
"明确关掉"必须分得开,压成一个值之后,页面上就再也开不回去了。

Revision ID: 015
Revises: 014
"""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_tenancy",
        sa.Column("tenant", sa.String(64), primary_key=True, nullable=False, server_default=""),
        sa.Column("plugin", sa.String(128), primary_key=True, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(128), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(40), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("tenant", "plugin", name="pk_plugin_tenancy"),
    )
    op.create_index("ix_plugin_tenancy_tenant", "plugin_tenancy", ["tenant"])


def downgrade() -> None:
    op.drop_index("ix_plugin_tenancy_tenant", table_name="plugin_tenancy")
    op.drop_table("plugin_tenancy")
