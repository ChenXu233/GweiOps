"""身份拆开:人(person)与成员关系(membership)

`users` 一行同时装着两件生命周期完全不同的事:`email` / `password_hash` /
`last_login_at` 属于**这个人**;`tenant_id` / `parent_id` / `permissions` 属于
**他在这一个工作区里的**角色。他凭邀请进第二个工作区时,按 (tenant_id, email)
唯一必须再插一行:第二份密码、两个"最后登录"、改密码要改两处,然后两处必然漂移。

这一版把它拆成两份:

- `persons`:一个人一行,`email` 在**整个部署**里唯一,凭据跟着人走
- `memberships`:人 × 工作区一行,`user_id` 是主键(列名不变——会话、审计、
  `UserRole.user_id`、"谁点的头"问的一直是"这个工作区里的哪个人")
- `user_sessions` / `user_contacts` / `password_reset_tokens` /
  `external_identities` 改挂到 `persons`:一次登录,多道门

一次到位(先双写再删旧列是两步的代价,而这个部署里还没有第二个工作区的人):
同一个 email 出现在两个租户里时并成一条 person + 两条 membership,密码取
"最近登录过的那一行",审计记一条。并表清单可以用
`engine.identity.migration_report` 重新列出。

down 有损:拆开之后的 person 没法判断原来属于哪个工作区,只能按 membership
逐条写回 `users` —— 同一个人在多个工作区里会重新变成多行、多份密码,那正是
这一版要消灭的形状。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) `users` 上带着 013 给的行级安全策略。它要退场,策略得先摘掉 —— 表都删了,
    #    down 的时候按同一个名字再建回来。
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "users"')
    op.execute('ALTER TABLE "users" NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "users" DISABLE ROW LEVEL SECURITY')

    # 1) persons:邮箱全部署唯一。并同一个邮箱的多行是这次迁移唯一"有判断"的地方。
    op.create_table(
        "persons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_persons_email"),
    )

    # 每一条 users 行都变成一条 person;同一 email 的多行取同一 id(最早建的那行)。
    op.execute(
        """
        INSERT INTO persons (id, email, display_name, password_hash, status, created_at, last_login_at)
        SELECT DISTINCT ON (lower(email))
               id, lower(email), display_name, password_hash, status, created_at, last_login_at
          FROM users
         ORDER BY lower(email), created_at
        """
    )
    # 并进来的那些行把显示名与"最后登录"让给存活的那一条:人只有一份履历。
    op.execute(
        """
        UPDATE persons p
           SET last_login_at = GREATEST(p.last_login_at, agg.last_login_at),
               display_name = CASE WHEN p.display_name = '' THEN agg.display_name ELSE p.display_name END
          FROM (
                SELECT lower(u.email) AS email, MAX(u.last_login_at) AS last_login_at,
                       MAX(u.display_name) AS display_name
                  FROM users u GROUP BY lower(u.email)
               ) agg
         WHERE p.email = agg.email
        """
    )

    # 2) memberships:人 × 工作区。`user_id` 沿用旧 users.id,会话与角色不用改指。
    op.create_table(
        "memberships",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("memberships.user_id", ondelete="CASCADE"), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "person_id", name="uq_memberships_tenant_person"),
    )
    op.create_index("ix_memberships_tenant", "memberships", ["tenant_id"])
    op.execute(
        """
        INSERT INTO memberships (user_id, tenant_id, person_id, parent_id, display_name, permissions, status, created_at)
        SELECT u.id, u.tenant_id, p.id, u.parent_id, u.display_name, u.permissions, u.status, u.created_at
          FROM users u
          JOIN persons p ON p.email = lower(u.email)
        """
    )

    # 3) 会话、联系方式、找回密码、OIDC 绑定改挂到人
    op.add_column("user_sessions", sa.Column("person_id", UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE user_sessions s SET person_id = p.id
          FROM users u JOIN persons p ON p.email = lower(u.email)
         WHERE u.id = s.user_id
        """
    )
    op.execute("DELETE FROM user_sessions WHERE person_id IS NULL")
    op.drop_index("ix_user_sessions_user", table_name="user_sessions")
    op.drop_column("user_sessions", "user_id")
    op.alter_column("user_sessions", "person_id", nullable=False)
    op.create_foreign_key(
        "fk_user_sessions_person", "user_sessions", "persons", ["person_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_user_sessions_person", "user_sessions", ["person_id"])

    op.add_column("user_contacts", sa.Column("person_id", UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE user_contacts c SET person_id = p.id
          FROM users u JOIN persons p ON p.email = lower(u.email)
         WHERE u.id = c.user_id
        """
    )
    # 并表之后同一个人可能有两条同名联系方式:留最早的一条
    op.execute(
        """
        DELETE FROM user_contacts c USING user_contacts keep
         WHERE c.person_id = keep.person_id AND c.kind = keep.kind
           AND c.target = keep.target AND c.id > keep.id
        """
    )
    op.execute("DELETE FROM user_contacts WHERE person_id IS NULL")
    op.drop_index("ix_user_contacts_user", table_name="user_contacts")
    op.drop_column("user_contacts", "user_id")
    op.alter_column("user_contacts", "person_id", nullable=False)
    op.create_foreign_key(
        "fk_user_contacts_person", "user_contacts", "persons", ["person_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_user_contacts_person", "user_contacts", ["person_id"])

    op.add_column("password_reset_tokens", sa.Column("person_id", UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE password_reset_tokens t SET person_id = p.id
          FROM users u JOIN persons p ON p.email = lower(u.email)
         WHERE u.id = t.user_id
        """
    )
    op.execute("DELETE FROM password_reset_tokens WHERE person_id IS NULL")
    op.drop_index("ix_password_reset_user", table_name="password_reset_tokens")
    op.drop_column("password_reset_tokens", "user_id")
    op.alter_column("password_reset_tokens", "person_id", nullable=False)
    op.create_foreign_key(
        "fk_password_reset_person", "password_reset_tokens", "persons", ["person_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_password_reset_person", "password_reset_tokens", ["person_id"])

    op.add_column("external_identities", sa.Column("person_id", UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE external_identities e SET person_id = p.id
          FROM users u JOIN persons p ON p.email = lower(u.email)
         WHERE u.id = e.user_id
        """
    )
    op.execute("DELETE FROM external_identities WHERE person_id IS NULL")
    op.drop_index("ix_external_identities_user", table_name="external_identities")
    op.drop_column("external_identities", "user_id")
    op.alter_column("external_identities", "person_id", nullable=False)
    op.create_foreign_key(
        "fk_external_identities_person", "external_identities", "persons", ["person_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_external_identities_person", "external_identities", ["person_id"])

    # 审计里的 actor_id 一直是裸 uuid(006 没给它建外键),值是 users.id,也就是
    # 现在的 memberships.user_id —— 这里不用改。补上外键则是把"这个人被移出去了"
    # 这件事处理掉:留着 id 而人不在,审计就是一条查不到人的记录。
    # 加外键之前先清掉指向"已经不在这份名单里的人"的行。历史审计里会有这种人:
    # 用户被删掉、或者这一版之前就存在的实验账号。不清就加外键,升级过的库一律
    # 卡在 ForeignKeyViolationError,而迁移是启动路径上的第一步——整个引擎起不来。
    op.execute(
        """
        UPDATE audit_log a SET actor_id = NULL
         WHERE a.actor_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = a.actor_id)
        """
    )
    op.create_foreign_key(
        "fk_audit_log_actor", "audit_log", "memberships", ["actor_id"], ["user_id"], ondelete="SET NULL"
    )

    # 4) 旧表退场:它现在只剩"人"与"成员关系"两半,两半都搬走了。
    #    user_roles.user_id 指向 memberships —— 先把外键改指再删表,否则删表会带走它。
    #   名字按改名之前的形状找,不写死:006 建约束时用的是 metadata 的命名约定
    #   (`fk_user_roles_user_id_users`),006 之后这张表又被 create_all 建过一次的地方
    #   会是 Postgres 的默认名(`user_roles_user_id_fkey`)。写死其中一个,另一种库上
    #   这一版就升不上去 —— 迁移只该认"user_id 这一列上指向 users 的那个外键"。
    op.execute(
        """
        DO $$
        DECLARE found text;
        BEGIN
            FOR found IN
                SELECT con.conname
                  FROM pg_constraint con
                  JOIN pg_class rel ON rel.oid = con.conrelid
                  JOIN pg_class ref ON ref.oid = con.confrelid
                 WHERE rel.relname = 'user_roles'
                   AND con.contype = 'f'
                   AND ref.relname = 'users'
            LOOP
                EXECUTE format('ALTER TABLE user_roles DROP CONSTRAINT %I', found);
            END LOOP;
        END $$;
        """
    )
    op.create_foreign_key(
        "fk_user_roles_membership", "user_roles", "memberships", ["user_id"], ["user_id"], ondelete="CASCADE"
    )
    op.drop_table("users")


def downgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False, server_default=""),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant", "users", ["tenant_id"])
    op.execute('ALTER TABLE "users" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "users" FORCE ROW LEVEL SECURITY')
    op.execute(
        "CREATE POLICY tenant_isolation ON users "
        "USING (tenant_id::text = current_setting('gwei.tenant', true)) "
        "WITH CHECK (tenant_id::text = current_setting('gwei.tenant', true))"
    )
    op.execute(
        """
        INSERT INTO users (id, tenant_id, parent_id, email, display_name, password_hash, permissions, status, created_at, last_login_at)
        SELECT m.user_id, m.tenant_id, m.parent_id, p.email, m.display_name, p.password_hash,
               m.permissions, p.status, m.created_at, p.last_login_at
          FROM memberships m JOIN persons p ON p.id = m.person_id
        """
    )

    op.drop_constraint("fk_audit_log_actor", "audit_log", type_="foreignkey")

    op.drop_constraint("fk_user_roles_membership", "user_roles", type_="foreignkey")
    op.create_foreign_key(
        "user_roles_user_id_fkey", "user_roles", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )

    for table, index, constraint, column in (
        ("user_sessions", "ix_user_sessions_person", "fk_user_sessions_person", "user_id"),
        ("user_contacts", "ix_user_contacts_person", "fk_user_contacts_person", "user_id"),
        ("password_reset_tokens", "ix_password_reset_person", "fk_password_reset_person", "user_id"),
        ("external_identities", "ix_external_identities_person", "fk_external_identities_person", "user_id"),
    ):
        op.add_column(table, sa.Column(column, UUID(as_uuid=True), nullable=True))
        op.execute(
            f"""
            UPDATE {table} t SET {column} = m.user_id
              FROM memberships m JOIN persons p ON p.id = m.person_id
             WHERE m.person_id = t.person_id
            """
        )
        op.execute(f"DELETE FROM {table} WHERE {column} IS NULL")
        op.drop_index(index, table_name=table)
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.drop_column(table, "person_id")
        op.alter_column(table, column, nullable=False)
        op.create_foreign_key(
            f"{table}_user_id_fkey", table, "users", [column], ["id"], ondelete="CASCADE"
        )

    op.drop_index("ix_memberships_tenant", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("persons")
