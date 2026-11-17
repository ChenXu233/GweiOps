"""项目这一级:projects 加 parent_id + slug,唯一键换成 (租户, slug)

上一版(016)把仓库身份定成 (租户, 来源, 仓库全名),解决了"两个来源的 12345
不是同一份代码";但仓库上面没有父,`租户 → 仓库` 只有一层。于是项目级的东西
(可见性、默认动作、凭据)没有地方摆,子仓 `platform/team-a` 也无处安放。

这一版补上中间那一级:

- 自引用的 `parent_id`:空 = 这一行是项目,非空 = 这一行是某个项目下的仓库
- `slug`:在这棵树上唯一且稳定的名字,仓库是 `来源-仓库全名`
  (github-acme-api / cnb-acme-api,`/` 也压成 `-`),项目取人给的那一段。
  分隔符一律 `-`,URL 里不用转义;反过来不可逆,要拆开读 source / name
- 唯一键从 (租户, 来源, 仓库全名) 换成 (租户, slug)

存量行没有父:`parent_id` 留空,`slug` 回填成 "来源-仓库全名"(没有来源时就是
仓库全名),每行因此各自是一个项目下的仓库——旧的平铺视图在界面上仍然看得见,
只是多了一层"这个仓库和谁是一家"可以填。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("parent_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_projects_parent_id",
        "projects",
        "projects",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("projects", sa.Column("slug", sa.String(255), nullable=True))

    # 回填:来源为空时就是仓库全名;有来源时带上前缀,免得 github/cnb 同名的两个仓库
    # 在同一个租户里撞成一行。
    op.execute(
        """
        UPDATE projects
           SET slug = CASE
                        WHEN COALESCE(source, '') = '' THEN replace(name, '/', '-')
                        ELSE source || '-' || replace(name, '/', '-')
                      END
        """
    )
    op.alter_column("projects", "slug", existing_type=sa.String(255), nullable=False)

    op.drop_constraint("uq_projects_tenant_source_name", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_tenant_slug", "projects", ["tenant_id", "slug"])
    # 查找永远是"先定租户":给 (租户, 父) 一条索引,列表按它分组。
    op.create_index("ix_projects_tenant_parent", "projects", ["tenant_id", "parent_id"])


def downgrade() -> None:
    # 有损:项目行没有来源与仓库全名,合回 (租户, 来源, 仓库全名) 唯一时会撞。
    op.execute("DELETE FROM projects WHERE parent_id IS NULL")
    op.drop_index("ix_projects_tenant_parent", table_name="projects")
    op.drop_constraint("uq_projects_tenant_slug", "projects", type_="unique")
    op.create_unique_constraint(
        "uq_projects_tenant_source_name", "projects", ["tenant_id", "source", "name"]
    )
    op.drop_column("projects", "slug")
    op.drop_constraint("fk_projects_parent_id", "projects", type_="foreignkey")
    op.drop_column("projects", "parent_id")
