"""注册、核验、OIDC 绑定与配额用量

注册要落地四张表:联系方式、一次性验证码、待核验申请、重置令牌;OIDC 的 sub
还要与本地用户绑定。配额的用量单独一张,不去改 tenants 的列 —— 策略留在配置里。

Revision ID: 011
Revises: 010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_contacts"),
    )
    op.create_index("ix_user_contacts_target", "user_contacts", ["kind", "target"], unique=True)
    op.create_index("ix_user_contacts_user", "user_contacts", ["user_id"])

    op.create_table(
        "verification_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_verification_codes"),
    )
    op.create_index(
        "ix_verification_codes_target", "verification_codes", ["channel", "target", "purpose"]
    )

    op.create_table(
        "user_activations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_activations"),
    )
    op.create_index("ix_user_activations_target", "user_activations", ["channel", "target"], unique=True)

    op.create_table(
        "password_reset_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name="pk_password_reset_tokens"),
    )
    op.create_index("ix_password_reset_user", "password_reset_tokens", ["user_id"])

    op.create_table(
        "external_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_external_identities"),
    )
    op.create_index(
        "ix_external_identities_subject", "external_identities", ["issuer", "subject"], unique=True
    )
    op.create_index("ix_external_identities_user", "external_identities", ["user_id"])

    op.create_table(
        "quota_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quota_usage"),
    )
    op.create_index(
        "ix_quota_usage_subject", "quota_usage", ["subject_kind", "subject_id", "resource", "used_at"]
    )


def downgrade() -> None:
    op.drop_table("quota_usage")
    op.drop_table("external_identities")
    op.drop_table("password_reset_tokens")
    op.drop_table("user_activations")
    op.drop_table("verification_codes")
    op.drop_table("user_contacts")
