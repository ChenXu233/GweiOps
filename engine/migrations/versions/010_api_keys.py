"""api_keys —— 给外界 agent 的凭据

控制台令牌写在环境变量里,一个部署就几条;外界的 agent 是一把一把的,要能单独
签发、单独吊销、各自不同的权限。这张表存的是密钥的记录:明文只在签发那一次出现,
库里只留 sha256 与一段可辨识的前后缀。

permissions / tools / bindings 都是 JSON 数组:第一个贴着权限目录,后两个是可选的
白名单收窄 —— tools 收窄到哪几个工具,bindings 收窄到哪些资源(下游目标)。

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False, server_default=""),
        sa.Column("name", sa.String(64), nullable=False, server_default=""),
        sa.Column("hint", sa.String(32), nullable=False, server_default=""),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("tools", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("bindings", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("last_used_at", sa.String(40), nullable=False, server_default=""),
        sa.Column("expires_at", sa.String(40), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
    )
    op.create_index("ix_api_keys_tenant", "api_keys", ["tenant"])
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_keys_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant", table_name="api_keys")
    op.drop_table("api_keys")
