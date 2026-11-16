"""仓库身份:来源 + 平台侧 id 唯一,并允许平台侧不给 id

`projects.github_id` 是"GitHub 上的数字 id"。接第二个来源那天起它就是错的:
CNB / GitLab 的 id 与 GitHub 的 id 不在同一个身份证体系里,同一个数字在两边
指的是两份不同的代码。而 payload 里这一栏来自适配器,没有 id 的来源(GitLab
的某些投递、临时注册的仓库)会传 None。

所以:加 `source`(哪个平台,与 tenants 的"哪个团队"是两个正交的维度),
唯一键从 (tenant_id, github_id) 换成 (tenant_id, source, name) —— 仓库全名
才是跨来源唯一的东西;`github_id` 保留,降为"来源自己给的 id,可以没有"。

存量行回填 source='github'。
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("source", sa.String(32), nullable=False, server_default="github"),
    )
    op.alter_column("projects", "github_id", existing_type=sa.BigInteger(), nullable=True)

    op.drop_constraint("uq_projects_tenant_id", "projects", type_="unique")
    op.create_unique_constraint(
        "uq_projects_tenant_source_name", "projects", ["tenant_id", "source", "name"]
    )
    op.create_index("ix_projects_tenant_source", "projects", ["tenant_id", "source"])


def downgrade() -> None:
    # 有损:同一租户下同一仓库名出现在两个来源时,合回 github_id 唯一会失败。
    op.execute("DELETE FROM projects WHERE github_id IS NULL")
    op.drop_index("ix_projects_tenant_source", table_name="projects")
    op.drop_constraint("uq_projects_tenant_source_name", "projects", type_="unique")
    op.alter_column("projects", "github_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_unique_constraint("uq_projects_tenant_id", "projects", ["tenant_id", "github_id"])
    op.drop_column("projects", "source")
