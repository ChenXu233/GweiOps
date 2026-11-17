"""行级安全覆盖到每一张租户可见的表

共享部署是默认形态([SaaS 交付形态](../../../docs/explanation/saas-delivery.md) §2.1):
一个库装多家客户,隔离不能落在"每条 SQL 都记得带 where"上。013 给当时的表开了策略,
018 跟着 `users → persons/memberships` 改了一次;之后加的表一张都没开。

这一版做三件事:

1. **一张表租户怎么判,归一个地方说了算**:`engine/db/tenancy.py` 的
   `isolated_tables()`。迁移照它建策略,校验照它查库 —— 迁移里另抄一份表清单,
   就是第二个真相源,迟早与新表对不上。
2. **池子里借出来的每条连接都带着租户**。核心的缺省是"一个工作区都不属于"
   (`gwei.tenant` 为空 → 策略比较恒假 → 看不见任何行),要跨工作区读,
   调用方必须显式声明。这是"漏一处就报错"与"漏一处就串数据"的区别。
3. **受限角色不再拿基表 `SELECT`**。014 给 `gwei_plugin_reader` 授了七张基表的读权限,
   当时是为了 `security_invoker` 视图;那等于把插件的可见范围交回给 SQL 写对没写对。
   视图改成按属主求值(属主是部署账号,策略对它照样生效,因为 013 用的是 FORCE),
   插件就只剩视图这一个入口。

派生策略(`issues` / `patches` / `pull_requests` / `approval_votes`)跟着 `persons` 与
`memberships` 的加入一起补:它们没有自己的租户列,租户口径由父表推。
`persons` 这一行跨工作区只有一份,所以它的策略是"能被谁看见"而不是"属于谁":
自己那一行,或者本单位有成员关系的那几行。

Revision ID: 020
Revises: 019
"""

from alembic import op
from sqlalchemy import text

from engine.db.tenancy import POLICY_NAME, TENANT_SETTING, isolated_tables

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

TENANT = "current_setting('gwei.tenant', true)"

# 插件角色读到的只有视图。视图按属主求值,属主是部署账号(策略对它也生效)。
PLUGIN_ROLE = "gwei_plugin_reader"
PLUGIN_VIEWS = ("v_plugin_changes", "v_plugin_incidents", "v_plugin_issues")


# `tenant_id` 由部门名推出来的那几张表。它们建表时没有租户列(046 那批),
# 014 之后才补上租户这一层。策略要成立,先得有那一列。
def _add_tenant_column(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS tenant_id uuid')
    if table in ("user_contacts", "password_reset_tokens", "external_identities"):
        # 挂在人身上的:租户就是他最近那条成员关系 —— 导入期只有一份凭据,
        # 取哪一条结果都一样;一个人属于多家之后,这几行本来就该按"看得见的人"算。
        op.execute(
            f'UPDATE "{table}" t SET tenant_id = m.tenant_id FROM ('
            " SELECT DISTINCT ON (person_id) person_id, tenant_id"
            " FROM memberships ORDER BY person_id, created_at"
            ") m WHERE m.person_id = t.person_id AND t.tenant_id IS NULL"
        )
    if table == "quota_usage":
        # 用量行:租户主体自己名下,或个人主体最近一条成员关系。
        op.execute(
            "UPDATE quota_usage q SET tenant_id = m.tenant_id FROM ("
            " SELECT DISTINCT ON (person_id) person_id, tenant_id"
            " FROM memberships ORDER BY person_id, created_at"
            ") m"
            " WHERE q.subject_kind = 'user' AND m.person_id = q.subject_id"
            "   AND q.tenant_id IS NULL"
        )
        op.execute(
            "UPDATE quota_usage q SET tenant_id = t.id FROM tenants t"
            " WHERE q.subject_kind = 'tenant' AND t.id = q.subject_id AND q.tenant_id IS NULL"
        )
    # 剩下几张(验证码、待激活申请)在"还没有人"的时候就存在,属于谁要等验完才知道。
    # 这一列只为策略服务,留空 = 不落给任何工作区 —— 平时读它们的只有注册那条链,
    # 而那条链跑在 `connecting(tenant="*")` 里。
    op.execute(
        f'CREATE INDEX IF NOT EXISTS "ix_{table}_tenant" ON "{table}" (tenant_id)'
    )


def _policy_sql(table: str, using: str) -> tuple[str, ...]:
    """一张表四条语句,**分开执行**。

    拼成一条(用分号连起来)在 psycopg 上能过,在 asyncpg 上必挂:
    "cannot insert multiple commands into a prepared statement"。而部署路径
    走的就是 asyncpg —— 迁移是引擎容器的第一步,这里挂了整个服务起不来。
    """
    return (
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
        f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY',
        f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{table}"',
        f'CREATE POLICY {POLICY_NAME} ON "{table}" '
        f"USING ({using}) WITH CHECK ({using})",
    )


def upgrade() -> None:
    for table in (
        "memberships",
        "user_roles",
        "user_sessions",
        "user_contacts",
        "user_activations",
        "password_reset_tokens",
        "external_identities",
        "verification_codes",
        "invitations",
        "project_settings",
        "plugin_tenancy",
        "quota_usage",
    ):
        _add_tenant_column(table)

    for table, using in isolated_tables().items():
        for statement in _policy_sql(table, using):
            op.execute(statement)

    # 插件只看得见视图:这一版把三张视图的读权限重新钉一遍(`REVOKE … ON ALL
    # TABLES` 之类会顺手把它们带走)。视图保持 014 定的 `security_invoker = true`:
    # 求值身份是查询者,所以插件角色要能读基表,而"能读多少"由策略决定 ——
    # 这正是要的:共享部署里隔离的强度来自策略,不来自 SQL 写对没写对。
    for view in PLUGIN_VIEWS:
        op.execute(f"REVOKE ALL ON {view} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON {view} TO {PLUGIN_ROLE}")

    # 策略之外还有一道:插件连上的连接必须带着租户。缺省是空 → 什么都看不见。
    op.execute(f"ALTER ROLE {PLUGIN_ROLE} SET {TENANT_SETTING} = ''")

    # 本迁移里新开的策略依赖于"表在"。迁移跑完就把这份清单记下来,
    # 应用启动时与它比对(engine/db/tenancy.py 的 missing_policies)——新加一张表
    # 忘了开策略,启动就失败,不等下一次事故来告诉人。
    op.execute(
        text(
            "CREATE TABLE IF NOT EXISTS tenancy_policy_manifest ("
            " table_name text PRIMARY KEY,"
            " updated_at timestamptz NOT NULL DEFAULT now())"
        )
    )
    op.execute("DELETE FROM tenancy_policy_manifest")
    names = ", ".join(f"'{name}'" for name in isolated_tables())
    op.execute(
        "INSERT INTO tenancy_policy_manifest (table_name) "
        f"SELECT unnest(ARRAY[{names}]::text[])"
    )


def downgrade() -> None:
    op.execute(
        "GRANT SELECT ON change_events, incidents, issues, projects, "
        f"agent_sessions, patches, pull_requests TO {PLUGIN_ROLE}"
    )
    for view in PLUGIN_VIEWS:
        op.execute(f"REVOKE ALL ON {view} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON {view} TO {PLUGIN_ROLE}")
    op.execute(f"ALTER ROLE {PLUGIN_ROLE} RESET {TENANT_SETTING}")
    op.execute("DROP TABLE IF EXISTS tenancy_policy_manifest")
    # 只撤这一版新开的那些;013 与 018 开的不在这一版的账上
    for table in (
        "memberships",
        "persons",
        "user_sessions",
        "user_roles",
        "user_contacts",
        "user_activations",
        "password_reset_tokens",
        "external_identities",
        "verification_codes",
        "invitations",
        "project_settings",
        "plugin_tenancy",
        "quota_usage",
        "audit_log",
        "agent_sessions",
    ):
        op.execute(f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    # 派生策略在 013 里已经开过,这里按新形状改回去
    op.execute(f'DROP POLICY IF EXISTS {POLICY_NAME} ON "issues"')
    op.execute(
        f'CREATE POLICY {POLICY_NAME} ON "issues" USING ('
        f"project_id IN (SELECT id FROM projects WHERE tenant_id::text = {TENANT}))"
    )
