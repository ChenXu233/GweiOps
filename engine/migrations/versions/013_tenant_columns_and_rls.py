"""租户列补齐与行级安全

在此之前,`issues` / `pull_requests` / `patches` / `approval_votes` 四张表没有
租户列,只能经 `projects` 那条链推出来。两跳能让"人写的 SQL"正确,但拦不住
"忘了写 where"的 SQL——而插件读库正是这种情况。

这一版做三件事:

1. 给 `issues` 加租户列(它直连 `projects`,`projects.tenant_id` 非空),回填后置非空;
2. `pull_requests` / `patches` / `approval_votes` 不加列,租户口径由父表派生——
   多一份租户列就多一份会漂移的事实;
3. 给租户可见的表开行级安全。策略按 `current_setting('gwei.tenant', true)` 收口:
   变量没设时它返回 NULL,比较结果永远为假。**默认看不见,而不是看得见。**
   核心自己的连接不设这个变量,因此不受影响。

Revision ID: 013
Revises: 012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

TENANT = "current_setting('gwei.tenant', true)"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# 自带租户字符串列的表
DIRECT = (
    "change_events",
    "incidents",
    "plugin_settings",
    "api_keys",
    "console_sessions",
    "console_messages",
)
# 有 tenant_id(uuid)的表。
# tenants 自己按 id 判:设了租户就只能看见自己那一行。
BY_UUID = ("projects", "roles", "users")
# 只能由父表派生的表
DERIVED = {
    "issues": f"project_id IN (SELECT id FROM projects WHERE tenant_id::text = {TENANT})",
    "patches": (
        "session_id IN (SELECT s.id FROM agent_sessions s "
        f"JOIN issues i ON i.id = s.issue_id WHERE i.tenant_id::text = {TENANT})"
    ),
    "pull_requests": (
        "patch_id IN (SELECT p.id FROM patches p "
        "JOIN agent_sessions s ON s.id = p.session_id "
        f"JOIN issues i ON i.id = s.issue_id WHERE i.tenant_id::text = {TENANT})"
    ),
    "approval_votes": (
        "pr_id IN (SELECT pr.id FROM pull_requests pr "
        "JOIN patches p ON p.id = pr.patch_id "
        "JOIN agent_sessions s ON s.id = p.session_id "
        f"JOIN issues i ON i.id = s.issue_id WHERE i.tenant_id::text = {TENANT})"
    ),
}


def _policy(table: str, using: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    # FORCE 让表属主也受策略约束:部署里核心与插件常常共用同一个库角色,
    # 少了这一句,策略只拦别人,拦不住自己。
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        f"USING ({using}) WITH CHECK ({using})"
    )


def _drop_policy(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    # 1) issues 补租户列,回填后置非空
    op.add_column(
        "issues", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.execute(
        "UPDATE issues SET tenant_id = p.tenant_id FROM projects p "
        "WHERE issues.project_id = p.id"
    )
    # project_id 为空的历史行按默认租户收口,不留 NULL——NULL 在策略里等于谁都看不见
    op.execute(f"UPDATE issues SET tenant_id = '{DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL")
    op.alter_column(
        "issues",
        "tenant_id",
        nullable=False,
        existing_type=postgresql.UUID(as_uuid=True),
    )
    op.create_foreign_key(
        "fk_issues_tenant_id_tenants", "issues", "tenants", ["tenant_id"], ["id"]
    )
    op.create_index("ix_issues_tenant", "issues", ["tenant_id"])

    # 2) 行级安全
    for table in DIRECT:
        _policy(table, f"tenant = {TENANT}")
    op.execute(f"ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenants "
        f"USING (id::text = {TENANT}) WITH CHECK (id::text = {TENANT})"
    )
    for table in BY_UUID:
        _policy(table, f"tenant_id::text = {TENANT}")
    for table, using in DERIVED.items():
        _policy(table, using)


def downgrade() -> None:
    for table in list(DERIVED) + list(BY_UUID) + ["tenants"] + list(DIRECT):
        _drop_policy(table)
    op.drop_index("ix_issues_tenant", table_name="issues")
    op.drop_constraint("fk_issues_tenant_id_tenants", "issues", type_="foreignkey")
    op.drop_column("issues", "tenant_id")
