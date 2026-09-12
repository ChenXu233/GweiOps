"""tenants table and per-tenant scoping

新增 tenants 表;projects 挂接租户;(tenant_id, github_id) 复合唯一替代
github_id 全局唯一(不同租户可安装同一仓库);issues 改 (project_id, github_id)
复合唯一(project 隶属唯一租户,等价保证租户内唯一)。存量数据回填默认租户。

Revision ID: 004
Revises: 003
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 固定 UUID 便于 downgrade 精确清理
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("settings", postgresql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
    )
    op.execute(
        "INSERT INTO tenants (id, slug, name, created_at) "
        f"VALUES ('{DEFAULT_TENANT_ID}', 'default', 'Default Tenant', now())"
    )

    op.add_column(
        "projects",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.execute(f"UPDATE projects SET tenant_id = '{DEFAULT_TENANT_ID}'")
    op.alter_column("projects", "tenant_id", nullable=False, existing_type=postgresql.UUID(as_uuid=True))
    op.create_foreign_key(
        "fk_projects_tenant_id_tenants", "projects", "tenants", ["tenant_id"], ["id"]
    )

    # github_id 全局唯一 → 租户内唯一(001 的命名约定为 uq_<table>_<column>)
    op.drop_constraint("uq_projects_github_id", "projects", type_="unique")
    op.create_unique_constraint(
        "uq_projects_tenant_id", "projects", ["tenant_id", "github_id"]
    )
    op.drop_constraint("uq_issues_github_id", "issues", type_="unique")
    op.create_unique_constraint(
        "uq_issues_project_id", "issues", ["project_id", "github_id"]
    )


def downgrade() -> None:
    # 注意:若已存在跨租户同仓库数据,恢复全局唯一会因重复失败——
    # 这是不可自动合并的有损回滚,失败时需人工归并数据。
    op.drop_constraint("uq_issues_project_id", "issues", type_="unique")
    op.drop_constraint("uq_projects_tenant_id", "projects", type_="unique")
    op.create_unique_constraint("uq_issues_github_id", "issues", ["github_id"])
    op.create_unique_constraint("uq_projects_github_id", "projects", ["github_id"])
    op.drop_constraint("fk_projects_tenant_id_tenants", "projects", type_="foreignkey")
    op.drop_column("projects", "tenant_id")
    op.execute(f"DELETE FROM tenants WHERE id = '{DEFAULT_TENANT_ID}'")
    op.drop_table("tenants")
