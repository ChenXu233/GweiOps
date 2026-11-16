"""插件只读视图与受限角色

插件读库只该看见"它干活需要的事实",不该看见内部列与别人的账。这一版建三样:

1. 三张视图 `v_plugin_changes` / `v_plugin_incidents` / `v_plugin_issues`,
   形状固定、去掉内部列;
2. `gwei_plugin_reader` 角色:只 `SELECT` 这三张视图,不碰基表;
3. 视图定义里带 `security_invoker = true` —— 视图按**查询者**的权限与策略求值。

第 3 条是这个文件里唯一需要解释的地方。视图默认按属主权限求值(`security_definer` 语义),
而属主通常就是部署里的迁移账号;属主是超级用户时,底表的行级安全对它整个不生效
(超级用户与 `BYPASSRLS` 角色绕过策略,`FORCE ROW LEVEL SECURITY` 也拦不住)。
于是"租户只能看见自己的账"在视图里根本不会发生。加上 `security_invoker` 之后,
求值身份变成插件自己:受限角色、只读、受策略约束。

代价是底表的 `SELECT` 也要授给插件角色——因为 `security_invoker` 要求查询者自己能读
基表。这一点由 §"基表授权"承担:授的是 `SELECT`,不授 `INSERT/UPDATE/DELETE`,
所以"插件只能读、要写就走出口"这条约束仍然成立;可见范围由策略决定,不由 SQL 决定。

Revision ID: 014
Revises: 013
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

ROLE = "gwei_plugin_reader"

VIEWS: dict[str, str] = {
    # 账本一行:判定与依据都在 payload 里,内部列不透出去
    "v_plugin_changes": """
        SELECT tenant,
               unit_id,
               binding,
               verdict,
               idempotency_key,
               created_at,
               payload ->> 'capability' AS capability,
               payload ->> 'reason' AS reason
          FROM change_events
    """,
    "v_plugin_incidents": """
        SELECT tenant,
               id,
               signal_title AS title,
               status,
               started_at,
               finished_at AS closed_at
          FROM incidents
    """,
    "v_plugin_issues": """
        SELECT p.tenant_id,
               i.id,
               i.number,
               i.title,
               i.status,
               i.created_at
          FROM issues i
          JOIN projects p ON p.id = i.project_id
    """,
}

# 视图背后的基表:插件角色需要能 `SELECT` 它们,可见范围由策略收口。
BASE_TABLES = ("change_events", "incidents", "issues", "projects", "agent_sessions",
               "patches", "pull_requests")


def upgrade() -> None:
    op.execute(
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN "
        f"CREATE ROLE {ROLE} NOLOGIN; "
        f"END IF; END $$;"
    )
    # 只读:授 SELECT,不授写。写世界只能从出口走,这条不是靠自觉。
    for table in BASE_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {ROLE}")
    op.execute(f"GRANT USAGE ON schema public TO {ROLE}")
    for name, body in VIEWS.items():
        op.execute(
            f"CREATE OR REPLACE VIEW {name} WITH (security_invoker = true) AS {body.strip()}"
        )
        op.execute(f"REVOKE ALL ON {name} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON {name} TO {ROLE}")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")
    for table in BASE_TABLES:
        op.execute(f"REVOKE SELECT ON {table} FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON schema public FROM {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")
