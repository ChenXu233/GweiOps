"""邀请,以及项目这一级的值

两件都是"工作区与 SaaS 之间剩下的东西":

1. `invitations` —— 管理员发一条,被邀请人自己接手。原来"把人拉进来"只有一条
   路:管理员替他设一个初始密码,再用带外通道告诉他。那条路让管理员替别人想
   密码,也让同一个人被拉进第二个工作区时多出一份密码。邀请里只存工作区与
   被邀请的邮箱,令牌只存哈希:谁的邮箱谁接,密码他自己定。

2. `project_settings` —— 项目级的值:可见性、默认发布参数、项目级凭据。
   `plugin_settings` 的键是 (租户, scope, key),它只能回答"整个工作区怎么配";
   项目之间的差异原来只能靠"每个仓库抄一遍"表达,改一次要改三处。

两张新表都只是新增,不动存量行。`invitations.accepted_at` 用过之后再点那条
链接得到的是"已经用过了",不是一个看不懂的 404 —— 所以用过的行留着,不删。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("memberships.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("memberships.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("role_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_invitations_token", "invitations", ["token_hash"], unique=True)
    op.create_index("ix_invitations_tenant_email", "invitations", ["tenant_id", "email"])

    op.create_table(
        "project_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="workspace"),
        sa.Column("defaults", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("credentials", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_project_settings_project", "project_settings", ["project_id"], unique=True)
    op.create_index("ix_project_settings_tenant", "project_settings", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_project_settings_tenant", table_name="project_settings")
    op.drop_index("ix_project_settings_project", table_name="project_settings")
    op.drop_table("project_settings")
    op.drop_index("ix_invitations_tenant_email", table_name="invitations")
    op.drop_index("ix_invitations_token", table_name="invitations")
    op.drop_table("invitations")
